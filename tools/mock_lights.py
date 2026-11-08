#!/usr/bin/env python3
"""Stateful simulated WiZ bulbs on loopback only, for the real wiz_butler.py manager.

Each bulb owns 127.0.0.N:<port> and answers the WiZ UDP JSON methods the manager
uses (getPilot, setPilot, setState, getSystemConfig, registration). A separate
socket on DISCOVERY_ADDRESS stands in for the LAN broadcast: the manager is run
with --broadcast DISCOVERY_ADDRESS, and every online bulb answers from its own
address, exactly like real discovery replies. Every socket binds to 127/8, so
nothing here can receive from or send to the LAN.

A small loopback HTTP control API exposes and changes simulated state:
  GET  /bulbs                 -> list of bulbs (mac, ip, room, online, registered, pilot, commands)
  POST /bulbs/<mac or room>   {"online": false} / {"pilot": {...}}  -> updated bulbs
"""

import argparse
import ipaddress
import json
import logging
import select
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

DISCOVERY_ADDRESS = "127.0.0.10"
FIRST_BULB_HOST = 11
DEFAULT_PORT = 48899
REGULAR = {"dimming": 100, "temp": 6500}
NIGHT = {"dimming": 20, "temp": 2700}
PILOT_KEYS = ("state", "sceneId", "temp", "dimming", "r", "g", "b", "w", "c", "speed")


def require_loopback(address):
    if not ipaddress.IPv4Address(address).is_loopback:
        raise ValueError(f"Mock bulbs are loopback-only; refusing {address}")
    return address


def parse_rooms(text):
    """'Living room=2,Bedroom=1' -> [("Living room", 2), ("Bedroom", 1)]."""
    rooms = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        name, _, count = part.rpartition("=")
        if not name.strip() or not count.isdigit() or int(count) < 1:
            raise ValueError(f"Expected Room=count, got {part!r}")
        rooms.append((name.strip(), int(count)))
    if not rooms:
        raise ValueError("At least one room is required")
    return rooms


def layout(rooms=(("Living room", 2), ("Bedroom", 1)), new=1, offline=("Bedroom",)):
    """Build simulated bulbs. `offline` matches a room name or MAC; `new` bulbs are unregistered."""
    bulbs, offline = [], set(offline)
    for room, count in [*rooms, *([(None, new)] if new else [])]:
        for _ in range(count):
            n = len(bulbs) + 1
            if FIRST_BULB_HOST + n - 1 > 250:
                raise ValueError("Too many simulated bulbs")
            mac = f"a0b1c2{n:06x}"
            bulbs.append({"mac": mac, "ip": f"127.0.0.{FIRST_BULB_HOST + n - 1}", "room": room,
                          "registered": room is not None,
                          "online": room not in offline and mac not in offline,
                          "pilot": {"mac": mac, "rssi": -55, "state": True, "sceneId": 0, **NIGHT},
                          "system": {"mac": mac, "moduleName": "MOCK_SHRGBC_01", "fwVersion": "9.9.9-mock",
                                     "homeId": 1, "roomId": n},
                          "commands": []})
    return bulbs


def manager_state(bulbs, enabled=False):
    """Seed state for wiz_butler.py --state: only registered bulbs, at loopback IPs."""
    return {"schemaVersion": 2, "holds": {}, "intents": {},
            "config": {"enabled": enabled, "night": "21:00", "morning": "06:00",
                       "timezone": "Asia/Jerusalem", "pollSeconds": 1,
                       "bulbs": [{"mac": b["mac"], "ip": b["ip"], "room": b["room"]}
                                 for b in bulbs if b["registered"]]}}


