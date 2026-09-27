"""Desktop integration without shell interpolation or a hardcoded terminal."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable

from .config import STATE, Settings, atomic_json, xdg_path


def conversation_command(settings: Settings, which: Callable = shutil.which) -> list[str]:
    codex = which(settings.codex_path)
    if not codex:
        raise RuntimeError("Codex executable not found. Update codex_path using jki setup.")
    terminals = [("kitty", "-e"), ("foot", "-e"), ("gnome-terminal", "--"),
                 ("konsole", "-e"), ("x-terminal-emulator", "-e"), ("xterm", "-e")]
    if settings.terminal:
        binary = which(settings.terminal)
        if not binary:
            raise RuntimeError("Configured terminal was not found")
        separator = "--" if Path(binary).name == "gnome-terminal" else "-e"
        return [binary, separator, codex, "resume", settings.thread_id]
    for name, separator in terminals:
        binary = which(name)
        if binary:
            return [binary, separator, codex, "resume", settings.thread_id]
    raise RuntimeError("No supported terminal found. Set terminal in jki setup.")


def open_conversation(settings: Settings) -> None:
    subprocess.Popen(conversation_command(settings), start_new_session=True)


class StatusFile:
    def __init__(self, path: Path = STATE / "status.json"):
        self.path = path
        self.previous: str | None = None

    def update(self, snapshot: dict[str, Any], persist_transcript: bool = False) -> None:
        # Error details, progress, previews, approvals, and paths never enter this file.
        value = {key: snapshot[key] for key in ("status", "connected", "model", "permission_profile")}
        value.update(pid=os.getpid(), schema_version=2)
        if persist_transcript:
            value["heard"] = snapshot["heard"]
        key = json.dumps(value, sort_keys=True)
        if key != self.previous:
            atomic_json(self.path, value)
            self.previous = key

    def close(self) -> None:
        self.path.unlink(missing_ok=True)


def _quote(value: str) -> str:
    if any(c in value for c in "\n\r\x00$`"):
        raise ValueError("Invalid executable/configuration path")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def install_desktop(config_path: Path) -> tuple[Path, Path]:
    command = " ".join(_quote(arg) for arg in (sys.executable, "-m", "jki", "run", "--config", str(config_path)))
    applications = xdg_path("XDG_DATA_HOME", "~/.local/share") / "applications"
    units = xdg_path("XDG_CONFIG_HOME", "~/.config") / "systemd/user"
    applications.mkdir(parents=True, exist_ok=True)
    units.mkdir(parents=True, exist_ok=True)
    desktop = applications / "local.jake.Voice.desktop"
    service = units / "jake-voice.service"
    desktop.write_text("[Desktop Entry]\nType=Application\nName=JKI (Jake Voice)\n"
                       "Comment=Local speech companion for Codex\n"
                       f"Exec={command}\nTerminal=false\nCategories=Utility;\n"
                       "Keywords=voice;assistant;Codex;speech;\n", encoding="utf-8")
    service.write_text("[Unit]\nDescription=JKI (Jake Voice)\n"
                       "After=graphical-session.target pipewire.service\nPartOf=graphical-session.target\n"
                       "\n[Service]\nType=simple\nUMask=0077\nNoNewPrivileges=yes\n"
                       f"ExecStart={command}\nRestart=on-failure\nRestartSec=5\nTimeoutStopSec=15\n"
                       "\n[Install]\nWantedBy=graphical-session.target\n", encoding="utf-8")
    return desktop, service
