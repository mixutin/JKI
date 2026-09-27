"""Versioned configuration, explicit permissions, and private atomic storage."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any


def xdg_path(variable: str, fallback: str) -> Path:
    value = Path(os.environ.get(variable, fallback)).expanduser()
    return value if value.is_absolute() else Path(fallback).expanduser()


CONFIG = xdg_path("XDG_CONFIG_HOME", "~/.config") / "jake-voice/config.json"
STATE = xdg_path("XDG_STATE_HOME", "~/.local/state") / "jake-voice"
DATA = xdg_path("XDG_DATA_HOME", "~/.local/share") / "jake-voice"


class ConfigError(ValueError):
    """An actionable configuration error, safe to show without a traceback."""


def atomic_json(path: Path, data: Any) -> None:
    """Create privately, fsync, and atomically replace; never follow a temp symlink."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class Settings:
    schema_version: int = 2
    wake_word: str = "jake"
    thread_id: str = ""
    model: str = ""
    effort: str = "medium"
    model_path: str = str(DATA / "vosk-model-small-en-us-0.15")
    transcription_model_path: str = "base.en"
    socket_path: str = str(Path.home() / ".codex/app-server-control/app-server-control.sock")
    codex_path: str = "codex"
    tts_engine: str = "espeak"
    tts_model_path: str = ""
    voice: str = "en-us+m3"
    permission_profile: str = "restricted"
    full_access_acknowledged: bool = False
    workspace: str = str(Path.home())
    language: str = "en"
    input_mode: str = "push-to-talk"
    microphone: str = ""
    output_device: str = ""
    preview_transcript: bool = True
    persist_transcript: bool = False
    reduced_motion: bool = False
    spoken_progress: bool = True
    progress_interval: float = 20.0
    command_ttl: float = 30.0
    cpu_threads: int = 4
    compute_type: str = "int8"
    beam_size: int = 3
    max_utterance_seconds: int = 30
    terminal: str = ""
    media_enabled: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Settings:
        if not isinstance(raw, dict):
            raise ConfigError("Configuration must be a JSON object.")
        data = dict(raw)
        version = data.get("schema_version", 1)
        if type(version) is not int or version not in (1, 2):
            raise ConfigError(f"Unsupported configuration schema: {version!r}. Update JKI first.")
        if version == 1:
            # Never inherit broad permissions from a legacy boolean or resumed thread.
            data.pop("full_access", None)
            data["permission_profile"] = "restricted"
            data["full_access_acknowledged"] = False
            data["schema_version"] = 2
        allowed = {field.name for field in fields(cls)}
        unknown = set(data) - allowed
        if unknown:
            raise ConfigError("Unknown configuration fields: " + ", ".join(sorted(unknown)))
        defaults = cls()
        for key, value in data.items():
            default = getattr(defaults, key)
            if isinstance(default, bool):
                valid = type(value) is bool
            elif isinstance(default, int):
                valid = type(value) is int
            elif isinstance(default, float):
                valid = type(value) in (int, float)
            else:
                valid = isinstance(value, str)
            if not valid:
                raise ConfigError(f"Invalid type for {key}.")
        settings = cls(**data)
        choices = {
            "permission_profile": {"restricted", "workspace", "full"},
            "input_mode": {"wake-word", "push-to-talk"},
            "tts_engine": {"piper", "espeak"},
            "compute_type": {"int8", "float32"},
        }
        for key, values in choices.items():
            if getattr(settings, key) not in values:
                raise ConfigError(f"{key} must be one of: {', '.join(sorted(values))}.")
        for key, low, high in (
            ("cpu_threads", 1, 32), ("beam_size", 1, 10),
            ("max_utterance_seconds", 1, 60), ("progress_interval", 5, 300),
            ("command_ttl", 1, 300),
        ):
            if not low <= getattr(settings, key) <= high:
                raise ConfigError(f"{key} must be between {low} and {high}.")
        if not settings.wake_word.strip() or len(settings.wake_word) > 40:
            raise ConfigError("wake_word must contain 1–40 characters.")
        if settings.language != "auto" and not re.fullmatch(r"[a-z]{2,3}", settings.language):
            raise ConfigError("language must be a language code, such as en or fi, or auto.")
        if settings.effort and not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", settings.effort):
            raise ConfigError("effort must be a reasoning level identifier from the model catalog.")
        if settings.transcription_model_path.endswith(".en") and settings.language not in ("en", "auto"):
            raise ConfigError("An English-only Whisper model cannot transcribe this language.")
        for key in ("workspace", "socket_path", "model_path"):
            if not Path(getattr(settings, key)).is_absolute():
                raise ConfigError(f"{key} must be an absolute path.")
        if settings.permission_profile == "full" and not settings.full_access_acknowledged:
            raise ConfigError("Full access requires explicit confirmation in setup.")
        if settings.tts_engine == "piper" and not Path(settings.tts_model_path).is_absolute():
            raise ConfigError("Piper requires an absolute tts_model_path.")
        return settings

    def validate_runtime(self) -> None:
        if not self.thread_id or self.thread_id.startswith("REPLACE_"):
            raise ConfigError("Choose a Codex conversation using 'jki setup'.")
        if not Path(self.workspace).is_dir():
            raise ConfigError("Workspace directory not found. Run 'jki setup'.")

    def policy(self) -> dict[str, Any]:
        if self.permission_profile == "restricted":
            return {"type": "readOnly"}
        if self.permission_profile == "workspace":
            return {
                "type": "workspaceWrite", "writableRoots": [self.workspace],
                "networkAccess": False, "excludeTmpdirEnvVar": True,
                "excludeSlashTmp": True,
            }
        return {"type": "dangerFullAccess"}

    def resume_options(self) -> dict[str, Any]:
        mode = {"restricted": "read-only", "workspace": "workspace-write", "full": "danger-full-access"}
        result: dict[str, Any] = {
            "sandbox": mode[self.permission_profile], "approvalPolicy": "on-request",
            "cwd": self.workspace,
        }
        if self.model:
            result["model"] = self.model
        return result

    def turn_options(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sandboxPolicy": self.policy(), "approvalPolicy": "on-request", "cwd": self.workspace,
        }
        if self.model:
            result["model"] = self.model
        return result


class ConfigStore:
    def __init__(self, path: Path = CONFIG):
        self.path = Path(path).expanduser().absolute()
        self.lock = threading.RLock()

    def load(self) -> Settings:
        try:
            with self.lock:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            return Settings.from_dict(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Cannot read configuration at {self.path}. Run 'jki setup'.") from exc

    def save(self, settings: Settings) -> None:
        checked = Settings.from_dict(asdict(settings))
        with self.lock:
            atomic_json(self.path, asdict(checked))


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return asdict(ConfigStore(path).load())


def save_config(config: dict[str, Any], path: Path = CONFIG) -> None:
    ConfigStore(path).save(Settings.from_dict(config))
