"""Local audio adapters. Models never download implicitly during normal use."""
from __future__ import annotations

import array
from dataclasses import asdict
import json
import math
import multiprocessing
import os
from pathlib import Path
import queue
import selectors
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any
import wave

from .state import Captured


def reap(process: Any, timeout: float = 1) -> None:
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
    except ProcessLookupError:
        pass
    finally:
        for stream in (getattr(process, "stdout", None), getattr(process, "stderr", None), getattr(process, "stdin", None)):
            if stream is not None:
                stream.close()


def model_process(kind: str, config: dict[str, Any], connection: Any) -> None:
    """A killable worker retains its model across jobs; messages stay on a local pipe."""
    try:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        if kind == "transcribe":
            import numpy as np
            import onnxruntime
            onnxruntime.disable_telemetry_events()
            from faster_whisper import WhisperModel
            model = WhisperModel(config["transcription_model_path"], device="cpu",
                                 compute_type=config["compute_type"], cpu_threads=config["cpu_threads"],
                                 num_workers=1, local_files_only=True)
        else:
            from piper import PiperVoice
            model = PiperVoice.load(config["tts_model_path"], use_cuda=False)
        connection.send({"ready": True})
        while True:
            request = connection.recv()
            if request is None:
                return
            if kind == "transcribe":
                samples = np.frombuffer(request, dtype="<i2").astype(np.float32) / 32768.0
                language = None if config["language"] == "auto" else config["language"]
                segments, _ = model.transcribe(samples, language=language, beam_size=config["beam_size"],
                                               vad_filter=True, condition_on_previous_text=False)
                result = " ".join(s.text.strip() for s in segments
                                  if s.no_speech_prob < .65 and s.avg_logprob > -1.0).strip()
                connection.send({"result": result[:8000]})
            else:
                text, path = request
                with wave.open(path, "wb") as wav:
                    model.synthesize_wav(text, wav)
                connection.send({"result": True})
    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        try:
            connection.send({"error": f"Local {kind} model failed; run jki doctor"})
        except (OSError, EOFError):
            pass
    finally:
        connection.close()


