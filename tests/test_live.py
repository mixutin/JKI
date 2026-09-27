"""Read-only live check; explicit opt-in and a local config are both required."""
import os
from pathlib import Path
import unittest

from jki.config import ConfigStore
from jki.diagnostics import doctor


@unittest.skipUnless(os.environ.get("JKI_LIVE_TESTS") == "1" and os.environ.get("JKI_TEST_CONFIG"),
                     "Requires explicit JKI_LIVE_TESTS=1 and JKI_TEST_CONFIG; never starts a task")
class LiveTests(unittest.TestCase):
    def test_live_backend_read_only(self):
        settings = ConfigStore(Path(os.environ["JKI_TEST_CONFIG"])).load()
        report = doctor(settings, live=True)
        self.assertTrue(any(c["name"] == "live backend" and c["status"] == "ok" for c in report["checks"]))
