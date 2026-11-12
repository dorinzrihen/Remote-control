#!/usr/bin/env python3
"""Stateful simulated LG webOS TV on loopback only, for driving UniRemote Preview.

Speaks enough of the SSAP WebSocket protocol (ws://HOST:3000) for the app's
WebOsClient: hello, register (auto-accept or a simulated on-screen PROMPT), the
requests and subscriptions it sends on connect, audio volume/mute (with pushed
audio/getStatus updates), power off, app launch, media keys, toasts, and the
pointer input socket (/pointer: button presses). Every command is logged.

The server binds 127.0.0.1 only (the emulator reaches it as 10.0.2.2) and
ignores non-loopback peers, so it can never talk to the LAN or a real TV.

Plain HTTP on the same port exposes and changes the simulated state:
  GET  /state                    -> {"power", "volume", "muted", "foregroundApp", "commands": [...], ...}
  POST /state  {"volume": 20, "muted": false, "power": true}   -> updated state
  POST /reset-log                -> clears the command log
"""

import argparse
import base64
import hashlib
import ipaddress
import json
import logging
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 3000
CLIENT_KEY = "mock-client-key-0001"
FAKE_MAC = "02:00:00:00:4c:47"  # locally administered: no real device owns it
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
LOG_LIMIT = 500

INPUTS = [
    {"id": "HDMI_1", "label": "HDMI 1", "appId": "com.webos.app.hdmi1"},
    {"id": "HDMI_2", "label": "Xiaomi", "appId": "com.webos.app.hdmi2"},
    {"id": "HDMI_3", "label": "HDMI 3", "appId": "com.webos.app.hdmi3"},
]
APPS = [
    {"id": "netflix", "title": "Netflix"},
    {"id": "youtube.leanback.v4", "title": "YouTube"},
    {"id": "io.strem.tv", "title": "Stremio"},
    {"id": "com.webos.app.browser", "title": "Web Browser"},
]


def require_loopback(address):
    if not ipaddress.ip_address(address).is_loopback:
        raise ValueError(f"Mock TV is loopback-only; refusing {address}")
    return address


# ---------------------------------------------------------------- WebSocket framing (RFC 6455)

def accept_key(key):
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


def encode_frame(payload, opcode=0x1, mask=None):
    """One unfragmented frame. Servers send unmasked frames; clients pass a 4-byte mask."""
    if isinstance(payload, str):
        payload = payload.encode()
    head = bytes([0x80 | opcode])
    mask_bit = 0x80 if mask else 0
    n = len(payload)
    if n < 126:
        head += bytes([mask_bit | n])
    elif n < 1 << 16:
        head += bytes([mask_bit | 126]) + struct.pack("!H", n)
    else:
        head += bytes([mask_bit | 127]) + struct.pack("!Q", n)
    if mask:
        head += mask
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return head + payload


def read_exact(stream, n):
    data = b""
    while len(data) < n:
        chunk = stream.read(n - len(data))
        if not chunk:
            raise ConnectionError("socket closed")
        data += chunk
    return data


def read_frame(stream):
    """-> (fin, opcode, payload) with the client mask removed."""
    b1, b2 = read_exact(stream, 2)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack("!H", read_exact(stream, 2))[0]
    elif n == 127:
        n = struct.unpack("!Q", read_exact(stream, 8))[0]
    mask = read_exact(stream, 4) if b2 & 0x80 else None
    payload = read_exact(stream, n)
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return bool(b1 & 0x80), b1 & 0x0F, payload


def parse_pointer(text):
    """'type:button\\nname:UP\\n\\n' -> {"type": "button", "name": "UP"}."""
    return dict(line.split(":", 1) for line in text.strip().splitlines() if ":" in line)


# ---------------------------------------------------------------- simulated TV

