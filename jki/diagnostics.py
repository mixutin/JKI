"""Explicit, read-only diagnostics. No recording, model download, or task submission."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
from typing import Any

from . import __version__
from .config import Settings
from .protocol import CodexClient


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def devices() -> list[dict[str, str]]:
    result = subprocess.run(["pw-dump"], capture_output=True, timeout=5, check=True)
    if len(result.stdout) > 4 * 1024 * 1024:
        raise RuntimeError("PipeWire device report exceeds the diagnostic limit")
    values = []
    for item in json.loads(result.stdout):
        props = item.get("info", {}).get("props", {})
        kind = props.get("media.class")
        if kind in {"Audio/Source", "Audio/Sink"} and props.get("node.name"):
            values.append({"name": props["node.name"], "description": props.get("node.description", props["node.name"]),
                           "kind": "input" if kind == "Audio/Source" else "output"})
    return values


def doctor(settings: Settings, *, live: bool = False, client_factory: Any = CodexClient) -> dict[str, Any]:
    checks: list[Check] = []
    for binary in ("pw-record", "pw-play", "espeak-ng"):
        checks.append(Check(binary, "ok" if shutil.which(binary) else "error",
                            "Installed" if shutil.which(binary) else "Install the system package providing this executable"))
    if settings.media_enabled:
        for binary in ("mpv", "yt-dlp", "playerctl", "wpctl"):
            checks.append(Check(binary, "ok" if shutil.which(binary) else "warning", "Optional local media integration"))
    for module in ("gi", "cairo", "websockets", "faster_whisper", "numpy", "onnxruntime"):
        checks.append(Check(module, "ok" if importlib.util.find_spec(module) else "error",
                            "Import available" if importlib.util.find_spec(module) else "Install the documented dependency"))
    if settings.input_mode == "wake-word":
        checks.append(Check("vosk", "ok" if importlib.util.find_spec("vosk") else "error", "Wake-word engine"))
        checks.append(Check("wake model", "ok" if Path(settings.model_path).is_dir() else "error",
                            "Local Vosk directory required; use jki models to install a verified manifest"))
    transcription = Path(settings.transcription_model_path)
    checks.append(Check("transcription model", "ok" if transcription.is_dir() else "warning",
                        "Local directory found" if transcription.is_dir() else
                        "Model name/cache not verified. Runtime is offline-only; install a local model before speaking"))
    if settings.tts_engine == "piper":
        ready = Path(settings.tts_model_path).is_file() and Path(settings.tts_model_path + ".json").is_file()
        checks.append(Check("Piper voice", "ok" if ready and importlib.util.find_spec("piper") else "warning",
                            "Piper requires its ONNX model and adjacent .onnx.json configuration; eSpeak is the fallback"))
    try:
        settings.validate_runtime()
        checks.append(Check("configuration", "ok", "Runtime fields validated"))
    except ValueError as exc:
        checks.append(Check("configuration", "error", str(exc)))
    try:
        info = Path(settings.socket_path).stat()
        valid = stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()
        checks.append(Check("Codex socket", "ok" if valid else "error", "Must be a Unix socket owned by this user"))
        parent = Path(settings.socket_path).parent.stat()
        checks.append(Check("socket directory permissions", "ok" if not parent.st_mode & 0o022 else "warning",
                            "Parent directory should not be writable by other users"))
    except OSError:
        checks.append(Check("Codex socket", "error", "Start Codex and verify the configured socket path"))
    if live:
        client = None
        try:
            client = client_factory(settings.socket_path, lambda event: None)
            client.call("thread/read", {"threadId": settings.thread_id, "includeTurns": False})
            client.call("model/list", {"limit": 1})
            checks.append(Check("live backend", "ok", "Handshake, thread read, and model catalog succeeded; no task was started"))
        except Exception:
            checks.append(Check("live backend", "error", "Read-only compatibility check failed; verify the Codex version and conversation"))
        finally:
            if client:
                client.close()
    return {"jki_version": __version__, "python": platform.python_version(), "platform": platform.system(),
            "checks": [asdict(check) for check in checks], "live": live,
            "ok": all(check.status != "error" for check in checks)}
