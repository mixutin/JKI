import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from jki.models import HTTPSRedirects, install_manifest, relative_path, unpack_zip


class Response(io.BytesIO):
    def geturl(self):
        return "https://models.invalid/fixture"


class Opener:
    def __init__(self, data):
        self.data = data

    def open(self, request, timeout=30):
        return Response(self.data)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = b"fixture model data"
        self.manifest = {"schema_version": 1, "id": "fixture", "files": [{
            "path": "model.bin", "url": "https://models.invalid/model.bin", "size": len(self.data),
            "sha256": hashlib.sha256(self.data).hexdigest()}]}

    def install(self):
        path = self.root / "manifest.json"
        path.write_text(json.dumps(self.manifest))
        return install_manifest(path, self.root / "models", opener=Opener(self.data))

    def test_verified_download_installed_atomically(self):
        result = self.install()
        self.assertEqual((result / "model.bin").read_bytes(), self.data)
        self.assertEqual(list((self.root / "models").glob(".model-*")), [])

    def test_checksum_failure_installs_nothing(self):
        self.manifest["files"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(list((self.root / "models").iterdir()), [])

    def test_size_failure_installs_nothing(self):
        self.manifest["files"][0]["size"] = 1
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(list((self.root / "models").iterdir()), [])

    def test_existing_model_is_not_overwritten(self):
        path = self.install()
        with self.assertRaises(FileExistsError):
            self.install()
        self.assertEqual((path / "model.bin").read_bytes(), self.data)

    def test_http_url_rejected(self):
        self.manifest["files"][0]["url"] = "http://models.invalid/file"
        with self.assertRaises(ValueError):
            self.install()

    def test_http_redirect_rejected(self):
        with self.assertRaises(ValueError):
            HTTPSRedirects().redirect_request(None, None, 302, "", {}, "http://models.invalid/file")

    def test_unsafe_paths_rejected(self):
        for name in ("../outside", "/absolute", "folder/../../outside", "bad\\name", "."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                relative_path(name)

    def test_zip_traversal_is_rejected(self):
        archive = self.root / "archive.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("../outside", "fixture")
        with self.assertRaises(ValueError):
            unpack_zip(archive, self.root / "extract")
        self.assertFalse((self.root / "outside").exists())

    def test_zip_symlinks_are_rejected(self):
        archive = self.root / "archive.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            info = zipfile.ZipInfo("link")
            info.external_attr = 0o120777 << 16
            stream.writestr(info, "target")
        with self.assertRaises(ValueError):
            unpack_zip(archive, self.root / "extract")

    def test_expanded_archive_limit(self):
        archive = self.root / "archive.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("file", "12345")
        with self.assertRaises(ValueError):
            unpack_zip(archive, self.root / "extract", byte_limit=4)

    def test_future_manifest_schema_rejected(self):
        self.manifest["schema_version"] = 2
        with self.assertRaises(ValueError):
            self.install()

    def test_malformed_manifest_types_are_actionable(self):
        for value in ([], {"schema_version": True, "id": "model"},
                      {"schema_version": 1, "id": 42},
                      {"schema_version": 1, "id": "model", "files": [None]},
                      {"schema_version": 1, "id": "model", "files": [{"path": "file"}]}):
            self.manifest = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.install()
