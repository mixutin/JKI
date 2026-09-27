"""Opt-in local media shortcuts with bounded subprocess lifetime and output."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
import threading
from typing import Any, Callable


def music_query(text: str) -> str | None:
    if re.search(r"\bon (?:spotify|youtube|apple music)\b", text):
        return None
    match = re.match(r"^play (?:the )?(?:song|track|music)(?: called)? (.+)$", text)
    if match:
        return match.group(1).strip(" .!?")
    if text.startswith("play ") and " by " in text:
        return text[5:].strip(" .!?")
    return None


class MediaController:
    def __init__(self, say: Callable[[str], None]):
        self.say = say
        self.lock = threading.RLock()
        self.process: Any = None
        self.watcher: threading.Thread | None = None
        self.directory: Any = None
        self.socket_path: Path | None = None

    def _ipc(self, command: list) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(str(self.socket_path))
            connection.sendall((json.dumps({"command": command, "request_id": 1}) + "\n").encode())
            with connection.makefile("rb") as reader:
                for _ in range(32):
                    line = reader.readline(65537)
                    if not line or len(line) > 65536:
                        break
                    response = json.loads(line)
                    if response.get("request_id") == 1:
                        if response.get("error") != "success":
                            raise RuntimeError("Media command failed")
                        return
            raise RuntimeError("Media player did not respond")

    def handle(self, text: str) -> bool:
        query = music_query(text)
        if query:
            self.play(query)
            return True
        actions = {"pause music": ("set_property", "pause", True),
                   "pause the music": ("set_property", "pause", True),
                   "resume music": ("set_property", "pause", False),
                   "resume the music": ("set_property", "pause", False),
                   "play music": ("set_property", "pause", False),
                   "stop music": ("stop",), "stop the music": ("stop",),
                   "next song": ("playlist-next", "force"), "next track": ("playlist-next", "force"),
                   "skip song": ("playlist-next", "force"), "previous song": ("playlist-prev", "force")}
        if text in actions:
            action = actions[text]
            with self.lock:
                own_player = self.process and self.process.poll() is None
            if own_player:
                if action[0].startswith("playlist-"):
                    self.say("This is a single requested track. Ask for another song by name.")
                else:
                    self._ipc(list(action))
            else:
                command = ("pause" if action == ("set_property", "pause", True) else
                           "play" if action == ("set_property", "pause", False) else
                           "next" if action[0] == "playlist-next" else
                           "previous" if action[0] == "playlist-prev" else "stop")
                subprocess.run(["playerctl", command], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=5, check=True)
            return True
        volume = {"volume up": "5%+", "turn the volume up": "5%+", "turn volume up": "5%+",
                  "volume down": "5%-", "turn the volume down": "5%-", "turn volume down": "5%-"}
        match = re.match(r"^(?:set )?(?:the )?volume (?:to )?(\d{1,3})(?: ?percent| ?%)?$", text)
        amount = volume.get(text)
        if match:
            amount = f"{min(100, int(match.group(1)))}%"
        if amount:
            subprocess.run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", amount],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=True)
            return True
        return False

    def play(self, query: str) -> None:
        self.close()
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        directory = tempfile.TemporaryDirectory(prefix="jki-media-", dir=runtime or None)
        socket_path = Path(directory.name) / "mpv.sock"
        try:
            process = subprocess.Popen([
                "mpv", "--no-video", "--force-window=no", "--no-terminal",
                "--input-ipc-server=" + str(socket_path), "--ytdl-format=bestaudio/best",
                "--", "ytdl://ytsearch1:" + query,
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception:
            directory.cleanup()
            raise
        with self.lock:
            self.directory, self.socket_path, self.process = directory, socket_path, process
        self.say("I'm looking for that track.")

        def watch():
            code = process.wait()
            with self.lock:
                current = self.process is process
            if code > 0 and current:
                self.say("The music player could not play that track.")
        self.watcher = threading.Thread(target=watch, name="jki-media", daemon=True)
        self.watcher.start()

    def close(self) -> None:
        with self.lock:
            process, directory, watcher = self.process, self.directory, self.watcher
            self.process = self.directory = self.watcher = None
            self.socket_path = None
        if process:
            try:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=1)
            except ProcessLookupError:
                process.wait(timeout=1)
        if watcher and watcher is not threading.current_thread():
            watcher.join(timeout=1)
        if directory:
            directory.cleanup()
