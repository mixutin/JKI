"""Interactive fixture replay: no audio capture, model loads, or backend connection."""
from .engine import Engine


class DemoEngine(Engine):
    def resolve_approval(self, identifier, decision):
        with self.lock:
            approval = self.health.approvals.get(identifier)
            if not approval or decision not in approval["decisions"]:
                return False
            self.health.approvals.pop(identifier)
            self._record("demo-turn")["answer"] = {"id": "demo-answer", "text": "Demo complete. No real action was performed."}
            self._finish_turn({"id": "demo-turn", "status": "completed" if decision == "accept" else "interrupted"})
            return True

    def cancel_task(self):
        super().cancel_task()
        with self.lock:
            if self.health.active_turn:
                self._finish_turn({"id": self.health.active_turn, "status": "interrupted"})


def start_demo(engine, glib):
    engine.component("microphone", "idle")
    engine.component("transcription", "idle")
    engine.component("tts", "demo; no sound")
    engine.health.connected = True
    engine.effective_policy = "DEMO ONLY — nothing is executed"
    engine.models = ["demo-model"]
    engine.model = "demo-model"

    def begin():
        with engine.lock:
            engine._accepted("demo-turn")
        return False

    def progress():
        engine._event({"method": "turn/plan/updated", "params": {"threadId": "demo", "turnId": "demo-turn",
                       "plan": [{"step": "Read the sample", "status": "completed"},
                                {"step": "Prepare a demo change", "status": "inProgress"}]}})
        return False

    def approval():
        if engine.health.active_turn != "demo-turn":
            return False
        engine._event({"method": "item/started", "params": {"threadId": "demo", "turnId": "demo-turn", "item": {
            "id": "demo-file", "type": "fileChange", "changes": [{"path": "EXAMPLE.txt", "kind": {"type": "add"},
                                                                       "diff": "+This is only a preview."}]}}})
        engine._event({"id": "demo-approval", "method": "item/fileChange/requestApproval", "params": {
            "threadId": "demo", "turnId": "demo-turn", "itemId": "demo-file", "reason": "Demonstrate approval controls"}})
        return False
    glib.timeout_add(1000, begin)
    glib.timeout_add(3000, progress)
    glib.timeout_add(5000, approval)