class ModelWorker:
    def __init__(self, kind: str, settings: Any):
        self.kind, self.settings = kind, settings
        self.lock = threading.RLock()
        self.process: Any = None
        self.connection: Any = None

    @staticmethod
    def _receive(connection: Any, process: Any, cancel: threading.Event, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while not cancel.is_set():
            if connection.poll(.1):
                result = connection.recv()
                if "error" in result:
                    raise RuntimeError(result["error"])
                return result
            if not process.is_alive():
                raise RuntimeError("Local model worker exited")
            if time.monotonic() >= deadline:
                raise TimeoutError("Local model timed out")
        raise InterruptedError("Local model request cancelled")

    def request(self, value: Any, cancel: threading.Event) -> Any:
        try:
            with self.lock:
                if cancel.is_set():
                    raise InterruptedError("Cancelled")
                new = self.process is None
                if new:
                    context = multiprocessing.get_context("spawn")
                    parent, child = context.Pipe()
                    process = context.Process(target=model_process,
                                              args=(self.kind, asdict(self.settings), child), daemon=True)
                    process.start()
                    child.close()
                    self.process, self.connection = process, parent
                process, connection = self.process, self.connection
            if new:
                self._receive(connection, process, cancel, 120)
            if cancel.is_set():
                raise InterruptedError("Cancelled")
            connection.send(value)
            return self._receive(connection, process, cancel, 120).get("result")
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        with self.lock:
            process, connection = self.process, self.connection
            self.process = self.connection = None
        if process:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            process.close()
        if connection:
            connection.close()


class AudioPipeline:
    def __init__(self, engine: Any):
        self.engine = engine
        self.lock = threading.RLock()
        self.recorder: Any = None
        self.player: Any = None
        self.synthesizer: Any = None
        self.transcriber = ModelWorker("transcribe", engine.settings)
        self.piper = ModelWorker("synthesize", engine.settings)

    def stop_capture(self) -> None:
        with self.lock:
            if self.recorder and self.recorder.poll() is None:
                self.recorder.terminate()

    def stop_output(self) -> None:
        with self.lock:
            for process in (self.player, self.synthesizer):
                if process and process.poll() is None:
                    process.terminate()
        self.piper.close()

    def close(self) -> None:
        self.stop_capture()
        self.stop_output()
        self.transcriber.close()

    def microphone_loop(self) -> None:
        engine = self.engine
        vosk_model = None
        failure_delay = 1.0
        while not engine.stopping.is_set():
            with engine.lock:
                settings = engine.settings
                epoch = engine.capture_epoch
            if not shutil.which("pw-record"):
                engine.component("microphone", "error")
                engine.stopping.wait(5)
                continue
            if engine.muted.is_set() or (settings.input_mode == "push-to-talk" and not engine.capture_active.is_set()):
                engine.component("microphone", "idle")
                engine.stopping.wait(.1)
                continue
            process = None
            audio = bytearray()
            remainder = bytearray()
            cancelled = False
            recognizer = None
            try:
                if settings.input_mode == "wake-word":
                    from vosk import Model, KaldiRecognizer, SetLogLevel
                    SetLogLevel(-1)
                    if vosk_model is None:
                        vosk_model = Model(settings.model_path)
                    recognizer = KaldiRecognizer(vosk_model, 16000)
                    recognizer.SetWords(True)
                command = ["pw-record", "--raw", "--rate", "16000", "--channels", "1",
                           "--format", "s16", "--latency", "100ms"]
                if settings.microphone:
                    command += ["--target", settings.microphone]
                command += ["-"]
                with self.lock:
                    if engine.stopping.is_set() or engine.muted.is_set():
                        continue
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
                    self.recorder = process
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    suppressed = False
                    while not engine.stopping.is_set() and not engine.muted.is_set():
                        with engine.lock:
                            if epoch != engine.capture_epoch or settings.input_mode != engine.settings.input_mode:
                                cancelled = True
                                break
                        if settings.input_mode == "push-to-talk" and not engine.capture_active.is_set():
                            break
                        if not selector.select(.1):
                            if process.poll() is not None:
                                raise RuntimeError("Microphone disconnected")
                            continue
                        chunk = os.read(process.stdout.fileno(), 3200)
                        if not chunk:
                            raise RuntimeError("Microphone disconnected")
                        remainder.extend(chunk)
                        length = len(remainder) // 2 * 2
                        if not length:
                            continue
                        chunk = bytes(remainder[:length])
                        del remainder[:length]
                        samples = array.array("h", chunk)
                        rms = math.sqrt(sum(x * x for x in samples) / max(1, len(samples))) / 32768
                        with engine.lock:
                            engine.level = min(1.0, rms * 8)
                            engine.health.microphone = "ready"
                        failure_delay = 1.0
                        if engine.speaking.is_set() or engine.clock() < engine.quiet_until:
                            audio.clear()
                            suppressed = True
                            continue
                        if suppressed:
                            if recognizer:
                                recognizer.Reset()
                            suppressed = False
                        audio.extend(chunk)
                        if len(audio) > 32000 * settings.max_utterance_seconds:
                            audio.clear()
                            if recognizer:
                                recognizer.Reset()
                            with engine.lock:
                                engine.gate.reset()
                                engine.health.error = "Recording limit reached. Please use a shorter command."
                            engine.capture_active.clear()
                            cancelled = True
                            break
                        if recognizer and recognizer.AcceptWaveform(chunk):
                            result = json.loads(recognizer.Result())
                            with engine.lock:
                                accepted = engine.gate.accept(result.get("text", ""), words=result.get("result", []))
                                engine.health.hearing = accepted is not None
                            if accepted:
                                engine.accept_audio(Captured(bytes(audio), epoch, engine.clock()))
                            audio.clear()
                if (settings.input_mode == "push-to-talk" and not cancelled and len(audio) >= 3200
                        and not engine.stopping.is_set() and not engine.muted.is_set()):
                    engine.accept_audio(Captured(bytes(audio), epoch, engine.clock()))
            except Exception:
                if not engine.stopping.is_set() and not engine.muted.is_set():
                    engine.component("microphone", "error")
                    engine.stopping.wait(failure_delay)
                    failure_delay = min(30, failure_delay * 2)
            finally:
                reap(process)
                with self.lock:
                    if self.recorder is process:
                        self.recorder = None
                with engine.lock:
                    engine.level = 0

    def transcription_loop(self) -> None:
        engine = self.engine
        # Loading is lazy; typed commands and the GUI are usable immediately.
        engine.component("transcription", "idle")
        while not engine.stopping.is_set():
            try:
                captured = engine.recognitions.get(timeout=.2)
            except queue.Empty:
                continue
            with engine.lock:
                if engine.muted.is_set() or not captured.valid(engine.capture_epoch, engine.clock(), engine.settings.command_ttl):
                    continue
                engine.health.hearing = True
            start = engine.clock()
            try:
                text = self.transcriber.request(captured.payload, engine.stopping)
                engine.component("transcription", "ready")
                # Only remove a leading address; preserve later mentions of the wake name.
                if engine.settings.input_mode == "wake-word":
                    import re
                    text = re.sub(r"^\s*(?:(?:hey|hi|hello|okay|ok)[,\s]+)?" +
                                  re.escape(engine.settings.wake_word) + r"\b[,\s]*", "", text, flags=re.I)
                engine.metrics.record("transcription", engine.clock() - start)
                engine.transcription_ready(text, captured)
            except Exception:
                if not engine.stopping.is_set():
                    engine.component("transcription", "error")
                    with engine.lock:
                        engine.health.hearing = False

    @staticmethod
    def _wait(process: Any, cancel: threading.Event, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancel.wait(.05):
                raise InterruptedError("Speech cancelled")
            if time.monotonic() >= deadline:
                raise TimeoutError("Audio subprocess timed out")
        if process.returncode:
            raise RuntimeError("Audio subprocess failed")

    def _espeak(self, text: str, path: str, cancel: threading.Event) -> None:
        process = None
        try:
            with self.lock:
                if cancel.is_set():
                    raise InterruptedError("Speech cancelled")
                # A regular temporary input file avoids blocking on a full stdin pipe.
                with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as input_stream:
                    input_stream.write(text)
                    input_stream.seek(0)
                    process = subprocess.Popen(["espeak-ng", "--stdin", "-v", self.engine.settings.voice,
                                                "-s", "178", "-w", path], stdin=input_stream,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.synthesizer = process
            self._wait(process, cancel, 30)
        finally:
            reap(process)
            with self.lock:
                if self.synthesizer is process:
                    self.synthesizer = None

    def speech_loop(self) -> None:
        engine = self.engine
        engine.component("tts", "idle")
        while not engine.stopping.is_set():
            try:
                speech = engine.speech.get(timeout=.2)
            except queue.Empty:
                continue
            with engine.lock:
                if speech.epoch != engine.speech_epoch:
                    continue
                if speech.progress and (speech.turn_id != engine.health.active_turn or engine.health.approvals
                                        or engine.health.cancelling or
                                        engine.clock() - speech.created > engine.settings.progress_interval):
                    continue
                cancel = threading.Event()
                engine.output_cancel = cancel
                engine.speaking.set()
                engine.gate.reset()
            process = None
            try:
                with tempfile.TemporaryDirectory(prefix="jake-speech-") as directory:
                    path = str(Path(directory) / "reply.wav")
                    if engine.settings.tts_engine == "piper":
                        try:
                            self.piper.request((speech.text, path), cancel)
                            engine.component("tts", "ready")
                        except Exception:
                            if cancel.is_set():
                                raise InterruptedError("Cancelled") from None
                            engine.component("tts", "fallback")
                            self._espeak(speech.text, path, cancel)
                    else:
                        self._espeak(speech.text, path, cancel)
                        engine.component("tts", "ready")
                    # Recheck after synthesis: completion/approval may have arrived meanwhile.
                    with engine.lock, self.lock:
                        stale = speech.progress and (
                            speech.turn_id != engine.health.active_turn or engine.health.approvals
                            or engine.health.cancelling
                            or engine.clock() - speech.created > engine.settings.progress_interval
                        )
                        if cancel.is_set() or engine.stopping.is_set() or stale:
                            continue
                        command = ["pw-play"]
                        if engine.settings.output_device:
                            command += ["--target", engine.settings.output_device]
                        command.append(path)
                        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        self.player = process
                    engine.metrics.record("speech_queue_to_playback", engine.clock() - speech.created)
                    playback_start = engine.clock()
                    self._wait(process, cancel, 180)
                    engine.metrics.record("playback_duration", engine.clock() - playback_start)
            except Exception:
                if not cancel.is_set() and not engine.stopping.is_set():
                    engine.component("tts", "error")
            finally:
                reap(process)
                with self.lock:
                    if self.player is process:
                        self.player = None
                with engine.lock:
                    engine.quiet_until = engine.clock() + .25
                    engine.speaking.clear()
