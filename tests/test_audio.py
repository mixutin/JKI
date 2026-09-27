from dataclasses import asdict
import io
import os
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from jki.audio import AudioPipeline, model_process, reap
from jki.config import Settings
from tests.helpers import EngineFixture, wait_for


class AudioTests(EngineFixture, unittest.TestCase):
    def test_reap_escalates_and_waits_after_kill(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("fixture", 1), 0]
        process.stdout, process.stderr, process.stdin = io.BytesIO(), io.BytesIO(), None
        reap(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_real_owned_subprocess_is_reaped(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        reap(process)
        self.assertIsNotNone(process.poll())
        reap(process)

    def test_cancel_during_synthesis_cannot_start_playback(self):
        pipeline = AudioPipeline(self.engine)
        self.engine.audio = pipeline
        def synthesize(*_):
            self.engine.stop_speaking()
            self.engine.stopping.set()
        pipeline._espeak = synthesize
        self.engine.say("Test output")
        with patch("jki.audio.subprocess.Popen") as launch:
            pipeline.speech_loop()
        launch.assert_not_called()
        self.assertFalse(self.engine.speaking.is_set())

    def test_failed_tts_does_not_disable_backend(self):
        pipeline = AudioPipeline(self.engine)
        self.engine.audio = pipeline
        pipeline._espeak = Mock(side_effect=FileNotFoundError("espeak-ng"))
        self.engine.say("Test output")
        self.engine._spawn(pipeline.speech_loop, "test-speech")
        wait_for(lambda: self.engine.health.tts == "error")
        self.assertTrue(self.engine.health.connected)

    def test_model_loading_is_offline_only(self):
        constructor = Mock()
        connection = Mock()
        connection.recv.return_value = None
        fake = {"numpy": SimpleNamespace(), "onnxruntime": SimpleNamespace(disable_telemetry_events=Mock()),
                "faster_whisper": SimpleNamespace(WhisperModel=constructor)}
        with patch.dict(sys.modules, fake), patch.dict(os.environ):
            model_process("transcribe", asdict(Settings()), connection)
            self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
        self.assertTrue(constructor.call_args.kwargs["local_files_only"])
        self.assertEqual(constructor.call_args.kwargs["compute_type"], "int8")
        connection.close.assert_called_once()

    def test_ptt_key_repeat_does_not_reset_recording(self):
        self.engine.begin_capture()
        epoch = self.engine.capture_epoch
        self.engine.begin_capture()
        self.assertEqual(epoch, self.engine.capture_epoch)
        self.engine.end_capture()
        self.assertFalse(self.engine.capture_active.is_set())

    def test_completed_progress_is_not_played_after_synthesis(self):
        pipeline = AudioPipeline(self.engine)
        self.engine.audio = pipeline
        turn = self.start()
        self.speech()
        self.engine.say("Running tests", turn_id=turn, progress=True)
        entered = threading.Event()
        def synthesize(*_):
            with self.engine.lock:
                self.engine._finish_turn({"id": turn, "status": "completed"})
                self.engine.speech.clear()
            entered.set()
        pipeline._espeak = synthesize
        with patch("jki.audio.subprocess.Popen") as launch:
            self.engine._spawn(pipeline.speech_loop, "speech-progress-test")
            self.assertTrue(entered.wait(1))
            wait_for(lambda: not self.engine.speaking.is_set())
            self.engine.close()
        launch.assert_not_called()