class Simulator:
    def __init__(self, bulbs, port=DEFAULT_PORT, discovery=DISCOVERY_ADDRESS):
        self.bulbs = {b["mac"]: b for b in bulbs}
        self.port, self.discovery = port, require_loopback(discovery)
        self.lock = threading.Lock()
        self.sockets = {}
        self.stop = threading.Event()
        self.thread = None

    # ---- protocol (pure, unit-tested) ----
    def handle(self, mac, packet):
        """Return the reply dict for one request to `mac`, or None when it stays silent."""
        with self.lock:
            bulb = self.bulbs[mac]
            if not bulb["online"]:
                return None
            try:
                request = json.loads(packet)
            except ValueError:
                return None
            if not isinstance(request, dict) or not isinstance(request.get("method"), str):
                return None
            method, params = request["method"], request.get("params") or {}
            reply = {"method": method, "env": "pro"}
            if "id" in request:
                reply["id"] = request["id"]
            if method == "getPilot":
                reply["result"] = dict(bulb["pilot"])
            elif method == "getSystemConfig":
                reply["result"] = dict(bulb["system"])
            elif method == "registration":
                reply["result"] = {"mac": mac, "success": True}
            elif method in ("setPilot", "setState") and isinstance(params, dict):
                bulb["commands"].append({"method": method, "params": dict(params)})
                del bulb["commands"][:-50]
                self.apply(bulb["pilot"], params)
                reply["result"] = {"success": True}
            else:
                reply["error"] = {"code": -32601, "message": "Method not found"}
            return reply

    @staticmethod
    def apply(pilot, params):
        changes = {k: v for k, v in params.items() if k in PILOT_KEYS}
        # Matches observed ESP24 firmware: any preset write turns an off bulb on.
        if "state" not in changes and changes:
            changes["state"] = True
        if "temp" in changes:
            changes["sceneId"] = 0
            for key in ("r", "g", "b", "w", "c"):
                pilot.pop(key, None)
        pilot.update(changes)

    # ---- control API ----
    def snapshot(self):
        with self.lock:
            return [json.loads(json.dumps(b)) for b in self.bulbs.values()]

    def update(self, target, change):
        with self.lock:
            matched = [b for b in self.bulbs.values() if target in (b["mac"], b["room"])]
            if not matched:
                raise KeyError(target)
            for bulb in matched:
                if "online" in change:
                    bulb["online"] = bool(change["online"])
                if isinstance(change.get("pilot"), dict):
                    bulb["pilot"].update({k: v for k, v in change["pilot"].items() if k in PILOT_KEYS})
        return self.snapshot()

    # ---- sockets ----
    def start(self):
        if self.port == 0:  # Tests: let the kernel choose, then share it across addresses.
            probe = self.bind(self.discovery)
            self.port = probe.getsockname()[1]
            self.sockets[probe] = None
        else:
            self.sockets[self.bind(self.discovery)] = None
        for mac, bulb in self.bulbs.items():
            self.sockets[self.bind(bulb["ip"])] = mac
        self.thread = threading.Thread(target=self.serve, name="mock-bulbs", daemon=True)
        self.thread.start()

    def bind(self, address):
        require_loopback(address)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((address, self.port))
        except OSError:
            sock.close()
            raise
        return sock

    def serve(self):
        by_mac = {mac: sock for sock, mac in self.sockets.items() if mac}
        while not self.stop.is_set():
            ready, _, _ = select.select(list(self.sockets), [], [], 0.2)
            for sock in ready:
                try:
                    data, source = sock.recvfrom(8192)
                except OSError:
                    continue
                if not ipaddress.IPv4Address(source[0]).is_loopback:
                    continue
                mac = self.sockets[sock]
                # Discovery: every online bulb answers from its own address.
                targets = [mac] if mac else list(self.bulbs)
                for target in targets:
                    reply = self.handle(target, data)
                    if reply is not None:
                        by_mac[target].sendto(json.dumps(reply).encode(), source)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        for sock in self.sockets:
            sock.close()


def control_handler(simulator):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, code, value):
            body = json.dumps(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/bulbs":
                self.respond(200, simulator.snapshot())
            else:
                self.respond(404, {"error": "Not found"})

        def do_POST(self):
            if not self.path.startswith("/bulbs/"):
                self.respond(404, {"error": "Not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                change = json.loads(self.rfile.read(length) or b"{}")
                self.respond(200, simulator.update(unquote(self.path[len("/bulbs/"):]), change))
            except KeyError:
                self.respond(404, {"error": "No such bulb or room"})
            except (ValueError, TypeError) as error:
                self.respond(400, {"error": str(error)})

        def log_message(self, *_args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--layout", required=True, help="JSON file from layout()")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="UDP port on every simulated bulb address")
    parser.add_argument("--control-port", type=int, required=True, help="Loopback HTTP control API port")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with open(args.layout) as handle:
        simulator = Simulator(json.load(handle), args.port)
    simulator.start()
    server = ThreadingHTTPServer(("127.0.0.1", args.control_port), control_handler(simulator))
    logging.info("%d mock bulbs on 127.0.0.x:%d; control http://127.0.0.1:%d/bulbs",
                 len(simulator.bulbs), args.port, args.control_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        simulator.close()


if __name__ == "__main__":
    main()
