"""Explicit HTTPS model installation from a hash-pinned, user-selected manifest."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import build_opener, HTTPRedirectHandler, Request
import zipfile

MAX_BYTES = 3 * 1024**3


class HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https":
            raise ValueError("Model downloads cannot redirect to an insecure URL")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def relative_path(value: str) -> Path:
    if not isinstance(value, str):
        raise ValueError("A model path must be a string")
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Manifest/archive contains an unsafe relative path")
    return Path(*path.parts)


def unpack_zip(archive: Path, destination: Path, *, byte_limit: int = MAX_BYTES) -> None:
    total = 0
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as source:
        if len(source.infolist()) > 10000:
            raise ValueError("Archive contains too many entries")
        for entry in source.infolist():
            relative = relative_path(entry.filename)
            if str(relative) in seen:
                raise ValueError("Duplicate archive path")
            seen.add(str(relative))
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Symbolic links are not allowed in model archives")
            total += entry.file_size
            if total > byte_limit:
                raise ValueError("Expanded model exceeds the size limit")
            target = destination / relative
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with source.open(entry) as stream, target.open("xb") as output:
                shutil.copyfileobj(stream, output, 1024 * 1024)
            target.chmod(0o600)


def install_manifest(manifest_path: Path, destination: Path, *,
                     progress: Callable[[str, int, int], None] = lambda *_: None,
                     opener: Any = None) -> Path:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("id"), str):
        raise ValueError("Model manifest must be an object with a string ID")
    if type(manifest.get("schema_version")) is not int or manifest.get("schema_version") != 1 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", manifest.get("id", "")):
        raise ValueError("Invalid model manifest ID or schema")
    files = manifest.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 100:
        raise ValueError("A manifest must contain 1–100 files")
    total = 0
    targets: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) for key in ("path", "url", "sha256")):
            raise ValueError("Each model file needs string path, url, and sha256 fields")
        relative = relative_path(item["path"])
        if str(relative) in targets:
            raise ValueError("Duplicate manifest file")
        targets.add(str(relative))
        url = urlparse(item["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Model URLs must use HTTPS without embedded credentials")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", item.get("sha256", "")):
            raise ValueError("Each model file needs a published SHA-256 checksum")
        if type(item.get("size")) is not int or not 0 < item["size"] <= MAX_BYTES:
            raise ValueError("Each model file needs an exact bounded byte size")
        if item.get("archive") not in (None, "zip"):
            raise ValueError("Only ZIP archive extraction is supported")
        total += item["size"]
    for index, item in enumerate(files):
        if item.get("archive"):
            root = relative_path(item["path"])
            if any(relative_path(other["path"]).is_relative_to(root) for n, other in enumerate(files) if n != index):
                raise ValueError("Overlapping archive and file destinations")
    if total > MAX_BYTES:
        raise ValueError("Model download exceeds the total size limit")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    final = destination / manifest["id"]
    if final.exists():
        raise FileExistsError("Model destination already exists; it will not be overwritten")
    opener = opener or build_opener(HTTPSRedirects())
    with tempfile.TemporaryDirectory(prefix=".model-", dir=destination) as stage_name:
        stage = Path(stage_name)
        payload = stage / "payload"
        payload.mkdir(mode=0o700)
        expanded_remaining = MAX_BYTES
        for index, item in enumerate(files):
            download = stage / f"download-{index}"
            digest, size = hashlib.sha256(), 0
            request = Request(item["url"], headers={"User-Agent": "JKI/0.2.0"})
            with opener.open(request, timeout=30) as response, download.open("xb") as stream:
                if urlparse(response.geturl()).scheme != "https":
                    raise ValueError("Insecure model response")
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > item["size"]:
                        raise ValueError("Download exceeds the declared file size")
                    digest.update(chunk)
                    stream.write(chunk)
                    progress(item["path"], size, item["size"])
                stream.flush()
                os.fsync(stream.fileno())
            if size != item["size"] or digest.hexdigest() != item["sha256"].lower():
                raise ValueError("Model checksum or size mismatch; nothing was installed")
            target = payload / relative_path(item["path"])
            if item.get("archive") == "zip":
                target.mkdir(parents=True, exist_ok=False, mode=0o700)
                with zipfile.ZipFile(download) as archive:
                    expanded = sum(entry.file_size for entry in archive.infolist())
                unpack_zip(download, target, byte_limit=expanded_remaining)
                expanded_remaining -= expanded
            else:
                expanded_remaining -= item["size"]
                if expanded_remaining < 0:
                    raise ValueError("Installed model exceeds the total size limit")
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                download.chmod(0o600)
                download.rename(target)
        # Rename a complete verified directory, never a partially downloaded model.
        payload.rename(final)
    return final
