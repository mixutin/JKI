from contextlib import nullcontext
from pathlib import Path
import tempfile
import threading
import time

from jki.config import Settings
from jki.engine import Command, Engine
from jki.protocol import RequestDiscarded


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeClient:
    def __init__(self):
        self.calls = []
        self.responses = []
        self.closed = threading.Event()
        self.counter = 0
        self.failure = None
        self.before_send = None
        self.after_send = None

    def call(self, method, params, timeout=20, *, send_context=None, check=None):
        if self.before_send:
            self.before_send()
        with send_context if send_context is not None else nullcontext():
            if check and not check():
                raise RequestDiscarded()
            self.calls.append((method, params))
        if self.failure:
            raise self.failure
        if self.after_send:
            self.after_send(method, params)
        if method == "turn/start":
            self.counter += 1
            return {"turn": {"id": f"turn-{self.counter}", "status": "inProgress"}}
        if method == "turn/steer":
            return {"turnId": params["expectedTurnId"]}
        return {}

    def respond(self, identifier, result):
        self.responses.append((identifier, result))

    def unsupported(self, identifier):
        self.responses.append((identifier, "unsupported"))

    def close(self):
        self.closed.set()


def wait_for(condition, timeout=2):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            raise AssertionError("Condition did not become true")
        time.sleep(.005)


class EngineFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.settings = Settings(thread_id="test", workspace=self.temp.name)
        self.engine = Engine(self.settings, Path(self.temp.name) / "custom.json", clock=self.clock)
        self.client = FakeClient()
        self.engine.client = self.client
        self.engine.health.connected = True
        for component in ("microphone", "transcription", "tts"):
            self.engine.component(component, "ready")
        self.addCleanup(self.engine.close)

    def command(self, text="Read the file", voice=False):
        return Command("command", text, self.engine.capture_epoch, self.clock(), voice)

    def start(self):
        self.engine._execute(self.command())
        return self.engine.health.active_turn

    def event(self, method, **params):
        self.engine._event({"method": method, "params": {"threadId": "test", **params}})

    def speech(self):
        result = []
        while not self.engine.speech.empty():
            result.append(self.engine.speech.get_nowait().text)
        return result
