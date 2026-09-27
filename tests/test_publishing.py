import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.publish_pr import BASE, verified_files


class PublishingTests(unittest.TestCase):
    def test_verified_bundle_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sample.py').write_text('print("test")\n')
            digest = hashlib.sha256((root / 'sample.py').read_bytes()).hexdigest()
            (root / 'SOURCE-MANIFEST.json').write_text(json.dumps({'upstream_base': BASE, 'files': {'sample.py': digest}}))
            self.assertEqual(verified_files(root), [root / 'sample.py'])
            (root / 'sample.py').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                verified_files(root)

    def test_unsafe_bundle_path_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('../outside', '/absolute', '.git/config'):
                (root / 'SOURCE-MANIFEST.json').write_text(json.dumps({'upstream_base': BASE, 'files': {name: '0' * 64}}))
                with self.subTest(name=name), self.assertRaises(ValueError):
                    verified_files(root)
