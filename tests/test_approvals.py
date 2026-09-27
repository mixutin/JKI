import unittest
from tests.helpers import EngineFixture, wait_for


class ApprovalTests(EngineFixture, unittest.TestCase):
    def make_approval(self, *, command="printf example", decisions=None, identifier=77, turn=None):
        turn = turn or self.engine.health.active_turn or self.start()
        self.speech()
        params = {"threadId": "test", "turnId": turn, "itemId": "command-item"}
        if command is not None:
            params["command"] = command
            params["cwd"] = self.temp.name
        if decisions is not None:
            params["availableDecisions"] = decisions
        self.engine._event({"id": identifier, "method": "item/commandExecution/requestApproval", "params": params})
        return identifier

    def test_approval_status_survives_speech_completion(self):
        self.make_approval()
        self.engine.speaking.set()
        self.engine.speaking.clear()
        self.assertEqual(self.engine.snapshot()["status"], "attention")
        self.assertEqual(self.engine.snapshot()["detail"], "Waiting for on-screen approval")

    def test_decision_is_sent_once_and_waits_for_resolution(self):
        identifier = self.make_approval()
        self.engine._spawn(self.engine._control_loop, "test-controls")
        self.assertTrue(self.engine.resolve_approval(identifier, "accept"))
        self.assertFalse(self.engine.resolve_approval(identifier, "accept"))
        wait_for(lambda: bool(self.client.responses))
        self.assertEqual(self.client.responses, [(identifier, {"decision": "accept"})])
        self.assertIn(identifier, self.engine.health.approvals)
        self.event("serverRequest/resolved", requestId=identifier)
        self.assertNotIn(identifier, self.engine.health.approvals)

    def test_missing_details_cannot_be_accepted(self):
        identifier = self.make_approval(command=None)
        self.assertFalse(self.engine.resolve_approval(identifier, "accept"))
        self.assertTrue(self.engine.resolve_approval(identifier, "decline"))

    def test_server_offered_decisions_are_respected(self):
        identifier = self.make_approval(decisions=["decline", "cancel"])
        self.assertFalse(self.engine.resolve_approval(identifier, "accept"))
        self.assertTrue(self.engine.resolve_approval(identifier, "decline"))

    def test_voice_cannot_grant_approval(self):
        identifier = self.make_approval()
        with self.assertRaises(RuntimeError):
            self.engine._execute(self.command("approve", voice=True))
        self.assertFalse(self.engine.health.approvals[identifier]["answered"])

    def test_stale_turn_approval_is_rejected(self):
        self.start()
        self.make_approval(turn="not-the-active-turn")
        self.assertFalse(self.engine.health.approvals)

    def test_disconnection_invalidates_old_approval_buttons(self):
        identifier = self.make_approval()
        self.event("jake/disconnected")
        self.assertFalse(self.engine.resolve_approval(identifier, "accept"))

    def test_approval_keeps_progress_silent(self):
        self.make_approval()
        self.speech()
        self.clock.advance(30)
        self.event("item/started", turnId=self.engine.health.active_turn, item={"id": "web", "type": "webSearch"})
        self.assertEqual(self.speech(), [])

    def test_file_changes_need_full_preview(self):
        turn = self.start()
        self.event("item/started", turnId=turn, item={"id": "file", "type": "fileChange", "changes": [
            {"path": "sample", "diff": "+example", "kind": {"type": "add"}}]})
        self.engine._event({"id": 88, "method": "item/fileChange/requestApproval", "params": {
            "threadId": "test", "turnId": turn, "itemId": "file"}})
        self.assertTrue(self.engine.health.approvals[88]["can_accept"])

    def test_unsupported_request_has_a_control_response(self):
        turn = self.start()
        self.engine._event({"id": 99, "method": "unknown/request", "params": {"threadId": "test", "turnId": turn}})
        self.engine._spawn(self.engine._control_loop, "test-controls")
        wait_for(lambda: bool(self.client.responses))
        self.assertEqual(self.client.responses, [(99, "unsupported")])