class Connection:
    def __init__(self, handler, kind):
        self.handler, self.kind = handler, kind
        self.lock = threading.Lock()
        self.registered = False
        self.open = True

    def send(self, message):
        data = encode_frame(json.dumps(message) if isinstance(message, dict) else message)
        with self.lock:
            if not self.open:
                return
            try:
                self.handler.wfile.write(data)
                self.handler.wfile.flush()
            except OSError:
                self.open = False

    def close(self):
        with self.lock:
            if self.open:
                try:
                    self.handler.wfile.write(encode_frame(struct.pack("!H", 1000), opcode=0x8))
                    self.handler.wfile.flush()
                except OSError:
                    pass
            self.open = False
        try:
            self.handler.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class MockTv:
    def __init__(self, volume=12, muted=False, power=True, pairing="auto", prompt_seconds=2.0, model="MOCK-OLED55"):
        self.lock = threading.RLock()
        self.volume, self.muted, self.power = volume, muted, power
        self.pairing, self.prompt_seconds, self.model = pairing, prompt_seconds, model
        self.foreground = "com.webos.app.livetv"
        self.commands = []
        self.connections = []
        self.audio_subs = []  # (connection, id)
        self.app_subs = []

    # ---- state

    def snapshot(self):
        with self.lock:
            return {"power": self.power, "volume": self.volume, "muted": self.muted,
                    "foregroundApp": self.foreground, "model": self.model,
                    "clients": sum(c.registered and c.open for c in self.connections if c.kind == "ssap"),
                    "commands": list(self.commands)}

    def log(self, source, name, payload=None):
        with self.lock:
            entry = {"t": round(time.time(), 3), "source": source, "command": name}
            if payload:
                entry["payload"] = payload
            self.commands.append(entry)
            del self.commands[:-LOG_LIMIT]
        logging.info("%s %s %s", source, name, json.dumps(payload) if payload else "")

    def audio_status(self):
        return {"returnValue": True, "scenario": "mastervolume_tv_speaker", "volume": self.volume,
                "mute": self.muted, "volumeMax": 100, "action": "changed"}

    def push_audio(self):
        status = self.audio_status()
        for conn, sub_id in list(self.audio_subs):
            conn.send({"type": "response", "id": sub_id, "payload": {**status, "subscribed": True}})

    def push_app(self):
        for conn, sub_id in list(self.app_subs):
            conn.send({"type": "response", "id": sub_id,
                       "payload": {"returnValue": True, "appId": self.foreground, "subscribed": True}})

    def update(self, change):
        """Control API (simulated physical remote / Wake-on-LAN)."""
        with self.lock:
            if "volume" in change:
                self.volume = max(0, min(100, int(change["volume"])))
            if "muted" in change:
                self.muted = bool(change["muted"])
            if "power" in change:
                self.power = bool(change["power"])
                if not self.power:
                    self.drop_all()
            self.log("control", "update", change)
            self.push_audio()
        return self.snapshot()

    def drop_all(self):
        with self.lock:
            for conn in list(self.connections):
                conn.close()
            self.audio_subs.clear()
            self.app_subs.clear()

    def forget(self, conn):
        with self.lock:
            if conn in self.connections:
                self.connections.remove(conn)
            self.audio_subs[:] = [s for s in self.audio_subs if s[0] is not conn]
            self.app_subs[:] = [s for s in self.app_subs if s[0] is not conn]

    # ---- SSAP

    def handle(self, conn, text, host):
        try:
            msg = json.loads(text)
        except ValueError:
            return
        kind, msg_id, uri = msg.get("type"), msg.get("id"), msg.get("uri", "")
        payload = msg.get("payload") or {}
        if kind == "hello":
            conn.send({"type": "hello", "id": msg_id, "payload": {
                "protocolVersion": 1, "deviceType": "tv", "deviceOS": "webOS", "deviceOSVersion": "mock",
                "deviceUUID": "mock-tv", "pairingTypes": ["PROMPT"]}})
        elif kind == "register":
            self.register(conn, msg_id, payload)
        elif kind in ("request", "subscribe"):
            if not conn.registered:
                conn.send({"type": "error", "id": msg_id, "error": "401 insufficient permissions (not registered)", "payload": {}})
                return
            with self.lock:
                result = self.request(conn, kind, msg_id, uri.removeprefix("ssap://"), payload, host)
            if result is None:
                conn.send({"type": "error", "id": msg_id, "error": "404 no such service or method", "payload": {}})
            elif result is not False:
                conn.send({"type": "response", "id": msg_id, "payload": result})

    def register(self, conn, msg_id, payload):
        known = payload.get("client-key") == CLIENT_KEY
        self.log("ssap", "register", {"knownKey": known})

        def accept():
            conn.registered = True
            conn.send({"type": "registered", "id": msg_id, "payload": {"client-key": CLIENT_KEY}})

        if known or self.pairing == "auto":
            accept()
        else:
            conn.send({"type": "response", "id": msg_id, "payload": {"pairingType": "PROMPT", "returnValue": True}})
            threading.Timer(self.prompt_seconds, accept).start()

    def request(self, conn, kind, msg_id, uri, p, host):
        """Returns a payload dict, False when the reply was already sent/none is due, or None (unknown)."""
        ok = {"returnValue": True}
        if kind == "subscribe" and uri == "audio/getStatus":
            self.audio_subs.append((conn, msg_id))
            return {**self.audio_status(), "subscribed": True}
        if kind == "subscribe" and uri == "com.webos.applicationManager/getForegroundAppInfo":
            self.app_subs.append((conn, msg_id))
            return {"returnValue": True, "appId": self.foreground, "subscribed": True}
        if uri == "com.webos.service.ime/registerRemoteKeyboard":
            return False  # the TV only answers when a text field gains focus
        if uri == "system/getSystemInfo":
            return {**ok, "modelName": self.model, "features": {"3d": False, "dvr": False}}
        if uri == "com.webos.service.connectionmanager/getinfo":
            return {**ok, "wiredInfo": {"macAddress": FAKE_MAC}, "wifiInfo": {}}
        if uri == "tv/getExternalInputList":
            return {**ok, "devices": INPUTS}
        if uri == "com.webos.applicationManager/listLaunchPoints":
            return {**ok, "launchPoints": APPS}
        if uri == "com.webos.service.networkinput/getPointerInputSocket":
            return {**ok, "socketPath": f"ws://{host}/pointer"}
        if uri in ("audio/getStatus", "audio/getVolume"):
            return self.audio_status()
        if uri == "settings/getSystemSettings":
            values = {"backlight": "80", "brightness": "50", "pictureMode": "cinema",
                      "soundMode": "standard", "soundOutput": "tv_speaker"}
            return {**ok, "category": p.get("category"),
                    "settings": {k: values[k] for k in p.get("keys", []) if k in values}}
        # ---- commands (logged)
        self.log("ssap", uri, {k: v for k, v in p.items() if k != "subscribe"} or None)
        if uri == "audio/volumeUp":
            self.volume, self.muted = min(100, self.volume + 1), False
        elif uri == "audio/volumeDown":
            self.volume = max(0, self.volume - 1)
        elif uri == "audio/setVolume":
            self.volume = max(0, min(100, int(p.get("volume", self.volume))))
        elif uri == "audio/setMute":
            self.muted = bool(p.get("mute"))
        elif uri == "system/turnOff":
            self.power = False
            conn.send({"type": "response", "id": msg_id, "payload": ok})
            threading.Timer(0.3, self.drop_all).start()
            return False
        elif uri == "system.launcher/launch":
            self.foreground = p.get("id", self.foreground)
            self.push_app()
            return {**ok, "id": self.foreground}
        elif uri == "system.launcher/open":
            self.foreground = "com.webos.app.browser"
            self.push_app()
        elif uri == "tv/switchInput":
            self.foreground = next((i["appId"] for i in INPUTS if i["id"] == p.get("inputId")), self.foreground)
            self.push_app()
        elif uri == "system.notifications/createAlert":
            return {**ok, "alertId": "mock-alert-1"}
        elif uri.startswith(("media.controls/", "system.notifications/", "com.webos.service.tvpower/",
                             "com.webos.service.ime/", "com.webos.service.apiadapter/")):
            pass
        else:
            return None
        if uri.startswith("audio/"):
            self.push_audio()
        return ok


