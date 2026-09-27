from dataclasses import replace
from pathlib import Path
import threading
import unittest

from jki.state import Captured
from tests.helpers import EngineFixture, wait_for


class EngineTests(EngineFixture, unittest.TestCase):
    def test_spoken_acknowledgment_only_after_acceptance(self):
        self.assertEqual(self.speech(), [])
        turn = self.start()
        self.assertEqual(self.speech(), ["I'm doing it now."])
        self.event("turn/started", turn={"id": turn})
        self.assertEqual(self.speech(), [])

    def test_start_passes_explicit_permissions(self):
        self.start()
        method, params = self.client.calls[0]
        self.assertEqual(method, "turn/start")
        self.assertEqual(params["sandboxPolicy"]["type"], "readOnly")
        self.assertEqual(params["approvalPolicy"], "on-request")
        self.assertEqual(params["cwd"], self.temp.name)
        self.assertIn("clientUserMessageId", params)

    def test_steer_uses_expected_turn_id(self):
        turn = self.start()
        self.engine._execute(self.command("Focus on the tests instead"))
        self.assertEqual(self.client.calls[-1][0], "turn/steer")
        self.assertEqual(self.client.calls[-1][1]["expectedTurnId"], turn)
        self.assertNotIn("sandboxPolicy", self.client.calls[-1][1])

    def test_external_turn_is_not_silently_steered(self):
        self.event("turn/started", turn={"id": "external"})
        with self.assertRaisesRegex(RuntimeError, "another client"):
            self.engine._execute(self.command())
        self.assertEqual(self.client.calls, [])

    def test_progress_is_observed_and_throttled(self):
        turn = self.start()
        self.speech()
        self.event("turn/plan/updated", turnId=turn, plan=[{"step": "Inspect files", "status": "inProgress"}])
        self.assertIn("Inspect files", self.engine.snapshot()["progress"])
        self.assertEqual(self.speech(), [])
        self.clock.advance(21)
        self.event("turn/plan/updated", turnId=turn, plan=[{"step": "Run tests", "status": "inProgress"}])
        self.assertEqual(self.speech(), ["Step 1 of 1: Run tests"])
        self.clock.advance(21)
        self.event("turn/plan/updated", turnId=turn, plan=[{"step": "Run tests", "status": "inProgress"}])
        self.assertEqual(self.speech(), [])

    def test_progress_can_be_disabled(self):
        self.engine.settings = replace(self.settings, spoken_progress=False)
        turn = self.start()
        self.speech()
        self.clock.advance(30)
        self.event("item/started", turnId=turn, item={"id": "tool", "type": "webSearch"})
        self.assertEqual(self.speech(), [])
        self.assertEqual(self.engine.snapshot()["progress"], "Searching the web.")

    def test_reasoning_is_never_spoken(self):
        turn = self.start()
        self.speech()
        self.clock.advance(30)
        self.event("item/completed", turnId=turn, item={"id": "r", "type": "reasoning", "text": "hidden"})
        self.assertEqual(self.speech(), [])

    def test_final_answer_waits_for_terminal_and_is_deduplicated(self):
        turn = self.start()
        self.speech()
        item = {"id": "answer", "type": "agentMessage", "phase": "final_answer", "text": "Done."}
        self.event("item/completed", turnId=turn, item=item)
        self.assertEqual(self.speech(), [])
        self.event("turn/completed", turn={"id": turn, "status": "completed"})
        self.event("turn/completed", turn={"id": turn, "status": "completed"})
        self.assertEqual(self.speech(), ["Done."])
        self.assertIsNone(self.engine.health.active_turn)

    def test_fast_completion_before_rpc_response(self):
        def notify(method, params):
            self.event("item/completed", turnId="turn-1", item={"id": "fast", "type": "agentMessage", "text": "Already done."})
            self.event("turn/completed", turn={"id": "turn-1", "status": "completed"})
        self.client.after_send = notify
        self.start()
        self.assertEqual(self.speech(), ["Already done."])
        self.assertIsNone(self.engine.health.active_turn)

    def test_failed_turn_is_not_reported_as_success(self):
        turn = self.start()
        self.speech()
        self.event("turn/completed", turn={"id": turn, "status": "failed", "error": {"message": "Tool failed"}})
        self.assertEqual(self.engine.snapshot()["last_result"], "failed")
        self.assertIn("failed", self.speech()[0])
        self.assertEqual(self.engine.snapshot()["status"], "attention")

    def test_other_thread_is_ignored(self):
        self.engine._event({"method": "item/completed", "params": {"threadId": "other", "turnId": "x",
                          "item": {"type": "agentMessage", "text": "unrelated"}}})
        self.assertEqual(self.speech(), [])
        self.assertEqual(len(self.engine.turn_records), 0)

    def test_stale_connection_events_are_ignored(self):
        self.engine.connection_generation = 5
        self.engine._event({"method": "jake/disconnected"}, 4)
        self.assertTrue(self.engine.health.connected)

    def test_mute_invalidates_audio_even_after_unmute(self):
        captured = Captured(b"audio", self.engine.capture_epoch, self.clock())
        self.engine.toggle_mute()
        self.engine.toggle_mute()
        self.assertFalse(self.engine.transcription_ready("old request", captured))
        self.assertFalse(self.engine.accept_audio(captured))

    def test_queued_voice_command_cannot_survive_mute(self):
        command = self.command(voice=True)
        self.engine.toggle_mute()
        self.engine.toggle_mute()
        self.engine._execute(command)
        self.assertEqual(self.client.calls, [])

    def test_expired_command_is_discarded(self):
        command = self.command()
        self.clock.advance(31)
        self.engine._execute(command)
        self.assertEqual(self.client.calls, [])

    def test_typing_works_while_microphone_is_muted(self):
        self.engine.toggle_mute()
        self.engine._execute(self.command())
        self.assertEqual(self.client.calls[0][0], "turn/start")

    def test_preview_is_editable_and_requires_matching_token(self):
        captured = Captured(b"audio", self.engine.capture_epoch, self.clock())
        self.engine.transcription_ready("raw words", captured)
        token = self.engine.preview_token
        self.assertFalse(self.engine.confirm_preview("edit", "stale"))
        self.clock.advance(100)
        self.assertTrue(self.engine.confirm_preview("edited words", token))
        self.assertEqual(self.engine.commands.get_nowait().value, "edited words")

    def test_mute_discards_preview(self):
        captured = Captured(b"audio", self.engine.capture_epoch, self.clock())
        self.engine.transcription_ready("words", captured)
        token = self.engine.preview_token
        self.engine.toggle_mute()
        self.assertFalse(self.engine.confirm_preview("words", token))
        self.assertEqual(self.engine.snapshot()["preview"], "")

    def test_queue_limits_are_enforced(self):
        self.assertEqual(sum(self.engine.submit(f"Request {i}") for i in range(100)), 8)
        self.assertEqual(self.engine.commands.qsize(), 8)
        captured = Captured(b"audio", self.engine.capture_epoch, self.clock())
        self.assertTrue(self.engine.accept_audio(captured))
        self.assertTrue(self.engine.accept_audio(captured))
        self.assertFalse(self.engine.accept_audio(captured))

    def test_microphone_failure_survives_healthy_connection(self):
        self.engine.component("microphone", "error")
        self.assertEqual(self.engine.snapshot()["status"], "error")
        self.engine.health.connected = True
        self.assertEqual(self.engine.snapshot()["status"], "error")

    def test_timeout_is_uncertain_and_never_retried(self):
        self.client.failure = TimeoutError()
        with self.assertRaises(TimeoutError):
            self.start()
        self.assertTrue(self.engine.health.uncertain)
        with self.assertRaises(RuntimeError):
            self.engine._execute(self.command("Try again"))
        self.assertEqual(len(self.client.calls), 1)
        self.assertNotIn("I'm doing it now.", self.speech())

    def test_cancel_before_send_discards_without_unknown_outcome(self):
        self.client.before_send = self.engine.cancel_task
        self.start()
        self.assertFalse(self.engine.health.uncertain)
        self.assertEqual(self.client.calls, [])
        self.assertFalse(self.engine.health.cancelling)

    def test_cancel_is_pending_until_backend_confirms(self):
        turn = self.start()
        self.speech()
        self.engine._spawn(self.engine._control_loop, "test-controls")
        self.engine.cancel_task()
        wait_for(lambda: any(m == "turn/interrupt" for m, _ in self.client.calls))
        self.assertTrue(self.engine.health.cancelling)
        self.assertEqual(self.speech(), [])
        self.event("turn/completed", turn={"id": turn, "status": "interrupted"})
        self.assertFalse(self.engine.health.cancelling)
        self.assertIn("Earlier changes were not undone", self.speech()[0])

    def test_cancel_during_submission_interrupts_after_ack(self):
        entered, release = threading.Event(), threading.Event()
        def block(method, params):
            if method == "turn/start":
                entered.set()
                release.wait(2)
        self.client.after_send = block
        thread = threading.Thread(target=self.start)
        thread.start()
        self.assertTrue(entered.wait(1))
        self.engine._spawn(self.engine._control_loop, "test-controls")
        self.engine.cancel_task()
        release.set()
        thread.join(2)
        wait_for(lambda: any(m == "turn/interrupt" for m, _ in self.client.calls))
        self.assertTrue(self.engine.health.cancelling)

    def test_stop_speaking_cancels_output_not_task(self):
        turn = self.start()
        old_epoch = self.engine.speech_epoch
        self.engine.stop_speaking()
        self.assertGreater(self.engine.speech_epoch, old_epoch)
        self.assertTrue(self.engine.output_cancel.is_set())
        self.assertEqual(self.engine.health.active_turn, turn)
        self.assertEqual(self.speech(), [])

    def test_custom_config_model_change_stays_on_custom_path(self):
        default = Path(self.temp.name) / "default.json"
        default.write_text("unchanged")
        self.engine.models = ["catalog-model"]
        self.engine._switch_model("catalog-model")
        self.assertEqual(self.engine.store.load().model, "catalog-model")
        self.assertEqual(default.read_text(), "unchanged")
        self.assertEqual(self.client.calls, [])

    def test_model_selection_during_task_applies_only_to_next_turn(self):
        active = self.start()
        self.engine.models = ["new"]
        self.engine._switch_model("new")
        self.assertEqual(self.engine.health.active_turn, active)
        self.assertEqual(len(self.client.calls), 1)
        self.engine._execute(self.command("Additional context"))
        self.assertEqual(self.client.calls[-1][0], "turn/steer")
        self.assertNotIn("model", self.client.calls[-1][1])
        self.event("turn/completed", turn={"id": active, "status": "completed"})
        self.start()
        self.assertEqual(self.client.calls[-1][1]["model"], "new")

    def test_resume_policy_mismatch_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.engine._verify_resume({"sandbox": {"type": "dangerFullAccess"}, "approvalPolicy": "on-request", "cwd": self.temp.name})

    def test_resume_rejects_unknown_approval_policy(self):
        with self.assertRaises(RuntimeError):
            self.engine._verify_resume({"sandbox": {"type": "readOnly"}, "approvalPolicy": "never", "cwd": self.temp.name})

    def test_reconnect_reconciles_without_replaying_command(self):
        turn = self.start()
        self.speech()
        self.event("jake/disconnected")
        with self.engine.lock:
            self.engine._reconcile({"turns": [{"id": turn, "status": "completed"}]})
        self.assertFalse(self.engine.health.uncertain)
        self.assertEqual(len(self.client.calls), 1)
        self.assertIn("finished", self.speech()[0])

    def test_duplicate_history_is_bounded(self):
        for n in range(2000):
            self.engine._answer({"id": str(n), "text": "Result"})
        self.assertEqual(len(self.engine.seen_items), 512)
        self.assertEqual(self.engine.speech.qsize(), 8)
