from dataclasses import replace
import threading
import unittest

from jki.config import Settings
from tests.helpers import EngineFixture, FakeClient


CATALOG = [
    {"model": "gpt-6-sol", "defaultReasoningEffort": "medium", "supportedReasoningEfforts": [
        {"reasoningEffort": level} for level in ("low", "medium", "high", "xhigh", "max")
    ]},
    {"model": "other-model", "defaultReasoningEffort": "low", "supportedReasoningEfforts": [
        {"reasoningEffort": "low"}
    ]},
    {"model": "no-reasoning", "supportedReasoningEfforts": []},
]


class ReasoningTests(EngineFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.engine.model_catalog = CATALOG
        self.engine.models = [item["model"] for item in CATALOG]
        self.engine._switch_model("gpt-6-sol")
        self.speech()

    def test_combined_selection_persists_and_is_sent_with_new_turn(self):
        self.engine._execute(self.command("use Sol with high reasoning"))
        saved = self.engine.store.load()
        self.assertEqual((saved.model, saved.effort), ("gpt-6-sol", "high"))
        self.start()
        params = self.client.calls[-1][1]
        self.assertEqual((params["model"], params["effort"]), ("gpt-6-sol", "high"))

    def test_invalid_combined_selection_does_not_partially_change_settings(self):
        old = self.engine.store.load()
        with self.assertRaises(ValueError):
            self.engine._execute(self.command("use other-model with max reasoning"))
        self.assertEqual(self.engine.store.load(), old)
        self.assertEqual(self.engine.model, old.model)

    def test_model_switch_selects_a_supported_default(self):
        self.engine._switch_effort("max")
        self.engine._switch_model("other-model")
        self.assertEqual(self.engine.store.load().effort, "low")
        self.start()
        self.assertEqual(self.client.calls[-1][1]["effort"], "low")

    def test_model_without_reasoning_omits_effort(self):
        self.engine._switch_model("no-reasoning")
        self.start()
        self.assertNotIn("effort", self.client.calls[-1][1])
        self.assertEqual(self.engine.snapshot()["efforts"], [])

    def test_effort_change_during_work_only_affects_next_turn(self):
        active = self.start()
        self.engine._switch_effort("high")
        self.assertEqual(self.engine.health.active_turn, active)
        self.assertEqual(len(self.client.calls), 1)
        self.engine._execute(self.command("Use the examples too"))
        self.assertEqual(self.client.calls[-1][0], "turn/steer")
        self.assertNotIn("effort", self.client.calls[-1][1])
        self.event("turn/completed", turn={"id": active, "status": "completed"})
        self.start()
        self.assertEqual(self.client.calls[-1][1]["effort"], "high")

    def test_resume_response_does_not_replace_saved_selection(self):
        self.engine.settings = replace(self.engine.settings, model="gpt-6-sol", effort="high")
        engine = self.engine

        class ResumeClient(FakeClient):
            def call(self, method, params, **kwargs):
                self.calls.append((method, params))
                if method == "model/list":
                    if not params.get("cursor"):
                        return {"data": CATALOG[:1], "nextCursor": "next"}
                    return {"data": CATALOG[1:]}
                engine.stopping.set()
                return {"model": "old-thread-model", "sandbox": {"type": "readOnly"},
                        "approvalPolicy": "on-request", "cwd": engine.settings.workspace,
                        "thread": {"turns": []}}

        resumed = ResumeClient()
        engine.client_factory = lambda *_: resumed
        engine._connect_loop()
        self.assertEqual(engine.model, "gpt-6-sol")
        self.assertEqual(engine.effort, "high")
        self.assertEqual(resumed.calls[-1][1]["model"], "gpt-6-sol")
        self.assertNotIn("effort", resumed.calls[-1][1])
        self.assertEqual(engine.models, [item["model"] for item in CATALOG])
        engine.stopping = threading.Event()

    def test_upstream_legacy_effort_config_is_migrated(self):
        settings = Settings.from_dict({"model": "gpt-6-sol", "effort": "max", "full_access": False})
        self.assertEqual(settings.effort, "max")
        self.assertEqual(settings.schema_version, 2)

    def test_future_catalog_effort_is_not_hardcoded(self):
        self.engine.model_catalog = [{"model": "future", "supportedReasoningEfforts": [
            {"reasoningEffort": "future-level"}]}]
        self.engine.models = ["future"]
        self.engine._switch_model("future")
        self.assertEqual(self.engine.store.load().effort, "future-level")
