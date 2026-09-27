from contextlib import nullcontext
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest

from jki.protocol import CodexClient, RequestDiscarded, RpcError
from tests.helpers import wait_for


class FakeSocket:
    def __init__(self):
        self.incoming = queue.Queue()
        self.sent = []
        self.is_closed = False

    def send(self, raw):
        obj = json.loads(raw)
        self.sent.append(obj)
        if obj.get("method") == "initialize":
            self.incoming.put(json.dumps({"id": obj["id"], "result": {"userAgent": "fixture"}}))
        elif obj.get("method") == "echo":
            self.incoming.put(json.dumps({"id": obj["id"], "result": obj["params"]}))
        elif obj.get("method") == "reject":
            self.incoming.put(json.dumps({"id": obj["id"], "error": {"message": "rejected"}}))

    def __iter__(self):
        while True:
            raw = self.incoming.get()
            if raw is None:
                return
            yield raw

    def close(self):
        if not self.is_closed:
            self.is_closed = True
            self.incoming.put(None)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.socket = FakeSocket()
        self.events = []
        self.client = CodexClient("unused", self.events.append, websocket=self.socket)
        self.addCleanup(self.client.close)

    def test_initialization_order(self):
        self.assertEqual([x["method"] for x in self.socket.sent[:2]], ["initialize", "initialized"])

    def test_concurrent_requests_are_correlated(self):
        results = []
        threads = [threading.Thread(target=lambda n=i: results.append(self.client.call("echo", {"n": n}))) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(x["n"] for x in results), list(range(8)))
        self.assertEqual(self.client.pending, {})

    def test_rpc_errors_are_reported(self):
        with self.assertRaisesRegex(RpcError, "rejected"):
            self.client.call("reject", {})

    def test_request_timeout_removes_waiter(self):
        with self.assertRaises(TimeoutError):
            self.client.call("hang", {}, timeout=.01)
        self.assertEqual(self.client.pending, {})

    def test_cancelled_preflight_does_not_send(self):
        with self.assertRaises(RequestDiscarded):
            self.client.call("echo", {}, send_context=nullcontext(), check=lambda: False)
        self.assertEqual(len(self.socket.sent), 2)
        self.assertEqual(self.client.pending, {})

    def test_disconnect_unblocks_waiters(self):
        errors = []
        def request():
            try:
                self.client.call("hang", {})
            except RpcError as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=request)
        thread.start()
        wait_for(lambda: bool(self.client.pending))
        self.socket.close()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors)

    def test_server_requests_can_be_answered(self):
        self.socket.incoming.put(json.dumps({"id": "approval", "method": "item/fileChange/requestApproval", "params": {}}))
        wait_for(lambda: bool(self.events))
        self.client.respond("approval", {"decision": "decline"})
        self.assertEqual(self.socket.sent[-1], {"id": "approval", "result": {"decision": "decline"}})

    def test_invalid_json_closes_connection(self):
        self.socket.incoming.put("not json")
        self.assertTrue(self.client.closed.wait(1))

    def test_closed_client_rejects_new_calls(self):
        self.client.close()
        with self.assertRaises(RpcError):
            self.client.call("echo", {})


class UnixTransportTests(unittest.TestCase):
    def test_real_websocket_transport_with_local_fake_server(self):
        from websockets.sync.server import unix_serve
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "fixture.sock")
            def handler(websocket):
                for raw in websocket:
                    obj = json.loads(raw)
                    if "id" in obj:
                        websocket.send(json.dumps({"id": obj["id"], "result": obj.get("params", {})}))
            server = unix_serve(handler, path=path, open_timeout=2)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            client = None
            try:
                client = CodexClient(path, lambda event: None)
                self.assertEqual(client.call("fixture/echo", {"value": 7}), {"value": 7})
            finally:
                if client:
                    client.close()
                server.shutdown()
                thread.join(2)
            self.assertFalse(thread.is_alive())
