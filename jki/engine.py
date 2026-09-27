"""Thread-safe orchestration; hardware and transport are injectable adapters."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass, replace
import json
import queue
import threading
import time
from typing import Any, Callable
import uuid

from .config import CONFIG, ConfigStore, Settings
from .protocol import CodexClient, RequestDiscarded
from .speech_queue import SpeechQueue
from .state import Captured, Health, Metrics, Progress, RecentIDs, Speech
from .text import WakeGate, effort_choice, model_choice, speakable

APPROVAL_METHODS = {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}


@dataclass(frozen=True)
class Command:
    kind: str
    value: str
    epoch: int
    created: float
    voice: bool = False


class Engine:
    def __init__(self, config: Settings | dict[str, Any], config_path=CONFIG, *,
                 client_factory: Callable[..., Any] = CodexClient,
                 clock: Callable[[], float] = time.monotonic):
        self.settings = Settings.from_dict(asdict(config) if isinstance(config, Settings) else config)
        self.store = ConfigStore(config_path)
        self.client_factory = client_factory
        self.clock = clock
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.muted = threading.Event()
        self.speaking = threading.Event()
        self.capture_active = threading.Event()
        self.health = Health()
        self.gate = WakeGate(self.settings.wake_word)
        self.client: Any = None
        self.connection_generation = 0
        self.commands: queue.Queue[Command] = queue.Queue(maxsize=8)
        self.controls: queue.Queue = queue.Queue(maxsize=16)
        self.recognitions: queue.Queue[Captured] = queue.Queue(maxsize=2)
        self.speech = SpeechQueue(limit=8)
        self.seen_items = RecentIDs(512)
        self.completed_turns = RecentIDs(128)
        self.owned_turns = RecentIDs(128)
        self.turn_records: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.item_context: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.models: list[str] = []
        self.model_catalog: list[dict[str, Any]] = []
        self.model = self.settings.model
        self.effort = self.settings.effort
        self.last_heard = ""
        self.level = 0.0
        self.capture_epoch = 0
        self.speech_epoch = 0
        self.output_cancel = threading.Event()
        self.quiet_until = 0.0
        self.preview_token = ""
        self.preview_capture: Captured | None = None
        self.metrics = Metrics()
        self.progress = Progress(self.settings.progress_interval, clock)
        self.turn_started_at: dict[str, float] = {}
        self.threads: list[threading.Thread] = []
        self.audio: Any = None
        self.music: Any = None
        self.effective_policy = "not connected"
        self.started = False

    def _spawn(self, target: Callable, name: str) -> None:
        def supervised():
            try:
                target()
            except Exception:
                with self.lock:
                    self.health.error = f"{name} stopped unexpectedly. Restart JKI and run jki doctor."
        thread = threading.Thread(target=supervised, name=f"jki-{name}", daemon=True)
        self.threads.append(thread)
        thread.start()

    def start(self) -> None:
        with self.lock:
            if self.started:
                return
            self.started = True
        from .audio import AudioPipeline
        from .media import MediaController
        self.music = MediaController(self.say)
        self.audio = AudioPipeline(self)
        for target, name in ((self._connect_loop, "connection"), (self._command_loop, "commands"),
                             (self._control_loop, "controls"), (self.audio.microphone_loop, "microphone"),
                             (self.audio.transcription_loop, "transcription"), (self.audio.speech_loop, "speech")):
            self._spawn(target, name)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            status, detail = self.health.status(self.muted.is_set(), self.speaking.is_set(),
                                                 self.settings.input_mode == "push-to-talk")
            return {
                "status": status, "detail": detail, "connected": self.health.connected,
                "model": self.model, "models": list(self.models), "model_catalog": list(self.model_catalog),
                "effort": self.effort, "efforts": self.supported_efforts(), "heard": self.last_heard,
                "level": self.level, "muted": self.muted.is_set(),
                "input_mode": self.settings.input_mode, "capturing": self.capture_active.is_set(),
                "active_turn": self.health.active_turn, "owned_turn": self.health.owned_turn,
                "cancelling": self.health.cancelling, "uncertain": self.health.uncertain,
                "submitting": self.health.submitting,
                "microphone_health": self.health.microphone, "transcription_health": self.health.transcription,
                "tts_health": self.health.tts, "permission_profile": self.settings.permission_profile,
                "effective_policy": self.effective_policy, "workspace": self.settings.workspace,
                "thread_id": self.settings.thread_id, "progress": self.health.progress,
                "preview": self.health.preview, "preview_token": self.preview_token,
                "last_result": self.health.last_result,
                "approvals": json.loads(json.dumps(list(self.health.approvals.values()))),
                "metrics": self.metrics.snapshot(),
            }

    def component(self, name: str, state: str) -> None:
        if name not in {"microphone", "transcription", "tts"}:
            raise ValueError("Unknown component")
        with self.lock:
            setattr(self.health, name, state)

    def _record(self, turn_id: str) -> dict[str, Any]:
        record = self.turn_records.setdefault(turn_id, {})
        while len(self.turn_records) > 32:
            self.turn_records.popitem(last=False)
        return record

    def _verify_resume(self, result: dict[str, Any]) -> None:
        actual = result.get("sandbox", {})
        if not isinstance(actual, dict) or actual.get("type") != self.settings.policy()["type"]:
            raise RuntimeError("Server did not confirm the requested sandbox. No commands will be sent.")
        if result.get("approvalPolicy") != "on-request":
            raise RuntimeError("Server did not confirm human approval policy. No commands will be sent.")
        if result.get("cwd") != self.settings.workspace:
            raise RuntimeError("Server workspace differs from configuration. Run jki setup.")
        self.effective_policy = actual["type"]

    def _connect_loop(self) -> None:
        retry = 1.0
        while not self.stopping.is_set():
            client = None
            with self.lock:
                self.connection_generation += 1
                generation = self.connection_generation
            try:
                client = self.client_factory(self.settings.socket_path,
                                             lambda event, g=generation: self._event(event, g))
                catalog: list[dict[str, Any]] = []
                cursor = None
                for _ in range(16):
                    params = {"limit": 100}
                    if cursor:
                        params["cursor"] = cursor
                    page = client.call("model/list", params)
                    catalog.extend(m for m in page.get("data", []) if not m.get("hidden", False))
                    cursor = page.get("nextCursor")
                    if not cursor:
                        break
                result = client.call("thread/resume", {
                    "threadId": self.settings.thread_id, "excludeTurns": False,
                    **self.settings.resume_options(),
                })
                with self.lock:
                    self._verify_resume(result)
                    self.model_catalog = list({m["model"]: m for m in catalog if m.get("model")}.values())
                    self.models = [m["model"] for m in self.model_catalog]
                    self.model = self.settings.model or result.get("model", self.model)
                    self.effort = self._available_effort(self.model, self.settings.effort)
                    self.client = client
                    self.health.connected = True
                    self.health.backend_error = ""
                    self._reconcile(result.get("thread", {}))
                retry = 1.0
                while not self.stopping.is_set() and not client.closed.wait(.2):
                    pass
            except Exception as exc:
                with self.lock:
                    self.health.connected = False
                    self.health.backend_error = str(exc)[:1000] or "Connection failed; run jki doctor."
                    self.effective_policy = "unverified; commands blocked"
            finally:
                with self.lock:
                    if self.client is client:
                        self.client = None
                    self.health.connected = False
                if client:
                    client.close()
            self.stopping.wait(retry)
            retry = min(30.0, retry * 2)

    def _reconcile(self, thread: dict[str, Any]) -> None:
        """Called under the engine lock. Never replay commands on reconnect."""
        previous = self.health.active_turn
        turns = thread.get("turns", [])
        active = next((t for t in reversed(turns) if t.get("status") == "inProgress"), None)
        if active:
            self.health.active_turn = active["id"]
            self.health.owned_turn = active["id"] in self.owned_turns
            self.health.uncertain = False
            self.health.progress = "Reconnected to an active task"
        elif previous:
            finished = next((t for t in turns if t.get("id") == previous), None)
            if finished and finished.get("status") in {"completed", "failed", "interrupted"}:
                for item in finished.get("items", []):
                    if item.get("type") == "agentMessage" and item.get("phase") != "commentary":
                        self._record(previous)["answer"] = item
                self._finish_turn(finished)
            else:
                self.health.uncertain = True
        # Unknown submission outcome is deliberately not cleared by an idle thread.

    def _event(self, event: dict[str, Any], generation: int | None = None) -> None:
        with self.lock:
            if generation is not None and generation != self.connection_generation:
                return
            method, params = event.get("method", ""), event.get("params", {})
            if not isinstance(params, dict):
                return
            if method == "jake/disconnected":
                self.health.connected = False
                if self.health.active_turn or self.health.submitting:
                    self.health.uncertain = True
                self.health.approvals.clear()
                return
            turn_id = params.get("turnId") or params.get("turn", {}).get("id")
            if params.get("threadId") != self.settings.thread_id:
                # Events without a thread ID require a known, explicitly scoped turn ID.
                if params.get("threadId") is not None or not turn_id or turn_id != self.health.active_turn:
                    return
            if method == "turn/started":
                if turn_id and turn_id not in self.completed_turns:
                    self.health.active_turn = turn_id
                    self.health.owned_turn = turn_id in self.owned_turns
            elif method == "turn/completed":
                self._finish_turn(params.get("turn", {}))
            elif method == "serverRequest/resolved":
                self.health.approvals.pop(params.get("requestId"), None)
            elif method in APPROVAL_METHODS and "id" in event:
                self._approval(event)
            elif "id" in event and "method" in event:
                # Unsupported requests fail closed instead of silently hanging or auto-approving.
                self._control(("unsupported", event["id"], self.connection_generation))
                self.health.error = "Codex requested an unsupported interaction. Review the conversation."
            elif method in {"item/started", "item/completed"}:
                item = params.get("item", {})
                kind = item.get("type")
                if kind in {"commandExecution", "fileChange"} and item.get("id"):
                    encoded = json.dumps(item)
                    self.item_context[item["id"]] = item if len(encoded) <= 131072 else {
                        "truncated": True, "notice": "Details exceed the safe preview limit. Do not approve here."
                    }
                    while len(self.item_context) > 32:
                        self.item_context.popitem(last=False)
                if not turn_id:
                    return
                if kind == "agentMessage" and method == "item/completed":
                    if item.get("phase") == "commentary":
                        self._progress(turn_id, speakable(item.get("text", ""), 220))
                    else:
                        self._record(turn_id)["answer"] = item
                elif method == "item/started":
                    labels = {"commandExecution": "Preparing a command.", "fileChange": "Preparing file changes.",
                              "mcpToolCall": "Using a connected tool.", "webSearch": "Searching the web."}
                    if kind in labels:
                        self._progress(turn_id, labels[kind])
                elif kind == "commandExecution":
                    text = "A command finished." if item.get("status") == "completed" else "A command reported a failure."
                    self._progress(turn_id, text)
            elif method == "turn/plan/updated" and turn_id:
                plan = params.get("plan", [])
                current = next(((i, p) for i, p in enumerate(plan, 1) if p.get("status") == "inProgress"), None)
                if current:
                    i, step = current
                    self._progress(turn_id, f"Step {i} of {len(plan)}: {speakable(step.get('step', ''), 180)}")
            elif method == "error":
                self.health.error = "Codex reported an error. Check the conversation."

    def _progress(self, turn_id: str, text: str) -> None:
        if not text or turn_id != self.health.active_turn or turn_id not in self.owned_turns:
            return
        self.health.progress = text
        if (self.settings.spoken_progress and not self.health.approvals and not self.health.cancelling
                and self.progress.allow(text)):
            self.say(text, turn_id=turn_id, progress=True)

    def _accepted(self, turn_id: str) -> None:
        self.owned_turns.add(turn_id)
        self.health.submitting = False
        record = self._record(turn_id)
        if "terminal" in record:
            self._finish_turn(record["terminal"])
            return
        self.health.active_turn = turn_id
        self.health.owned_turn = True
        self.health.uncertain = False
        self.health.progress = "Working on your request"
        self.turn_started_at[turn_id] = self.clock()
        if self.progress.begin(turn_id) and not self.health.cancelling:
            self.say("I'm doing it now.", turn_id=turn_id, progress=True)
        if self.health.cancelling:
            self._control(("cancel",))

    def _finish_turn(self, turn: dict[str, Any]) -> None:
        turn_id, status = turn.get("id"), turn.get("status")
        if not turn_id or status not in {"completed", "failed", "interrupted"}:
            return
        record = self._record(turn_id)
        record["terminal"] = turn
        self.health.approvals = {k: v for k, v in self.health.approvals.items() if v["turn_id"] != turn_id}
        # A completion notification can precede the turn/start response.
        if turn_id not in self.owned_turns:
            if not self.health.submitting and self.health.active_turn == turn_id:
                self.health.active_turn = None
                self.health.owned_turn = False
            return
        if not self.completed_turns.add(turn_id):
            return
        self.speech.drop_progress(turn_id)
        self.health.approvals = {k: v for k, v in self.health.approvals.items() if v["turn_id"] != turn_id}
        if self.health.active_turn in (None, turn_id):
            self.health.active_turn = None
            self.health.owned_turn = False
            self.health.cancelling = False
            self.health.uncertain = False
            self.health.submitting = False
        self.health.last_result = status
        self.health.progress = ""
        start = self.turn_started_at.pop(turn_id, None)
        if start is not None:
            self.metrics.record("task_duration", self.clock() - start)
        if status == "failed":
            error = turn.get("error") or {}
            self.health.error = str(error.get("message", "The task failed; check the conversation."))[:2000]
            self.say("The task failed. Please check the conversation for details.", turn_id=turn_id)
        elif status == "interrupted":
            self.say("The task was cancelled. Earlier changes were not undone.", turn_id=turn_id)
        else:
            item = record.get("answer")
            if item and item.get("text"):
                self._answer(item, turn_id)
            else:
                self.say("The task finished. See the conversation for details.", turn_id=turn_id)

    def _answer(self, item: dict[str, Any], turn_id: str | None = None) -> None:
        identifier = item.get("id")
        if identifier and self.seen_items.add(identifier) and item.get("text"):
            self.say(item["text"], turn_id=turn_id)

    def _approval(self, event: dict[str, Any]) -> None:
        params, identifier = event["params"], event["id"]
        if identifier in self.health.approvals:
            return
        if (not params.get("turnId") or params["turnId"] in self.completed_turns or
                (params["turnId"] != self.health.active_turn and not self.health.submitting)):
            self._control(("unsupported", identifier, self.connection_generation))
            return
        if len(self.health.approvals) >= 16:
            self._control(("unsupported", identifier, self.connection_generation))
            self.health.error = "Too many pending approvals. Cancel the task and review Codex."
            return
        item = self.item_context.get(params.get("itemId"), {})
        is_command = event["method"] == "item/commandExecution/requestApproval"
        context = params.get("networkApprovalContext") or params.get("command") or item.get("command")
        can_accept = bool(context) if is_command else bool(item.get("changes"))
        if item.get("truncated"):
            can_accept = False
        decisions = [x for x in params.get("availableDecisions", ["accept", "decline", "cancel"])
                     if isinstance(x, str) and x in {"accept", "decline", "cancel"}]
        if "accept" not in decisions:
            can_accept = False
        self.health.approvals[identifier] = {
            "id": identifier, "method": event["method"], "params": params, "item": item,
            "turn_id": params.get("turnId"), "connection": self.connection_generation,
            "can_accept": can_accept, "decisions": decisions, "answered": False,
        }
        self.say("I need your approval. Please review the details on screen.", turn_id=params.get("turnId"))

    def resolve_approval(self, identifier: int | str, decision: str) -> bool:
        with self.lock:
            pending = self.health.approvals.get(identifier)
            if (not pending or pending["answered"] or not self.health.connected
                    or pending["connection"] != self.connection_generation
                    or pending["turn_id"] != self.health.active_turn):
                return False
            if decision not in pending["decisions"] or (decision == "accept" and not pending["can_accept"]):
                return False
            pending["answered"] = True
            if not self._control(("approval", identifier, decision, self.connection_generation)):
                pending["answered"] = False
                return False
            return True

    def _control(self, value: tuple) -> bool:
        try:
            self.controls.put_nowait(value)
            return True
        except queue.Full:
            self.health.error = "Control queue is full. Check the conversation."
            return False

    def _control_loop(self) -> None:
        while not self.stopping.is_set():
            try:
                action = self.controls.get(timeout=.2)
            except queue.Empty:
                continue
            with self.lock:
                client = self.client
                active = self.health.active_turn
                generation = self.connection_generation
            if not client:
                continue
            try:
                if action[0] == "cancel" and active:
                    client.call("turn/interrupt", {"threadId": self.settings.thread_id, "turnId": active})
                elif action[0] == "approval" and action[3] == generation:
                    with self.lock:
                        pending = self.health.approvals.get(action[1])
                        valid = (pending and pending["connection"] == generation
                                 and pending["turn_id"] == self.health.active_turn)
                        if valid:
                            client.respond(action[1], {"decision": action[2]})
                elif action[0] == "unsupported" and action[2] == generation:
                    client.unsupported(action[1])
                elif action[0] == "resync":
                    result = client.call("thread/read", {"threadId": self.settings.thread_id, "includeTurns": True})
                    with self.lock:
                        self._reconcile(result.get("thread", {}))
            except Exception:
                with self.lock:
                    self.health.uncertain = True
                    self.health.error = "Control request was not confirmed. Check Codex before retrying."

    @staticmethod
    def _drain(work_queue: queue.Queue) -> None:
        while True:
            try:
                work_queue.get_nowait()
            except queue.Empty:
                return

    def _invalidate_capture(self) -> None:
        self.capture_epoch += 1
        self.gate.reset()
        self.capture_active.clear()
        self.preview_capture = None
        self.preview_token = ""
        self.health.preview = ""
        self.health.hearing = False
        self._drain(self.recognitions)
        self._drain(self.commands)

    def toggle_mute(self) -> None:
        with self.lock:
            self._invalidate_capture()
            if self.muted.is_set():
                self.muted.clear()
            else:
                self.muted.set()
            self.level = 0
        if self.audio:
            self.audio.stop_capture()

    def begin_capture(self) -> None:
        with self.lock:
            if self.muted.is_set() or self.capture_active.is_set() or self.settings.input_mode != "push-to-talk":
                return
            self._invalidate_capture()
            self.capture_active.set()
        self.stop_speaking()

    def end_capture(self) -> None:
        self.capture_active.clear()

    def set_input_mode(self, mode: str) -> None:
        if mode not in {"wake-word", "push-to-talk"}:
            raise ValueError("Invalid input mode")
        with self.lock:
            updated = replace(self.settings, input_mode=mode)
            self.store.save(updated)
            self.settings = updated
            self._invalidate_capture()
        if self.audio:
            self.audio.stop_capture()

    def set_reduced_motion(self, enabled: bool) -> None:
        with self.lock:
            updated = replace(self.settings, reduced_motion=enabled)
            self.store.save(updated)
            self.settings = updated

    def set_microphone(self, name: str) -> None:
        with self.lock:
            updated = replace(self.settings, microphone=name)
            self.store.save(updated)
            self.settings = updated
            self._invalidate_capture()
        if self.audio:
            self.audio.stop_capture()

    def accept_audio(self, captured: Captured) -> bool:
        with self.lock:
            if self.muted.is_set() or not captured.valid(self.capture_epoch, self.clock(), self.settings.command_ttl):
                return False
            try:
                self.recognitions.put_nowait(captured)
                return True
            except queue.Full:
                self.health.error = "Speech processing is busy. Please try again after it finishes."
                return False

    def transcription_ready(self, text: str, captured: Captured) -> bool:
        with self.lock:
            self.health.hearing = False
            if self.muted.is_set() or not captured.valid(self.capture_epoch, self.clock(), self.settings.command_ttl):
                return False
            if not text.strip():
                return False
            text = text.strip()[:8000]
            self.last_heard = text
            if self.settings.preview_transcript:
                self.health.preview = text
                self.preview_token = uuid.uuid4().hex
                self.preview_capture = Captured(text, captured.epoch, captured.created)
                return True
            return self._enqueue(Command("command", text, captured.epoch, captured.created, voice=True))

    def confirm_preview(self, text: str, token: str) -> bool:
        with self.lock:
            capture = self.preview_capture
            if (not token or token != self.preview_token or not capture or self.muted.is_set()
                    or capture.epoch != self.capture_epoch or not text.strip()):
                return False
            # Explicit review is a new authorization; the old audio's TTL no longer applies.
            result = self._enqueue(Command("command", text.strip()[:8000], self.capture_epoch, self.clock(), voice=True))
            if result:
                self.discard_preview()
            return result

    def discard_preview(self) -> None:
        with self.lock:
            self.health.preview = ""
            self.preview_capture = None
            self.preview_token = ""

    def submit(self, text: str) -> bool:
        with self.lock:
            if not text.strip() or self.stopping.is_set():
                return False
            return self._enqueue(Command("command", text.strip()[:8000], self.capture_epoch, self.clock()))

    def select_model(self, model: str) -> bool:
        with self.lock:
            return self._enqueue(Command("model", model, self.capture_epoch, self.clock()))

    def select_effort(self, effort: str) -> bool:
        with self.lock:
            return self._enqueue(Command("effort", effort, self.capture_epoch, self.clock()))

    def supported_efforts(self, model: str | None = None) -> list[str]:
        selected = model or self.model
        entry = next((item for item in self.model_catalog if item.get("model") == selected), {})
        return [item["reasoningEffort"] for item in entry.get("supportedReasoningEfforts", [])
                if isinstance(item, dict) and item.get("reasoningEffort")]

    def _available_effort(self, model: str, preferred: str) -> str:
        allowed = self.supported_efforts(model)
        if preferred in allowed:
            return preferred
        entry = next((item for item in self.model_catalog if item.get("model") == model), {})
        return next((level for level in (entry.get("defaultReasoningEffort"), "medium", "low")
                     if level in allowed), allowed[0] if allowed else "")

    def _enqueue(self, command: Command) -> bool:
        try:
            self.commands.put_nowait(command)
            return True
        except queue.Full:
            self.health.error = "Command queue is full; nothing new was submitted."
            return False

    def _switch_model(self, model: str, effort: str | None = None) -> None:
        with self.lock:
            if model not in self.models:
                raise ValueError("Choose a model from your current Codex catalog")
            allowed = self.supported_efforts(model)
            if effort is not None and effort not in allowed:
                raise ValueError("Choose a reasoning effort supported by the selected model")
            selected_effort = effort if effort is not None else self._available_effort(model, self.effort)
            updated = replace(self.settings, model=model, effort=selected_effort)
            self.store.save(updated)
            self.settings = updated
            self.model = model
            self.effort = selected_effort
        self.say("Model selected for your next request.")

    def _switch_effort(self, effort: str) -> None:
        with self.lock:
            if effort not in self.supported_efforts():
                raise ValueError("Choose a reasoning effort supported by the selected model")
            updated = replace(self.settings, effort=effort)
            self.store.save(updated)
            self.settings = updated
            self.effort = effort
        self.say("Reasoning effort set to " + effort + " for your next request.")

    def _command_loop(self) -> None:
        while not self.stopping.is_set():
            try:
                command = self.commands.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                self._execute(command)
            except Exception as exc:
                with self.lock:
                    self.health.error = str(exc)[:2000]
                self.say("That request was not completed. Please check the conversation before retrying.")

    def _execute(self, command: Command) -> None:
        with self.lock:
            if (command.epoch != self.capture_epoch or self.clock() - command.created > self.settings.command_ttl
                    or (command.voice and self.muted.is_set()) or self.stopping.is_set()):
                return
            self.last_heard = command.value
        if command.kind == "model":
            self._switch_model(command.value)
            return
        if command.kind == "effort":
            self._switch_effort(command.value)
            return
        plain = command.value.lower().strip(" .!?")
        if plain in {"mute", "mute microphone", "stop listening", "go to sleep"}:
            if not self.muted.is_set():
                self.toggle_mute()
            self.say("Microphone muted.")
            return
        if plain in {"stop speaking", "quiet please"}:
            self.stop_speaking()
            return
        if plain in {"cancel task", "cancel the task"}:
            self.cancel_task()
            return
        if plain in {"what model", "current model", "what model are you using"}:
            self.say("The selected model is " + self.model)
            return
        if plain in {"list models", "show models", "what models are available"}:
            self.say("Available models: " + ", ".join(self.models))
            return
        choice = model_choice(command.value, self.models)
        if choice is not None:
            if not choice:
                raise ValueError("Please choose a model from the model menu")
            requested_effort = effort_choice(command.value, self.supported_efforts(choice))
            self._switch_model(choice, requested_effort)
            return
        effort = effort_choice(command.value, self.supported_efforts())
        if effort is not None:
            if not effort:
                raise ValueError("Please choose a reasoning effort supported by this model")
            self._switch_effort(effort)
            return
        with self.lock:
            if command.epoch != self.capture_epoch or (command.voice and self.muted.is_set()):
                return
            media = self.music if self.settings.media_enabled else None
        if media and media.handle(plain):
            return
        with self.lock:
            if command.epoch != self.capture_epoch or (command.voice and self.muted.is_set()):
                return
            if self.health.uncertain or self.health.cancelling or self.health.approvals:
                raise RuntimeError("Resolve the pending task or approval before sending another command")
            if not self.health.connected or self.client is None:
                raise RuntimeError("Codex is disconnected. This command was not sent")
            if self.health.active_turn and not self.health.owned_turn:
                raise RuntimeError("This conversation has a task from another client. Wait for it to finish")
            client = self.client
            active = self.health.active_turn
            self.health.error = ""
            self.health.submitting = True
            options = self.settings.turn_options()
            if self.model:
                options["model"] = self.model
            if self.effort in self.supported_efforts():
                options["effort"] = self.effort
            else:
                options.pop("effort", None)
        prompt = ("[Spoken or typed command via Jake Voice. Reply concisely for speech. "
                  "Give brief, factual progress updates for multi-step work. "
                  "Do not claim success before checking results. Voice is not identity verification.]\n" + command.value)
        params = {"threadId": self.settings.thread_id, "input": [{"type": "text", "text": prompt}]}
        method = "turn/steer" if active else "turn/start"
        if active:
            params["expectedTurnId"] = active
        else:
            params.update(options)
            params["clientUserMessageId"] = uuid.uuid4().hex
        started = self.clock()
        try:
            result = client.call(method, params, send_context=self.lock,
                                 check=lambda: command.epoch == self.capture_epoch
                                 and not self.stopping.is_set() and not self.health.cancelling
                                 and (not command.voice or not self.muted.is_set()))
            with self.lock:
                if active:
                    if result.get("turnId") != active:
                        raise RuntimeError("Unexpected steering acknowledgment")
                    self.health.submitting = False
                    self.say("I've passed on your update.", turn_id=active)
                else:
                    identifier = result.get("turn", {}).get("id")
                    if not identifier:
                        raise RuntimeError("Missing turn ID in acknowledgment")
                    self._accepted(identifier)
                    if result["turn"].get("status") in {"completed", "failed", "interrupted"}:
                        self._finish_turn(result["turn"])
                self.metrics.record("submission_acknowledgment", self.clock() - started)
        except RequestDiscarded:
            with self.lock:
                self.health.submitting = False
                if not self.health.active_turn:
                    self.health.cancelling = False
        except Exception:
            with self.lock:
                self.health.submitting = False
                self.health.uncertain = True
            raise

    def cancel_task(self) -> None:
        with self.lock:
            self._invalidate_capture()
            self.health.cancelling = bool(self.health.active_turn or self.health.submitting)
            self._control(("cancel",))
        self.stop_speaking()

    def resync(self) -> None:
        with self.lock:
            self._control(("resync",))

    def acknowledge_review(self) -> None:
        """On-screen action only, after the human checks the conversation."""
        with self.lock:
            if not self.health.active_turn and not self.health.submitting:
                self.health.uncertain = False
                self.health.cancelling = False
            self.health.error = ""

    def say(self, text: str, *, turn_id: str | None = None, progress: bool = False) -> None:
        cleaned = speakable(text)
        with self.lock:
            if cleaned and not self.stopping.is_set():
                self.speech.put(Speech(cleaned, self.speech_epoch, turn_id, progress, self.clock()))

    def stop_speaking(self) -> None:
        with self.lock:
            self.speech_epoch += 1
            self.output_cancel.set()
            self.speech.clear()
        if self.audio:
            self.audio.stop_output()

    def close(self) -> None:
        with self.lock:
            if self.stopping.is_set():
                return
            self.stopping.set()
            self._invalidate_capture()
            client = self.client
        self.stop_speaking()
        if self.audio:
            self.audio.close()
        if client:
            client.close()
        if self.music:
            self.music.close()
        deadline = time.monotonic() + 5
        for thread in self.threads:
            if thread is not threading.current_thread():
                thread.join(timeout=max(0, deadline - time.monotonic()))