# ---------------------------------------------------------------- HTTP + WebSocket server

def make_handler(tv):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            logging.debug(fmt, *args)

        def peer_ok(self):
            if ipaddress.ip_address(self.client_address[0]).is_loopback:
                return True
            self.close_connection = True
            return False

        def reply(self, status, body):
            data = json.dumps(body, indent=2).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.peer_ok():
                return
            if self.headers.get("Upgrade", "").lower() == "websocket":
                return self.websocket()
            if self.path == "/state":
                return self.reply(200, tv.snapshot())
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            if not self.peer_ok():
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/state":
                return self.reply(200, tv.update(body))
            if self.path == "/reset-log":
                with tv.lock:
                    tv.commands.clear()
                return self.reply(200, tv.snapshot())
            self.reply(404, {"error": "not found"})

        def websocket(self):
            kind = "pointer" if self.path.startswith("/pointer") else "ssap"
            if not tv.power:
                self.reply(503, {"error": "TV is off"})
                self.close_connection = True
                return
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept_key(self.headers["Sec-WebSocket-Key"]))
            self.end_headers()
            self.wfile.flush()
            conn = Connection(self, kind)
            with tv.lock:
                tv.connections.append(conn)
            host = self.headers.get("Host", f"127.0.0.1:{self.server.server_address[1]}")
            buffer, buffer_op = b"", 0x1
            try:
                while conn.open:
                    fin, opcode, payload = read_frame(self.rfile)
                    if opcode == 0x8:
                        conn.close()
                        break
                    if opcode == 0x9:
                        with conn.lock:
                            self.wfile.write(encode_frame(payload, opcode=0xA))
                            self.wfile.flush()
                        continue
                    if opcode in (0x1, 0x2):
                        buffer, buffer_op = payload, opcode
                    elif opcode == 0x0:
                        buffer += payload
                    else:
                        continue
                    if not fin:
                        continue
                    text = buffer.decode(errors="replace")
                    if kind == "pointer":
                        event = parse_pointer(text)
                        tv.log("pointer", event.get("type", "?"), event)
                    else:
                        tv.handle(conn, text, host)
            except (ConnectionError, OSError):
                pass
            finally:
                conn.open = False
                tv.forget(conn)
                self.close_connection = True

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(tv, host="127.0.0.1", port=DEFAULT_PORT):
    require_loopback(host)
    server = Server((host, port), make_handler(tv))
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--listen", default="127.0.0.1", help="Loopback address only (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="SSAP + control port (the app always uses 3000)")
    parser.add_argument("--volume", type=int, default=12)
    parser.add_argument("--muted", action="store_true")
    parser.add_argument("--off", action="store_true", help="Start powered off (refuses connections)")
    parser.add_argument("--pairing", choices=("auto", "prompt"), default="auto",
                        help="prompt: simulate the TV's Yes/No prompt, accepted after --prompt-seconds")
    parser.add_argument("--prompt-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    tv = MockTv(volume=args.volume, muted=args.muted, power=not args.off,
                pairing=args.pairing, prompt_seconds=args.prompt_seconds)
    server = serve(tv, args.listen, args.port)
    logging.info("Mock LG TV on ws://%s:%d (state: http://%s:%d/state)", args.listen, args.port, args.listen, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
