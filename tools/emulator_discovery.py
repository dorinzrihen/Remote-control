#!/usr/bin/env python3
"""Loopback-only, read-only SSDP bridge for the development emulator's NAT network."""
import argparse
import json
from pathlib import Path
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

ST = {
    "lg": "urn:lge-com:service:webos-second-screen:1",
    "samsung": "urn:samsung.com:device:RemoteControlReceiver:1",
}
DEVICE_PORT = 18765
IDENTITY = "uniremote-ssdp-dev-v1"


def parse_response(kind, ip, text):
    if not text.upper().startswith("HTTP/1.1 200"):
        return None
    headers = {line.split(":", 1)[0].strip().lower(): line.split(":", 1)[1].strip()
               for line in text.splitlines() if ":" in line}
    if headers.get("st", "").lower() != ST[kind].lower():
        return None
    if kind == "lg" and not any(word in text.lower() for word in ("webos", "lge")):
        return None
    if kind == "samsung" and "samsung" not in text.lower():
        return None
    return {"ip": ip, "name": (headers.get("server", "LG webOS TV")[:40]
                               if kind == "lg" else "Samsung TV")}


def discover(kind, timeout=3):
    """Only standard M-SEARCH discovery; never connect, pair or send remote commands."""
    message = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
               f'MAN: "ssdp:discover"\r\nMX: 2\r\nST: {ST[kind]}\r\n\r\n').encode()
    devices = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.25)
        for _ in range(2):
            sock.sendto(message, ("239.255.255.250", 1900))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, address = sock.recvfrom(8192)
            except socket.timeout:
                continue
            device = parse_response(kind, address[0], data.decode(errors="replace"))
            if device:
                devices[device["ip"]] = device
    return list(devices.values())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self.respond(200, {"service": IDENTITY})
        elif self.path in ("/discover/lg", "/discover/samsung"):
            try:
                self.respond(200, {"devices": discover(self.path.rsplit("/", 1)[1])})
            except OSError as exc:
                self.respond(503, {"error": str(exc)})
        else:
            self.respond(404, {"error": "Unknown discovery type"})

    def do_POST(self):
        if self.path != "/stop/" + self.server.stop_key:
            self.respond(404, {})
            return
        self.respond(200, {})
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def read_state(path):
    try:
        state = json.loads(path.read_text())
        if not (isinstance(state["port"], int) and 1024 <= state["port"] <= 65535):
            return None
        if not (isinstance(state["key"], str) and len(state["key"]) == 64):
            return None
        with urlopen(f'http://127.0.0.1:{state["port"]}/health', timeout=1) as response:
            return state if json.load(response).get("service") == IDENTITY else None
    except (OSError, ValueError, KeyError):
        return None


def stop_bridge(path):
    state = read_state(path)
    if state:
        urlopen(Request(f'http://127.0.0.1:{state["port"]}/stop/{state["key"]}',
                        method="POST"), timeout=2).close()
        deadline = time.monotonic() + 5
        while read_state(path) and time.monotonic() < deadline:
            time.sleep(0.1)
        if read_state(path):
            raise OSError("Host TV discovery bridge did not stop in 5s")
    path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    path = parser.parse_args().state
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.stop_key = secrets.token_hex(32)
    state = {"port": server.server_port, "key": server.stop_key}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.replace(path)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
