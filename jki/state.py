"""Small bounded primitives shared by the engine and its adapters."""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
import math
import threading
import time
from typing import Any, Callable


class RecentIDs:
    def __init__(self, limit: int = 512):
        self.limit = limit
        self.values: OrderedDict[str, None] = OrderedDict()

    def add(self, identifier: str) -> bool:
        if not identifier or identifier in self.values:
            return False
        self.values[identifier] = None
        while len(self.values) > self.limit:
            self.values.popitem(last=False)
        return True

    def __contains__(self, identifier: str) -> bool:
        return identifier in self.values

    def __len__(self) -> int:
        return len(self.values)


@dataclass(frozen=True, slots=True)
class Captured:
    payload: bytes | str
    epoch: int
    created: float

    def valid(self, epoch: int, now: float, ttl: float) -> bool:
        return self.epoch == epoch and 0 <= now - self.created <= ttl


@dataclass(frozen=True, slots=True)
class Speech:
    text: str
    epoch: int
    turn_id: str | None = None
    progress: bool = False
    created: float = field(default_factory=time.monotonic)


@dataclass
class Health:
    connected: bool = False
    microphone: str = "starting"
    transcription: str = "starting"
    tts: str = "starting"
    active_turn: str | None = None
    owned_turn: bool = False
    cancelling: bool = False
    uncertain: bool = False
    submitting: bool = False
    hearing: bool = False
    error: str = ""
    backend_error: str = ""
    last_result: str = ""
    progress: str = ""
    preview: str = ""
    approvals: dict[Any, dict[str, Any]] = field(default_factory=dict)

    def status(self, muted: bool, speaking: bool, ptt: bool) -> tuple[str, str]:
        if self.approvals:
            return "attention", "Waiting for on-screen approval"
        if self.uncertain:
            return "attention", "Task state is uncertain; check the conversation before retrying"
        if self.error:
            return "attention", self.error
        if self.cancelling:
            return "working", "Cancellation requested; waiting for confirmation"
        if self.active_turn or self.submitting:
            return "working", self.progress or "Working on your request"
        if self.preview:
            return "preview", "Review the transcript, then Send or Discard"
        if speaking:
            return "speaking", "Speaking"
        if muted:
            return "muted", "Microphone off"
        if self.microphone == "error" or self.transcription == "error":
            return "error", "Speech input unavailable; text commands still work. Run jki doctor."
        if self.microphone == "starting" or self.transcription == "starting":
            return "starting", "Loading local speech components"
        if not self.connected:
            return "offline", self.backend_error or "Codex is offline; enabled local media controls still work"
        if self.hearing:
            return "hearing", "Understanding your command"
        return "listening", "Hold to talk" if ptt else "Say the wake word and your command"


class Metrics:
    """Transcript-free bounded timings. All access is synchronized."""
    def __init__(self, limit: int = 256):
        self.limit = limit
        self.values: dict[str, deque[float]] = {}
        self.lock = threading.Lock()

    def record(self, name: str, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            return
        with self.lock:
            self.values.setdefault(name, deque(maxlen=self.limit)).append(seconds)

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        with self.lock:
            result: dict[str, dict[str, float | int]] = {}
            for name, samples in self.values.items():
                ordered = sorted(samples)
                result[name] = {"count": len(ordered), "p50_seconds": ordered[len(ordered) // 2],
                                "p95_seconds": ordered[math.ceil(len(ordered) * .95) - 1]}
            return result


class Progress:
    """No timer-based claims: only report observed events, rate-limited for speech."""
    def __init__(self, interval: float, clock: Callable[[], float] = time.monotonic):
        self.interval = interval
        self.clock = clock
        self.last_time = float("-inf")
        self.last_text = ""
        self.last_turn: str | None = None

    def begin(self, turn_id: str) -> bool:
        if turn_id == self.last_turn:
            return False
        self.last_turn = turn_id
        self.last_text = ""
        self.last_time = self.clock()
        return True

    def allow(self, text: str) -> bool:
        now = self.clock()
        if text == self.last_text or now - self.last_time < self.interval:
            return False
        self.last_text, self.last_time = text, now
        return True
