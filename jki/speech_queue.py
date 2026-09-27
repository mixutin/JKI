"""Bounded output queue with coalesced, disposable progress announcements."""
from collections import deque
import queue
import threading
import time
from .state import Speech


class SpeechQueue:
    def __init__(self, limit: int = 8):
        self.limit = limit
        self.items: deque[Speech] = deque()
        self.condition = threading.Condition()

    def put(self, item: Speech) -> None:
        with self.condition:
            if item.progress:
                self.items = deque(x for x in self.items if not x.progress)
            else:
                self.items = deque(x for x in self.items if not x.progress or x.turn_id != item.turn_id)
            if len(self.items) >= self.limit:
                self.items.popleft()
            self.items.append(item)
            self.condition.notify()

    def get(self, timeout: float = .2) -> Speech:
        until = time.monotonic() + timeout
        with self.condition:
            while not self.items:
                remaining = until - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                self.condition.wait(remaining)
            return self.items.popleft()

    def get_nowait(self) -> Speech:
        return self.get(timeout=0)

    def clear(self) -> None:
        with self.condition:
            self.items.clear()

    def drop_progress(self, turn_id: str) -> None:
        with self.condition:
            self.items = deque(x for x in self.items if not (x.progress and x.turn_id == turn_id))

    def empty(self) -> bool:
        with self.condition:
            return not self.items

    def qsize(self) -> int:
        with self.condition:
            return len(self.items)
