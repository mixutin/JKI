from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import stat
import tempfile
import threading
import unittest

from jki.config import ConfigError, ConfigStore, Settings, atomic_json


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "custom.json"

    def test_legacy_false_never_inherits_thread_permissions(self):
        self.assertEqual(Settings.from_dict({"full_access": False}).permission_profile, "restricted")

    def test_legacy_true_requires_new_explicit_confirmation(self):
        self.assertEqual(Settings.from_dict({"full_access": True}).permission_profile, "restricted")

    def test_unknown_future_schema_rejected(self):
        with self.assertRaises(ConfigError):
            Settings.from_dict({"schema_version": 900})

    def test_unknown_field_rejected(self):
        with self.assertRaises(ConfigError):
            Settings.from_dict({"schema_version": 2, "cpu_thread": 4})

    def test_boolean_is_not_an_integer(self):
        with self.assertRaises(ConfigError):
            Settings.from_dict({"cpu_threads": True})

    def test_nan_and_range_are_rejected(self):
        for value in (math.nan, math.inf, 0, 10000):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                Settings.from_dict({"progress_interval": value})

    def test_full_access_needs_confirmation(self):
        with self.assertRaises(ConfigError):
            Settings.from_dict({"schema_version": 2, "permission_profile": "full"})

    def test_profile_policy_is_explicit(self):
        restricted = Settings()
        workspace = replace(restricted, permission_profile="workspace")
        full = replace(restricted, permission_profile="full", full_access_acknowledged=True)
        self.assertEqual(restricted.turn_options()["sandboxPolicy"], {"type": "readOnly"})
        self.assertFalse(workspace.policy()["networkAccess"])
        self.assertTrue(workspace.policy()["excludeSlashTmp"])
        self.assertEqual(full.policy()["type"], "dangerFullAccess")
        for settings in (restricted, workspace, full):
            self.assertEqual(settings.resume_options()["approvalPolicy"], "on-request")
            self.assertIn("sandbox", settings.resume_options())

    def test_invalid_language_model_combination(self):
        with self.assertRaises(ConfigError):
            Settings.from_dict({"language": "fi", "transcription_model_path": "base.en"})
        settings = Settings.from_dict({"language": "fi", "transcription_model_path": "/models/multilingual"})
        self.assertEqual(settings.language, "fi")

    def test_private_atomic_write(self):
        store = ConfigStore(self.path)
        store.save(Settings(thread_id="test"))
        self.assertEqual(store.load().thread_id, "test")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(list(self.path.parent.glob(".custom.json-*")), [])

    def test_fixed_temp_symlink_is_not_used(self):
        sentinel = self.path.parent / "sentinel"
        sentinel.write_text("unchanged")
        self.path.with_suffix(".tmp").symlink_to(sentinel)
        atomic_json(self.path, {"safe": True})
        self.assertEqual(sentinel.read_text(), "unchanged")

    def test_concurrent_writers_leave_valid_complete_json(self):
        threads = [threading.Thread(target=atomic_json, args=(self.path, {"value": n})) for n in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertIn(json.loads(self.path.read_text())["value"], range(10))

    def test_roundtrip_and_custom_path(self):
        settings = Settings(thread_id="custom")
        store = ConfigStore(self.path)
        store.save(settings)
        self.assertEqual(asdict(settings), asdict(store.load()))
        self.assertEqual(store.path, self.path)
