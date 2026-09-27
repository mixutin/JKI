"""Bounded synchronous JSON-RPC transport over a local Unix WebSocket."""
from __future__ import annotations

import json
from contextlib import nullcontext
import queue
import threading
from typing import Any, Callable


class RpcError(RuntimeError):
    pass


class RequestDiscarded(RuntimeError):
    """Local cancellation prevented transmission; no uncertain backend outcome."""


class CodexClient:
    def __init__(self, socket_path: str, callback: Callable[[dict[str, Any]], None], *, websocket: Any = None):
        if websocket is None:
            from websockets.sync.client import unix_connect
            websocket = unix_connect(socket_path, uri="ws://localhost/", open_timeout=10,
                                     close_timeout=2, max_size=1024 * 1024, max_queue=16)
        self.ws = websocket
        self.callback = callback
        self.pending: dict[int, queue.Queue] = {}
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.closed = threading.Event()
        self.seq = 0
        self.reader = threading.Thread(target=self._read, name="jki-rpc", daemon=True)
        self.reader.start()
        try:
            self.server_info = self.call("initialize", {
                "clientInfo": {"name": "jake_voice", "version": "0.2.0"},
                "capabilities": {"experimentalApi": True},
            })
            self._send({"method": "initialized", "params": {}})
        except Exception:
            self.close()
            raise

    def _send(self, obj: dict[str, Any]) -> None:
        with self.write_lock:
            if self.closed.is_set():
                raise RpcError("Codex connection is closed")
            self.ws.send(json.dumps(obj))

    def _read(self) -> None:
        try:
            for raw in self.ws:
                obj = json.loads(raw)
                if not isinstance(obj, dict):
                    raise RpcError("Invalid server message")
                if "id" in obj and "method" not in obj:
                    with self.lock:
                        waiter = self.pending.get(obj["id"])
                    if waiter:
                        try:
                            waiter.put_nowait(obj)
                        except queue.Full:
                            pass
                elif isinstance(obj.get("method"), str):
                    self.callback(obj)
        except Exception:
            # Never log backend payloads, transcripts, or credentials.
            pass
        finally:
            self.closed.set()
            with self.lock:
                for waiter in self.pending.values():
                    try:
                        waiter.put_nowait({"error": {"message": "Codex connection closed"}})
                    except queue.Full:
                        pass
            self.callback({"method": "jake/disconnected", "params": {}})

    def call(self, method: str, params: dict[str, Any], timeout: float = 20, *,
             send_context: Any = None, check: Callable[[], bool] | None = None) -> dict[str, Any]:
        waiter: queue.Queue = queue.Queue(maxsize=1)
        with self.lock:
            if self.closed.is_set():
                raise RpcError("Codex connection is closed")
            if len(self.pending) >= 32:
                raise RpcError("Too many pending backend requests")
            self.seq += 1
            number = self.seq
            self.pending[number] = waiter
        try:
            with send_context if send_context is not None else nullcontext():
                if check is not None and not check():
                    raise RequestDiscarded("Command invalidated before transmission")
                self._send({"id": number, "method": method, "params": params})
            try:
                obj = waiter.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError(f"Codex did not acknowledge {method}; outcome may be unknown") from None
            if "error" in obj:
                raise RpcError(str(obj["error"].get("message", "Backend error"))[:2000])
            if not isinstance(obj.get("result"), dict):
                raise RpcError("Invalid backend result")
            return obj["result"]
        finally:
            with self.lock:
                self.pending.pop(number, None)

    def respond(self, request_id: int | str, result: dict[str, Any]) -> None:
        self._send({"id": request_id, "result": result})

    def unsupported(self, request_id: int | str) -> None:
        self._send({"id": request_id, "error": {"code": -32601, "message": "Request not supported by JKI"}})

    def close(self) -> None:
        self.closed.set()
        self.ws.close()
        if threading.current_thread() is not self.reader:
            self.reader.join(timeout=3)
