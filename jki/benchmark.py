"""Reproducible local measurements; synthetic timings are not model benchmarks."""
from __future__ import annotations

from dataclasses import asdict
import platform
import resource
import statistics
import tempfile
import threading
import time
from pathlib import Path
import wave

from .audio import ModelWorker
from .config import Settings
from .engine import Command, Engine


def summarize(samples: list[float]) -> dict[str, float | int]:
    ordered = sorted(samples)
    return {"count": len(samples), "p50_seconds": statistics.median(samples),
            "p95_seconds": ordered[max(0, int(len(ordered) * .95 + .999) - 1)]}


def benchmark(settings: Settings, *, wav_path: Path | None = None, iterations: int = 5) -> dict:
    if not 1 <= iterations <= 1000:
        raise ValueError("iterations must be between 1 and 1000")
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "machine": platform.machine(), "processor": platform.processor() or "not reported",
              "backend_used": False, "microphone_used": False}
    if wav_path:
        with wave.open(str(wav_path), "rb") as wav:
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
                raise ValueError("Benchmark WAV must be 16 kHz, mono, signed 16-bit PCM")
            if wav.getnframes() > 16000 * settings.max_utterance_seconds:
                raise ValueError("Benchmark recording exceeds configured duration limit")
            audio = wav.readframes(wav.getnframes())
        worker = ModelWorker("transcribe", settings)
        try:
            samples = []
            for _ in range(iterations):
                start = time.perf_counter()
                worker.request(audio, threading.Event())
                samples.append(time.perf_counter() - start)
            report.update(kind="local ASR", cold_seconds=samples[0], warm=summarize(samples[1:] or samples),
                          configuration={k: v for k, v in asdict(settings).items()
                                         if k in {"cpu_threads", "compute_type", "beam_size", "language"}})
        finally:
            worker.close()
    else:
        class FakeBackend:
            counter = 0
            def call(self, _method, _params, **kwargs):
                self.counter += 1
                return {"turn": {"id": str(self.counter), "status": "inProgress"}}
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(settings, Path(directory) / "config.json")
            engine.client = FakeBackend()
            engine.health.connected = True
            samples = []
            for _ in range(iterations):
                start = time.perf_counter()
                engine._execute(Command("command", "Benchmark fixture", engine.capture_epoch, engine.clock()))
                with engine.lock:
                    engine._finish_turn({"id": engine.health.active_turn, "status": "completed"})
                engine.snapshot()
                samples.append(time.perf_counter() - start)
            report.update(kind="synthetic orchestration; NO audio, GUI, or model execution", timings=summarize(samples))
    report["process_peak_rss_kib_linux"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return report
