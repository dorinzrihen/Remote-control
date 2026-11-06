#!/usr/bin/env python3
"""Authoritative LAN WiZ manager. Python 3.11+, standard library only."""

import argparse
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import signal
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

from bonjour import Bonjour

MODES = {"REGULAR": {"dimming": 100, "temp": 6500}, "NIGHT": {"dimming": 20, "temp": 2700}}
DEFAULT_CONFIG = {"enabled": False, "night": "21:00", "morning": "06:00", "timezone": "Asia/Jerusalem", "pollSeconds": 1, "bulbs": []}


def validate_config(value):
    if not isinstance(value, dict) or type(value.get("enabled")) is not bool:
        raise ValueError("enabled must be a boolean")
    for key in ("night", "morning"):
        if not isinstance(value.get(key), str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value[key]):
            raise ValueError(f"{key} must be HH:MM")
    if value["night"] == value["morning"]:
        raise ValueError("Night and morning must differ")
    poll_seconds = value.get("pollSeconds", DEFAULT_CONFIG["pollSeconds"])
    if type(poll_seconds) is not int or not 1 <= poll_seconds <= 300:
        raise ValueError("Polling interval must be a whole number from 1 to 300 seconds")
    try:
        ZoneInfo(value["timezone"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Unknown IANA timezone") from None
    bulbs = value.get("bulbs")
    if not isinstance(bulbs, list) or len(bulbs) > 100:
        raise ValueError("bulbs must be an array of at most 100 bulbs")
    clean, seen = [], set()
    for bulb in bulbs:
        if not isinstance(bulb, dict):
            raise ValueError("Invalid bulb")
        mac, ip, room = bulb.get("mac"), bulb.get("ip"), bulb.get("room")
        if not isinstance(mac, str) or not re.fullmatch(r"[0-9a-fA-F]{12}", mac) or mac.lower() in seen:
            raise ValueError("Invalid or duplicate MAC")
        address = ipaddress.IPv4Address(ip)
        if not address.is_private or address.is_loopback or address.is_multicast or address.is_unspecified or str(address).endswith(".255"):
            raise ValueError("Bulb IP must be a private LAN unicast IPv4 address")
        if not isinstance(room, str) or not room.strip() or len(room) > 100:
            raise ValueError("Invalid room")
        seen.add(mac.lower())
        clean.append({"mac": mac.lower(), "ip": str(address), "room": room})
    return {key: value[key] for key in ("enabled", "night", "morning", "timezone")} | {"pollSeconds": poll_seconds, "bulbs": clean}


def schedule(config, now):
    """Return current mode, last boundary and next boundary as UTC timestamps.

    Resolve ambiguous wall times once (fold=0); normalize nonexistent spring
    times forward through UTC. Comparing epochs, not local datetimes, avoids
    repeating a transition when the clock falls back.
    """
    tz = ZoneInfo(config["timezone"])
    day = datetime.fromtimestamp(now, tz).date()
    boundaries = []
    for delta in range(-2, 3):
        for key, mode in (("night", "NIGHT"), ("morning", "REGULAR")):
            hour, minute = map(int, config[key].split(":"))
            date = day + timedelta(days=delta)
            at = datetime(date.year, date.month, date.day, hour, minute, tzinfo=tz).timestamp()
            boundaries.append((at, mode))
    previous = max(entry for entry in boundaries if entry[0] <= now)
    following = min(entry[0] for entry in boundaries if entry[0] > now)
    return previous[1], previous[0], following


def signature(pilot):
    return tuple(pilot.get(key) for key in ("state", "sceneId", "temp", "dimming", "r", "g", "b", "w", "c"))


class Udp:
    def __init__(self, broadcast):
        self.broadcast = broadcast

    def request(self, ip, method, params):
        ident = secrets.randbelow(2**30)
        packet = json.dumps({"id": ident, "method": method, "params": params}).encode()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((ip, 38899))
                sock.settimeout(0.7)
                for _ in range(2):
                    sock.send(packet)
                    end = time.monotonic() + 0.7
                    while time.monotonic() < end:
                        sock.settimeout(max(0.001, end - time.monotonic()))
                        try:
                            reply = json.loads(sock.recv(8192))
                        except (socket.timeout, ValueError):
                            break
                        if isinstance(reply, dict) and reply.get("method") == method and reply.get("id", ident) == ident:
                            return reply.get("result")
        except OSError:
            pass
        return None

    def discover(self):
        found = {}
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.2)
            sock.sendto(b'{"method":"getSystemConfig","params":{}}', (self.broadcast, 38899))
            end = time.monotonic() + 1
            while time.monotonic() < end:
                try:
                    data, source = sock.recvfrom(8192)
                    reply = json.loads(data)
                    if isinstance(reply, dict) and reply.get("method") == "getSystemConfig":
                        result = reply.get("result")
                        mac = result.get("mac") if isinstance(result, dict) else None
                        if isinstance(mac, str) and re.fullmatch(r"[0-9a-fA-F]{12}", mac):
                            found[mac.lower()] = source[0]
                except (socket.timeout, ValueError, KeyError, TypeError):
                    continue
        return found


class Butler:
    def __init__(self, path, udp):
        self.path, self.udp = Path(path), udp
        self.lock = threading.RLock()
        self.changed = threading.Event()
        stored = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.config = validate_config(stored.get("config", DEFAULT_CONFIG))
        self.holds = stored.get("holds", {})
        self.previous = {}
        self.addresses = {}
        self.last_boundary = None
        self.last_discovery = 0
        self.errors = {}
        self.last_poll = None
        self.observed = {}
        self.observed_at = {}
        self.system_configs = {}
        self.discovered = {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with open(temporary, "w", opener=lambda path, flags: os.open(path, flags, 0o600)) as output:
            json.dump({"config": self.config, "holds": self.holds}, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(self.path)

    def configure(self, value):
        with self.lock:
            # Bulbs have dedicated add/remove operations. In particular an old
            # or newly installed phone must never erase this manager's list.
            if "bulbs" in value and value["bulbs"] != self.config["bulbs"]:
                raise ValueError("Manager owns the bulb list; use bulb add/remove, not config")
            config = validate_config(value | {"bulbs": self.config["bulbs"]})
            # Preserve holds, observations and known addresses. Saving a
            # timetable is not a lighting action or a discovery reset.
            old_config = self.config
            self.config = config
            try:
                self.save()
            except OSError:
                self.config = old_config
                raise
            self.previous.clear()
            self.last_boundary = None
            self.changed.set()

    def rediscover(self):
        found = {}
        for mac, ip in self.udp.discover().items():
            try:
                bulb = validate_config(self.config | {"bulbs": [{"mac": mac, "ip": ip, "room": "Discovered"}]})["bulbs"][0]
            except (ValueError, TypeError):
                continue
            found[bulb["mac"]] = bulb["ip"]
        self.addresses.update(found)
        return found

    def discover(self):
        with self.lock:
            found = self.rediscover()
            result = []
            for mac, ip in found.items():
                bulb = {"mac": mac, "ip": ip, "room": "Discovered"}
                pilot = self.pilot(bulb)
                if pilot is None:
                    continue
                self.discovered[mac] = bulb
                self.read_system_config(bulb)
                result.append({"mac": mac, "ip": ip, "pilot": pilot,
                               "systemConfig": self.system_configs.get(mac)})
            return {"discovered": result, "status": self.status()}

    def add_bulb(self, value):
        with self.lock:
            bulb = validate_config(self.config | {"bulbs": [value]})["bulbs"][0]
            if self.pilot(bulb) is None:
                raise ValueError("Bulb did not answer with the expected MAC; discover again")
            old = self.config
            self.config = validate_config(self.config | {"bulbs": [b for b in self.config["bulbs"] if b["mac"] != bulb["mac"]] + [bulb]})
            try:
                self.save()
            except OSError:
                self.config = old
                raise
            # Do not interpret adding an already-on bulb as a wall-switch event.
            self.previous.pop(bulb["mac"], None)
            self.read_system_config(bulb)
            self.changed.set()
            return self.status()

    def remove_bulb(self, mac):
        with self.lock:
            if not isinstance(mac, str) or not any(b["mac"] == mac for b in self.config["bulbs"]):
                raise ValueError("Bulb is not configured on the manager")
            old, holds = self.config, dict(self.holds)
            self.config = self.config | {"bulbs": [b for b in self.config["bulbs"] if b["mac"] != mac]}
            self.holds.pop(mac, None)
            try:
                self.save()
            except OSError:
                self.config, self.holds = old, holds
                raise
            for cache in (self.previous, self.observed, self.observed_at, self.errors, self.system_configs):
                cache.pop(mac, None)
            return self.status()

    def read_system_config(self, bulb):
        result = self.udp.request(self.addresses.get(bulb["mac"], bulb["ip"]), "getSystemConfig", {})
        if isinstance(result, dict) and isinstance(result.get("mac"), str) and result["mac"].lower() == bulb["mac"]:
            self.system_configs[bulb["mac"]] = result

    def blink(self, mac):
        with self.lock:
            bulb = next((b for b in self.config["bulbs"] if b["mac"] == mac), self.discovered.get(mac) if isinstance(mac, str) else None)
            if bulb is None:
                raise ValueError("Unknown bulb; discover through the manager first")
            original = self.pilot(bulb)
            if original is None:
                raise ValueError("Bulb unreachable or MAC mismatch; no blink sent")
            # All flashes/restores share the scheduler lock. Preserve colour,
            # brightness, power and any existing manual hold; no timetable race.
            restore = {k: original[k] for k in ("state", "sceneId", "temp", "dimming", "r", "g", "b", "w", "c") if k in original}
            needs_restore = False
            try:
                for _ in range(2):
                    needs_restore = True
                    if not self.write(bulb, "setPilot", {"state": not original["state"]}):
                        raise ValueError("Blink was not acknowledged")
                    time.sleep(0.3)
                    if not self.write(bulb, "setPilot", restore):
                        raise ValueError("Blink restore was not acknowledged; check bulb state")
                    needs_restore = False
                    time.sleep(0.3)
            finally:
                # Also attempt restoration after a lost flash acknowledgement.
                restored = not needs_restore or self.write(bulb, "setPilot", restore)
                self.previous.pop(mac, None)
                self.pilot(bulb)
                if not restored:
                    raise ValueError("Blink restore failed (unreachable, MAC mismatch or no acknowledgement); check bulb state")
            return self.status()

    def poll_delay(self, now, elapsed=0):
        """Poll at the configured interval, but wake for a schedule boundary too."""
        with self.lock:
            # The configured interval includes work already spent querying:
            # do not add another full second after slow/unreachable replies.
            delay = max(0.05, self.config["pollSeconds"] - elapsed)
            if self.config["enabled"]:
                delay = min(delay, max(0.05, schedule(self.config, now)[2] - now))
            return delay

    def pilot(self, bulb):
        ip = self.addresses.get(bulb["mac"], bulb["ip"])
        pilot = self.udp.request(ip, "getPilot", {})
        # Never send a write to an IP reassigned to a different bulb.
        if not isinstance(pilot, dict) or not isinstance(pilot.get("mac"), str) or pilot["mac"].lower() != bulb["mac"] or type(pilot.get("state")) is not bool:
            self.errors[bulb["mac"]] = "unreachable or MAC mismatch"
            self.observed.pop(bulb["mac"], None)
            return None
        self.errors.pop(bulb["mac"], None)
        self.observed[bulb["mac"]] = pilot
        self.observed_at[bulb["mac"]] = time.time()
        return pilot

    def write(self, bulb, method, params, only_if_on=False):
        # Every write, including blink restoration, verifies identity afresh.
        current = self.pilot(bulb)
        if current is None or (only_if_on and not current["state"]):
            return False
        result = self.udp.request(self.addresses.get(bulb["mac"], bulb["ip"]), method, params)
        ok = isinstance(result, dict) and result.get("success") is True
        if not ok:
            self.errors[bulb["mac"]] = "command not acknowledged"
        return ok

    def apply(self, bulb, mode):
        # Live ESP24_SHRGBC_01/1.29.0 testing showed that BOTH setState and
        # setPilot turn an off bulb on when a preset is supplied. Neither is
        # an atomic "update only if on" operation. Recheck immediately before
        # writing; commands from our API are serialized by self.lock. Another
        # controller can still race this read/write pair (UDP has no CAS).
        current = self.pilot(bulb)
        if current is None or not current["state"]:
            return False
        ok = self.write(bulb, "setPilot", MODES[mode], only_if_on=True)
        if ok:
            logging.info("Timetable %s -> …%s", mode, bulb["mac"][-4:])
        return ok

    def tick(self, now):
        with self.lock:
            self.last_poll = now
            if now - self.last_discovery >= 60:
                try:
                    self.rediscover()
                except OSError:
                    logging.warning("Discovery failed; retaining known addresses")
                self.last_discovery = now
            mode, boundary, following = schedule(self.config, now)
            crossed = self.last_boundary is not None and boundary != self.last_boundary
            dirty = False
            for bulb in self.config["bulbs"]:
                mac = bulb["mac"]
                current = self.pilot(bulb)
                if mac not in self.system_configs:
                    self.read_system_config(bulb)
                known = mac in self.previous
                previous = self.previous.get(mac)
                self.previous[mac] = current
                if not self.config["enabled"]:
                    continue
                if current is None or not current["state"]:
                    continue
                # External colour/brightness changes while on are manual too.
                # Do not infer such a change from a lost packet or power cycle.
                if previous and previous["state"] and signature(current) != signature(previous):
                    self.holds[mac] = following
                    dirty = True
                held = self.holds.get(mac, 0) > now
                turned_on = known and (previous is None or not previous["state"])
                if not held and (crossed or turned_on):
                    if self.apply(bulb, mode):
                        # Global bulb fades can take seconds; baseline the next
                        # poll rather than mistake an intermediate fade for an
                        # external manual override.
                        self.previous.pop(mac, None)
            self.last_boundary = boundary
            if dirty:
                self.save()

    def command(self, room, mode, now):
        if not isinstance(room, str) or mode not in (*MODES, "OFF", "AUTO", "ON", "TOGGLE"):
            raise ValueError("Expected room and REGULAR, NIGHT, OFF, ON, AUTO or TOGGLE mode")
        with self.lock:
            if mode == "AUTO" and not self.config["enabled"]:
                raise ValueError("Timetable is disabled; enable it before resuming")
            bulbs = [b for b in self.config["bulbs"] if b["room"] == room]
            if not bulbs:
                raise ValueError("Room is not configured on the butler")
            # Decide toggle from the laptop's fresh observations under the same
            # lock as scheduling, not the phone's potentially stale UDP cache.
            pilots = {bulb["mac"]: self.pilot(bulb) for bulb in bulbs}
            if mode == "TOGGLE":
                mode = "OFF" if any(p and p["state"] for p in pilots.values()) else "ON"
            current_mode, _, following = schedule(self.config, now)
            old_holds = dict(self.holds)
            for bulb in bulbs:
                if mode == "AUTO":
                    self.holds.pop(bulb["mac"], None)
                else:
                    self.holds[bulb["mac"]] = following
            # Persist intent before writing, so restart or a lost UDP reply
            # cannot cause the scheduler to undo a manual action.
            try:
                self.save()
            except OSError:
                self.holds = old_holds
                raise
            ok = 0
            for bulb in bulbs:
                pilot = pilots[bulb["mac"]]
                if pilot is None:
                    continue
                if mode == "AUTO":
                    success = not pilot["state"] or self.apply(bulb, current_mode)
                else:
                    preset = current_mode if mode == "ON" else mode
                    params = {"state": mode != "OFF"} | (MODES[preset] if preset in MODES else {})
                    success = self.write(bulb, "setPilot", params)
                if success:
                    ok += 1
                self.previous.pop(bulb["mac"], None)
                if success:
                    self.pilot(bulb)
            return {"answered": ok, "total": len(bulbs), "errors": dict(self.errors)}

    def status(self):
        with self.lock:
            bulbs = [b | {"ip": self.addresses.get(b["mac"], b["ip"])} for b in self.config["bulbs"]]
            saved = {b["mac"] for b in bulbs}
            return {"config": self.config | {"bulbs": bulbs}, "holds": dict(self.holds), "errors": dict(self.errors),
                    "pilots": {mac: p for mac, p in self.observed.items() if mac in saved},
                    "systemConfigs": {mac: c for mac, c in self.system_configs.items() if mac in saved},
                    "observedAt": {mac: at for mac, at in self.observed_at.items() if mac in saved},
                    "lastPoll": self.last_poll, "statusAt": time.time(), "native": False}


def handler(butler):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def respond(self, code, value):
            data = json.dumps(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path not in ("/v1/config", "/v1/status"):
                self.respond(404, {"error": "Not found"})
                return
            self.respond(200, butler.status())

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32768:
                    raise ValueError("Invalid body length")
                value = json.loads(self.rfile.read(length))
                if not isinstance(value, dict):
                    raise ValueError("Expected JSON object")
                if self.path == "/v1/config":
                    butler.configure(value)
                    self.respond(200, butler.status())
                elif self.path == "/v1/room":
                    self.respond(200, butler.command(value.get("room"), value.get("mode"), time.time()))
                elif self.path == "/v1/discover":
                    self.respond(200, butler.discover())
                elif self.path == "/v1/bulbs/add":
                    self.respond(200, butler.add_bulb(value))
                elif self.path == "/v1/bulbs/remove":
                    self.respond(200, butler.remove_bulb(value.get("mac")))
                elif self.path == "/v1/bulbs/blink":
                    self.respond(200, butler.blink(value.get("mac")))
                else:
                    self.respond(404, {"error": "Not found"})
            except (ValueError, TypeError) as error:
                self.respond(400, {"error": str(error)})
            except OSError:
                logging.exception("Butler storage/network failure")
                self.respond(503, {"error": "Butler storage/network failure"})

        def log_message(self, fmt, *args):
            logging.info(fmt, *args)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", default="127.0.0.1", help="Bind a specific LAN IP to allow the phone")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--state", type=Path, default=Path.home() / ".local/state/uniremote-wiz/state.json")
    parser.add_argument("--broadcast", default="255.255.255.255", help="LAN broadcast for DHCP rediscovery")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    butler = Butler(args.state, Udp(args.broadcast))
    server = ThreadingHTTPServer((args.listen, args.port), handler(butler))
    bonjour = Bonjour(args.listen, server.server_port)
    bonjour.start()
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            butler.changed.clear()
            started = time.monotonic()
            try:
                butler.tick(time.time())
            except Exception:
                logging.exception("Poll failed; no automatic retry of writes")
            butler.changed.wait(butler.poll_delay(time.time(), time.monotonic() - started))

    worker = threading.Thread(target=poll, daemon=True)
    worker.start()
    logging.info("Listening on %s:%d; timetable enabled=%s", args.listen, args.port, butler.config["enabled"])
    def terminate(_signal, _frame):
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, terminate)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        butler.changed.set()
        server.server_close()
        bonjour.close()


if __name__ == "__main__":
    main()
