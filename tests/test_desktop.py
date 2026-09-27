from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from jki.config import Settings
from jki.desktop import StatusFile, conversation_command
from jki.diagnostics import devices, doctor
from jki.ui import refresh_interval


class DesktopTests(unittest.TestCase):
    def test_default_status_does_not_persist_transcripts_or_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            store = StatusFile(path)
            state = {"status": "listening", "connected": True, "model": "catalog", "permission_profile": "restricted",
                     "heard": "private command", "progress": "private progress", "detail": "private error"}
            store.update(state)
            written = json.loads(path.read_text())
            self.assertNotIn("heard", written)
            self.assertNotIn("progress", written)
            self.assertNotIn("detail", written)
            store.update(state, persist_transcript=True)
            self.assertEqual(json.loads(path.read_text())["heard"], "private command")
            store.update(state)
            self.assertNotIn("heard", json.loads(path.read_text()))
            store.close()
            self.assertFalse(path.exists())

    def test_unchanged_status_does_not_rewrite_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StatusFile(Path(directory) / "status.json")
            value = {"status": "muted", "connected": True, "model": "x", "permission_profile": "restricted"}
            with patch("jki.desktop.atomic_json") as write:
                store.update(value)
                store.update(value)
                self.assertEqual(write.call_count, 1)

    def test_terminal_fallback_preserves_argv(self):
        available = {"codex": "/usr/bin/codex", "gnome-terminal": "/usr/bin/gnome-terminal"}
        command = conversation_command(Settings(thread_id="id with spaces"), available.get)
        self.assertEqual(command, ["/usr/bin/gnome-terminal", "--", "/usr/bin/codex", "resume", "id with spaces"])

    def test_missing_terminal_has_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, "terminal"):
            conversation_command(Settings(), lambda name: "/usr/bin/codex" if name == "codex" else None)

    def test_custom_terminal_is_used(self):
        command = conversation_command(replace(Settings(), terminal="custom"), lambda name: "/bin/" + name)
        self.assertEqual(command[:2], ["/bin/custom", "-e"])

    def test_animation_is_throttled_or_disabled(self):
        self.assertEqual(refresh_interval({"status": "working"}, True, False), 50)
        self.assertEqual(refresh_interval({"status": "working"}, True, True), 250)
        self.assertEqual(refresh_interval({"status": "muted"}, True, False), 250)
        self.assertEqual(refresh_interval({"status": "speaking"}, False, False), 1000)

    def test_doctor_does_not_connect_by_default(self):
        factory = Mock(side_effect=AssertionError("Must not connect"))
        doctor(Settings(), client_factory=factory)
        factory.assert_not_called()

    def test_live_doctor_only_uses_read_operations(self):
        client = Mock()
        result = doctor(Settings(thread_id="test"), live=True, client_factory=lambda *_: client)
        self.assertEqual([call.args[0] for call in client.call.call_args_list], ["thread/read", "model/list"])
        client.close.assert_called_once()
        self.assertTrue(result["live"])

    def test_device_discovery_uses_stable_names(self):
        output = [{"info": {"props": {"media.class": "Audio/Source", "node.name": "mic", "node.description": "USB microphone"}}},
                  {"info": {"props": {"media.class": "Audio/Sink", "node.name": "speaker"}}}]
        with patch("jki.diagnostics.subprocess.run", return_value=Mock(stdout=json.dumps(output).encode())):
            self.assertEqual([item["name"] for item in devices()], ["mic", "speaker"])

    def test_launcher_rejects_expansion_sensitive_paths(self):
        from jki.desktop import _quote
        for value in ["path\nline", "$(anything)", "`anything`", "nul\x00"]:
            with self.assertRaises(ValueError):
                _quote(value)
        self.assertEqual(_quote("a b%"), '\"a b%%\"')
