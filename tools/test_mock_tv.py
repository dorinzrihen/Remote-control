import base64
import json
import os
import socket
import threading
import unittest
from urllib.request import Request, urlopen

import mock_tv


class Client:
    """Minimal masked WebSocket client, enough to act like WebOsClient."""

    def __init__(self, port, path="/"):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        self.stream = self.sock.makefile("rb")
        status = self.stream.readline()
        if b" 101 " not in status:
            self.close()
            raise ConnectionError(status)
        headers = {}
        while (line := self.stream.readline().strip()):
            name, _, value = line.decode().partition(":")
            headers[name.lower()] = value.strip()
        assert headers["sec-websocket-accept"] == mock_tv.accept_key(key)

    def send(self, message):
        text = json.dumps(message) if isinstance(message, dict) else message
        self.sock.sendall(mock_tv.encode_frame(text, mask=os.urandom(4)))

    def recv(self):
        _fin, opcode, payload = mock_tv.read_frame(self.stream)
        return opcode, payload

    def json(self):
        while True:
            opcode, payload = self.recv()
            if opcode == 0x1:
                return json.loads(payload)

    def until(self, msg_id):
        while True:
            message = self.json()
            if message.get("id") == msg_id:
                return message

    def close(self):
        self.stream.close()
        self.sock.close()


class MockTvTest(unittest.TestCase):
    def setUp(self):
        self.tv = mock_tv.MockTv(volume=10)
        self.server = mock_tv.serve(self.tv, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def registered(self, key=None):
        client = Client(self.port)
        payload = {"pairingType": "PROMPT", "manifest": {}}
        if key:
            payload["client-key"] = key
        client.send({"type": "register", "id": "register_0", "payload": payload})
        message = client.until("register_0")
        self.assertEqual(message["type"], "registered")
        self.assertEqual(message["payload"]["client-key"], mock_tv.CLIENT_KEY)
        return client

    def state(self):
        with urlopen(f"http://127.0.0.1:{self.port}/state", timeout=5) as response:
            return json.load(response)

    def test_frames_round_trip_with_mask_and_long_payloads(self):
        import io
        for size in (5, 300, 70000):
            data = b"x" * size
            fin, opcode, payload = mock_tv.read_frame(io.BytesIO(mock_tv.encode_frame(data, opcode=2, mask=b"abcd")))
            self.assertEqual((fin, opcode, payload), (True, 2, data))

    def test_rejects_non_loopback_listen(self):
        with self.assertRaises(ValueError):
            mock_tv.serve(self.tv, "0.0.0.0", 0)
        with self.assertRaises(ValueError):
            mock_tv.require_loopback("192.168.1.20")

    def test_requests_need_registration(self):
        client = Client(self.port)
        client.send({"type": "request", "id": "r1", "uri": "ssap://audio/volumeUp", "payload": {}})
        self.assertEqual(client.until("r1")["type"], "error")
        self.assertEqual(self.state()["volume"], 10)
        client.close()

    def test_volume_commands_change_state_and_push_to_subscribers(self):
        client = self.registered()
        client.send({"type": "subscribe", "id": "sub_1", "uri": "ssap://audio/getStatus", "payload": {"subscribe": True}})
        self.assertEqual(client.until("sub_1")["payload"]["volume"], 10)
        client.send({"type": "request", "id": "r1", "uri": "ssap://audio/volumeUp", "payload": {}})
        pushed = client.until("sub_1")["payload"]
        self.assertEqual((pushed["volume"], pushed["mute"]), (11, False))
        client.send({"type": "request", "id": "r2", "uri": "ssap://audio/setMute", "payload": {"mute": True}})
        self.assertTrue(client.until("sub_1")["payload"]["mute"])
        client.send({"type": "request", "id": "r3", "uri": "ssap://audio/setVolume", "payload": {"volume": 150}})
        self.assertEqual(client.until("sub_1")["payload"]["volume"], 100)
        state = self.state()
        self.assertEqual((state["volume"], state["muted"]), (100, True))
        self.assertEqual([c["command"] for c in state["commands"] if c["source"] == "ssap"][-3:],
                         ["audio/volumeUp", "audio/setMute", "audio/setVolume"])
        client.close()

    def test_control_api_pushes_changes(self):
        client = self.registered(mock_tv.CLIENT_KEY)
        client.send({"type": "subscribe", "id": "sub_1", "uri": "ssap://audio/getStatus", "payload": {"subscribe": True}})
        client.until("sub_1")
        request = Request(f"http://127.0.0.1:{self.port}/state", data=json.dumps({"volume": 33}).encode(), method="POST")
        urlopen(request, timeout=5).close()
        self.assertEqual(client.until("sub_1")["payload"]["volume"], 33)
        client.close()

    def test_pointer_socket_logs_buttons(self):
        client = self.registered()
        client.send({"type": "request", "id": "p", "uri": "ssap://com.webos.service.networkinput/getPointerInputSocket", "payload": {}})
        path = client.until("p")["payload"]["socketPath"]
        self.assertEqual(path, f"ws://127.0.0.1:{self.port}/pointer")
        pointer = Client(self.port, "/pointer")
        pointer.send("type:button\nname:UP\n\n")
        client.send({"type": "request", "id": "sync", "uri": "ssap://audio/getVolume", "payload": {}})
        client.until("sync")
        for _ in range(50):
            if any(c["source"] == "pointer" for c in self.state()["commands"]):
                break
            threading.Event().wait(0.05)
        self.assertIn({"type": "button", "name": "UP"}, [c.get("payload") for c in self.state()["commands"]])
        pointer.close()
        client.close()

    def test_power_off_drops_and_refuses_connections(self):
        client = self.registered()
        client.send({"type": "request", "id": "off", "uri": "ssap://system/turnOff", "payload": {}})
        self.assertEqual(client.until("off")["type"], "response")
        opcode, _ = client.recv()
        self.assertEqual(opcode, 0x8)
        self.assertFalse(self.state()["power"])
        client.close()
        with self.assertRaises(ConnectionError):
            Client(self.port)

    def test_prompt_pairing_sends_prompt_then_registers(self):
        self.tv.pairing, self.tv.prompt_seconds = "prompt", 0.1
        client = Client(self.port)
        client.send({"type": "register", "id": "register_0", "payload": {}})
        first = client.until("register_0")
        self.assertEqual(first["payload"]["pairingType"], "PROMPT")
        self.assertEqual(client.until("register_0")["type"], "registered")
        client.close()

    def test_parse_pointer(self):
        self.assertEqual(mock_tv.parse_pointer("type:move\ndx:3\ndy:-2\ndown:0\n\n"),
                         {"type": "move", "dx": "3", "dy": "-2", "down": "0"})


if __name__ == "__main__":
    unittest.main()
