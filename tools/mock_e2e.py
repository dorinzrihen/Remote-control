#!/usr/bin/env python3
"""End-to-end GUI verification against simulated WiZ bulbs. Never real lights.

  up        build Preview, boot the DISPOSABLE uniremote-preview emulator (headless,
            -read-only), start mock bulbs + the REAL wiz_butler.py manager on
            loopback, wire adb reverse, seed Preview to use only that manager
  down      stop mock bulbs, manager and the disposable emulator
  scenario  scripted proof (power toggle, Night/Regular, offline, discovery)
  status | state | bulb | tap | tap-in | wait | scroll | shot | tree   (drive it)

Artifacts: /tmp/uniremote-mock-e2e (screenshots + index.html). The everyday
uniremote-pixel-8a device is never started, reset or targeted.
"""

import argparse
import html
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen

import android_ui
from android_ui import Android, MODE_LABELS, find, texts
import mock_lights

ROOT = Path(__file__).resolve().parents[1]
AVD = "uniremote-preview"
EVERYDAY_AVD = "uniremote-pixel-8a"
CONSOLE_PORT = 5580
SERIAL = f"emulator-{CONSOLE_PORT}"
DEVICE_MANAGER_PORT = 8789  # Port inside Android; adb reverse maps it to the host mock manager.
OUT = Path(os.environ.get("UNIREMOTE_MOCK_E2E_DIR", "/tmp/uniremote-mock-e2e"))
RUN = OUT / "run"
SESSION = RUN / "session.json"
SERVICE_NAME = "Mock lights only - never household"
APK = ROOT / "app/build/outputs/apk/debug/app-debug.apk"


class Error(RuntimeError):
    pass


# ---------------------------------------------------------------- pure helpers

def room_status(count, status):
    return f"{count} bulb{'' if count == 1 else 's'}  ·  {status}"


def section(tree, room, rooms):
    """Nodes drawn between `room`'s title and the next room title (one room card)."""
    titles = {}
    for node in tree.iter("node"):
        if node.get("text") in rooms and node.get("text") not in titles and node.get("bounds"):
            titles[node.get("text")] = bounds(node)[1]
    if room not in titles:
        return []
    top = titles[room]
    bottom = min([y for y in titles.values() if y > top], default=float("inf"))
    return [node for node in tree.iter("node") if node.get("bounds") and top <= bounds(node)[1] < bottom]


def bounds(node):
    return tuple(map(int, re.findall(r"\d+", node.get("bounds"))))


def selected_in(nodes):
    chosen = []
    for node in nodes:
        if node.get("checkable") == "true" and node.get("checked") == "true":
            labels = [n.get("text") for n in node.iter("node") if n.get("text") in MODE_LABELS]
            chosen += labels[:1]
    return chosen


def rooms_of(status):
    return list(dict.fromkeys(b["room"] for b in status["config"]["bulbs"]))


def require_disposable(avd):
    if avd != AVD or avd == EVERYDAY_AVD:
        raise Error(f"Refusing to target AVD {avd!r}; only the disposable {AVD} is allowed")


def write_index(out=OUT):
    shots = json.loads((out / "shots.json").read_text()) if (out / "shots.json").exists() else []
    results = json.loads((out / "results.json").read_text()) if (out / "results.json").exists() else []
    figures = "\n".join(
        f'<figure><figcaption>{html.escape(s["caption"])}</figcaption>'
        f'<a href="{html.escape(s["file"])}"><img src="{html.escape(s["file"])}"></a></figure>' for s in shots)
    checks = "\n".join(f"<li>{html.escape(line)}</li>" for line in results)
    (out / "index.html").write_text(f'''<!doctype html><meta charset="utf-8">
<title>UniRemote mock lights e2e</title>
<style>body{{font:16px system-ui;background:#12141a;color:#eee;margin:28px}}
.s{{display:flex;gap:22px;flex-wrap:wrap}}figure{{margin:0;width:300px}}img{{width:100%;border:1px solid #555;border-radius:14px}}
figcaption{{margin:8px 0;font-weight:bold}}li{{margin:4px 0}}</style>
<h1>UniRemote Preview against simulated bulbs</h1>
<p>Real app in the disposable {AVD} emulator, real wiz_butler.py manager, simulated WiZ bulbs on 127.0.0.x. No real lights.</p>
<ul>{checks}</ul><div class="s">{figures}</div>''')
    return out / "index.html"


# ---------------------------------------------------------------- session

def load_session():
    if not SESSION.exists():
        raise Error("No mock session. Run: python3 tools/mock_e2e.py up")
    return json.loads(SESSION.read_text())


def http_json(url, body=None, timeout=10):
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET")
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def free_port(kind=socket.SOCK_STREAM, address="127.0.0.1"):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind((address, 0))
        return sock.getsockname()[1]


def wait_http(url, process, name, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise Error(f"{name} exited ({process.returncode}); see {RUN}")
        try:
            return http_json(url, timeout=2)
        except OSError:
            time.sleep(0.2)
    raise Error(f"{name} did not answer {url}")


def spawn(args, log):
    with (RUN / log).open("ab") as output:
        return subprocess.Popen([sys.executable, *map(str, args)], cwd=ROOT, stdin=subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.STDOUT, start_new_session=True)


def kill(pid, marker):
    """Terminate pid only if its command line is still ours (pids can be reused)."""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        return
    if marker in cmdline:
        os.kill(pid, signal.SIGTERM)


class Emulator:
    def __init__(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import emulator
        self.device = emulator.Device()  # SDK/JDK discovery only; its AVD methods are never used.

    def adb(self, *args, check=False, timeout=10):
        return self.device.adb_run(*args, check=check, timeout=timeout)

    def avd_name(self, serial):
        try:
            result = self.adb("-s", serial, "emu", "avd", "name", timeout=5)
        except subprocess.TimeoutExpired:
            return None
        lines = result.stdout.split()
        return lines[0] if result.returncode == 0 and lines else None

    def build(self):
        self.device.java()
        subprocess.run([str(ROOT / "gradlew"), "assembleDebug"], cwd=ROOT, env=self.device.env, check=True, timeout=900)

    def start(self, window=False):
        require_disposable(AVD)
        if SERIAL in self.device.serials():
            name = self.avd_name(SERIAL)
            require_disposable(name)
            print(f"Reusing {AVD} on {SERIAL}", flush=True)
        else:
            args = [self.device.emulator, "-avd", AVD, "-port", CONSOLE_PORT, "-read-only", "-no-snapshot-save",
                    "-no-audio", "-no-boot-anim", "-gpu", "swiftshader_indirect", "-no-metrics"]
            if not window:
                args.append("-no-window")
            RUN.mkdir(parents=True, exist_ok=True)
            with (RUN / "emulator.log").open("ab") as log:
                subprocess.Popen([str(a) for a in args], env=self.device.env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            print(f"Booting disposable {AVD} ({'windowed' if window else 'headless'}, read-only) on {SERIAL}…", flush=True)
            deadline = time.monotonic() + 120
            while SERIAL not in self.device.serials():
                if time.monotonic() > deadline:
                    raise Error(f"{AVD} did not appear in adb; see {RUN / 'emulator.log'}")
                time.sleep(1)
            require_disposable(self.avd_name(SERIAL))
        deadline = time.monotonic() + 240
        while self.adb("-s", SERIAL, "shell", "getprop", "sys.boot_completed").stdout.strip() != "1":
            if time.monotonic() > deadline:
                raise Error(f"{AVD} did not finish booting")
            time.sleep(1)

    def stop(self):
        if SERIAL not in self.device.serials():
            return False
        require_disposable(self.avd_name(SERIAL))
        self.adb("-s", SERIAL, "emu", "kill")
        deadline = time.monotonic() + 30
        while SERIAL in self.device.serials() and time.monotonic() < deadline:
            time.sleep(1)
        return True


def android(session=None):
    session = session or load_session()
    return Android(session["serial"], session["adb"])


def stop_mocks(session):
    for key, marker in (("managerPid", "wiz_butler.py"), ("simulatorPid", "mock_lights.py")):
        if session.get(key):
            kill(session[key], marker)


def up(args):
    emulator = Emulator()
    if args.build or not APK.exists():
        emulator.build()
    if SESSION.exists():
        stop_mocks(json.loads(SESSION.read_text()))
    OUT.mkdir(parents=True, exist_ok=True)
    for old in [*OUT.glob("*.png"), *OUT.glob("*.xml"), OUT / "shots.json", OUT / "results.json", OUT / "index.html"]:
        old.unlink(missing_ok=True)
    if RUN.exists():
        for old in RUN.iterdir():
            if old.name != "emulator.log":
                shutil.rmtree(old) if old.is_dir() else old.unlink()
    RUN.mkdir(parents=True, exist_ok=True)

    bulbs = mock_lights.layout(mock_lights.parse_rooms(args.rooms), args.new, args.offline)
    (RUN / "layout.json").write_text(json.dumps(bulbs, indent=2))
    (RUN / "manager-state.json").write_text(json.dumps(mock_lights.manager_state(bulbs, args.timetable), indent=2))
    for attempt in range(3):
        udp_port, control_port, manager_port = free_port(socket.SOCK_DGRAM, mock_lights.DISCOVERY_ADDRESS), free_port(), free_port()
        simulator = spawn([ROOT / "tools/mock_lights.py", "--layout", RUN / "layout.json",
                           "--port", udp_port, "--control-port", control_port], "mock-lights.log")
        try:
            wait_http(f"http://127.0.0.1:{control_port}/bulbs", simulator, "Mock bulbs")
            break
        except Error:
            if attempt == 2:
                raise
    manager = spawn([ROOT / "butler/wiz_butler.py", "--listen", "127.0.0.1", "--port", manager_port,
                     "--state", RUN / "manager-state.json", "--broadcast", mock_lights.DISCOVERY_ADDRESS,
                     "--test-loopback-bulbs", "--test-bulb-port", udp_port], "manager.log")
    session = {"serial": SERIAL, "avd": AVD, "adb": str(emulator.device.adb),
               "simulatorPid": simulator.pid, "managerPid": manager.pid,
               "control": f"http://127.0.0.1:{control_port}", "manager": f"http://127.0.0.1:{manager_port}",
               "rooms": [room for room, _ in mock_lights.parse_rooms(args.rooms)]}
    SESSION.write_text(json.dumps(session, indent=2))
    wait_http(session["manager"] + "/v1/status", manager, "Mock manager")

    emulator.start(window=args.window)
    device = android(session)
    device.adb("reverse", f"tcp:{DEVICE_MANAGER_PORT}", f"tcp:{manager_port}")
    device.prepare()
    device.install_fresh(APK, android_ui.preferences(f"http://127.0.0.1:{DEVICE_MANAGER_PORT}", SERVICE_NAME))
    device.open_bulbs()
    registered = sum(b["registered"] for b in bulbs)
    device.wait_for(f"Connected · {registered} bulbs", timeout=45)
    print(f"UP: Preview on {SERIAL} is connected to the mock manager {session['manager']} "
          f"({registered} saved bulbs, {args.new} undiscovered). Bulb state: python3 tools/mock_e2e.py state", flush=True)


def down(_args):
    session = json.loads(SESSION.read_text()) if SESSION.exists() else {}
    stop_mocks(session)
    emulator = Emulator()
    if SERIAL in emulator.device.serials():
        emulator.adb("-s", SERIAL, "reverse", "--remove", f"tcp:{DEVICE_MANAGER_PORT}")
    stopped = emulator.stop()
    SESSION.unlink(missing_ok=True)
    print(f"DOWN: mock bulbs/manager stopped; {AVD} {'stopped' if stopped else 'was not running'}. Artifacts kept in {OUT}")


# ---------------------------------------------------------------- driving commands

def bulb_state(session=None):
    return http_json((session or load_session())["control"] + "/bulbs")


def manager_status(session=None):
    return http_json((session or load_session())["manager"] + "/v1/status")


def shot(name, caption=None, device=None):
    device = device or android()
    OUT.mkdir(parents=True, exist_ok=True)
    file = re.sub(r"[^A-Za-z0-9_.-]", "-", name).removesuffix(".png") + ".png"
    device.screenshot(OUT / file)
    shots_path = OUT / "shots.json"
    shots = [s for s in (json.loads(shots_path.read_text()) if shots_path.exists() else []) if s["file"] != file]
    shots.append({"file": file, "caption": caption or name})
    shots_path.write_text(json.dumps(shots, indent=2))
    write_index()
    return OUT / file


def tap_in(device, room, label, rooms):
    tree = device.scroll_to(room)
    node = next((n for n in section(tree, room, rooms) if label in (n.get("text"), n.get("content-desc"))), None)
    if node is None:
        raise Error(f"No {label!r} in the {room} card")
    device.tap_xy(*android_ui.center(node))


def open_manage_bulbs(device):
    """Scroll down to the bulb manager, opening it unless already open (live sessions)."""
    for _ in range(12):
        tree = device.hierarchy()
        if find(tree, "Find new bulbs") is not None:
            return
        node = find(tree, "Manage bulbs")
        if node is not None:
            device.tap_xy(*android_ui.center(node))
            time.sleep(0.5)
        else:
            device.scroll()
    raise Error("Could not open Manage bulbs")


def cmd_state(args):
    bulbs = bulb_state()
    if args.json:
        print(json.dumps(bulbs, indent=2))
        return
    for b in bulbs:
        p = b["pilot"]
        print(f"{b['mac']} {b['ip']:<12} {str(b['room'] or '(new, unregistered)'):<20} "
              f"{'online ' if b['online'] else 'OFFLINE'} {'on ' if p['state'] else 'off'} "
              f"dim={p.get('dimming')} temp={p.get('temp')} commands={len(b['commands'])}")


def cmd_bulb(args):
    change = {}
    if args.offline or args.online:
        change["online"] = bool(args.online)
    if args.on or args.off:
        change["pilot"] = {"state": bool(args.on)}
    print(json.dumps(http_json(load_session()["control"] + "/bulbs/" + args.target.replace(" ", "%20"), change), indent=2))


def cmd_tree(args):
    tree = android().hierarchy()
    if args.xml:
        import xml.etree.ElementTree as ET
        print(ET.tostring(tree, encoding="unicode"))
    else:
        print("\n".join(texts(tree)))


# ---------------------------------------------------------------- scenario

def scenario(args):
    if not SESSION.exists():
        up(args)
    session = load_session()
    device, results = android(session), []
    rooms = rooms_of(manager_status(session))

    def ok(message):
        results.append("PASS: " + message)
        print(results[-1], flush=True)
        (OUT / "results.json").write_text(json.dumps(results, indent=2))
        write_index()

    def sim(room):
        return [b for b in bulb_state(session) if b["room"] == room]

    def wait_sim(room, predicate, description, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            bulbs = sim(room)
            if bulbs and all(predicate(b) for b in bulbs):
                return bulbs
            time.sleep(0.3)
        raise Error(f"Simulated bulbs never reached: {description}; now {sim(room)}")

    def wait_card(room, status, selected=None):
        def check(tree):
            nodes = section(tree, room, rooms)
            labels = [n.get("text") for n in nodes]
            return status in labels and (selected is None or selected_in(nodes) == selected)
        device.scroll_top()
        return device.wait_until(check, f"{room} card shows {status!r} selected={selected}")

    living, bedroom = rooms[0], rooms[1] if len(rooms) > 1 else None
    online = [b for b in sim(living) if b["online"]]
    if not online or len(online) != len(sim(living)):
        raise Error(f"Scenario needs every bulb in {living!r} online")
    count = len(online)

    device.scroll_top()
    start = "Night" if all(b["pilot"]["temp"] == 2700 for b in online) else None
    if start:
        wait_card(living, room_status(count, start), ["Night"])
    shot("01-connected", "Connected to mock manager (initial state)", device)
    ok(f"Bulbs tab connected to the real manager with simulated bulbs; {living} shows {start or 'its state'}")

    tap_in(device, living, f"{living} on / off", rooms)
    wait_sim(living, lambda b: not b["pilot"]["state"], f"{living} off")
    wait_card(living, room_status(count, "off"))
    shot("02-room-off", f"{living} power toggled off", device)
    ok(f"Power toggle turned every simulated {living} bulb off and the card says 'off'")

    tap_in(device, living, f"{living} on / off", rooms)
    wait_sim(living, lambda b: b["pilot"]["state"], f"{living} on")
    ok(f"Power toggle turned {living} back on (simulated state on)")

    tap_in(device, living, "Regular", rooms)
    wait_sim(living, lambda b: b["pilot"]["state"] and (b["pilot"]["dimming"], b["pilot"]["temp"]) == (100, 6500), "Regular 100%/6500K")
    wait_card(living, room_status(count, "Regular"), ["Regular"])
    shot("03-regular", f"{living} Regular selected", device)
    ok(f"Regular: simulated bulbs at 100%/6500K; only Regular selected in the {living} card")

    tap_in(device, living, "Night", rooms)
    wait_sim(living, lambda b: b["pilot"]["state"] and (b["pilot"]["dimming"], b["pilot"]["temp"]) == (20, 2700), "Night 20%/2700K")
    wait_card(living, room_status(count, "Night"), ["Night"])
    shot("04-night", f"{living} Night selected", device)
    ok(f"Night: simulated bulbs at 20%/2700K; only Night selected in the {living} card")

    offline = [b for b in bulb_state(session) if b["registered"] and not b["online"]]
    if offline and bedroom:
        total, missing = len(sim(bedroom)), sum(b["room"] == bedroom for b in offline)
        wait_card(bedroom, room_status(total, "no power or offline" if missing == total else f"{missing} with no power or offline"))
        device.scroll_to(bedroom)
        shot("05-offline", f"{bedroom}: offline bulb", device)
        ok(f"Offline simulated bulb: {bedroom} card reports no power/offline")

    new = [b for b in bulb_state(session) if not b["registered"] and b["online"]]
    if new:
        open_manage_bulbs(device)
        if offline:
            device.scroll_to("not reachable", exact=False, up=True)
            shot("06-manage-offline", "Manage bulbs: offline bulb marked not reachable", device)
            ok("Manage bulbs lists the offline bulb as 'not reachable'")
        device.scroll_to("Find new bulbs")
        device.tap("Find new bulbs")
        label = f"New bulb …{new[0]['mac'][-4:]}  ·  {new[0]['ip']}"
        # Results appear below the button, usually off-screen: scroll while waiting.
        deadline = time.monotonic() + 30
        while True:
            try:
                device.scroll_to(label, attempts=3, exact=False)
                break
            except RuntimeError:
                if time.monotonic() > deadline:
                    raise
        device.scroll_to("Add to ", exact=False)
        shot("07-discovered", "Find new bulbs: simulated new bulb discovered", device)
        ok(f"Find new bulbs: manager discovery over loopback found the simulated bulb at {new[0]['ip']}")
        _tree, button = device.wait_for("Add to ", exact=False)
        room = button.get("text").removeprefix("Add to ")
        device.tap_xy(*android_ui.center(button))
        deadline = time.monotonic() + 20
        while new[0]["mac"] not in {b["mac"] for b in manager_status(session)["config"]["bulbs"]}:
            if time.monotonic() > deadline:
                raise Error("Manager never saved the discovered bulb")
            time.sleep(0.3)
        device.scroll_to(f"{room}  ·  …{new[0]['mac'][-4:]}", exact=False)
        shot("08-added", f"Discovered bulb added to {room}", device)
        ok(f"Add: the manager saved the simulated bulb in {room}; it is listed under Saved bulbs")

    if offline:
        http_json(session["control"] + "/bulbs/" + offline[0]["mac"], {"online": True})
        device.scroll_top()
        device.wait_until(lambda tree: not any("no power or offline" in t for t in texts(tree)),
                          "offline status cleared after the bulb came back", timeout=30)
        shot("09-back-online", f"{offline[0]['room']}: bulb back online", device)
        ok("Simulated bulb brought back online at runtime; the app cleared its offline status")

    print("Scenario passed. Screenshots:", write_index())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    def add_up_options(command):
        command.add_argument("--rooms", default="Living room=2,Bedroom=1", help="Saved rooms, e.g. 'Kitchen=3,Hall=1'")
        command.add_argument("--new", type=int, default=1, help="Extra unregistered bulbs for Find new bulbs")
        command.add_argument("--offline", action="append", default=None, help="Room or MAC that starts offline (repeatable)")
        command.add_argument("--timetable", action="store_true", help="Enable the manager timetable (time-dependent)")
        command.add_argument("--build", action="store_true", help="Run ./gradlew assembleDebug first (default: only if APK missing)")
        command.add_argument("--window", action="store_true", help="Show the emulator window instead of headless")

    add_up_options(commands.add_parser("up", help="Start everything and leave it running"))
    add_up_options(commands.add_parser("scenario", help="Run the scripted proof (starts `up` if needed)"))
    commands.add_parser("down", help="Stop mocks and the disposable emulator")
    commands.add_parser("status", help="Session and manager summary")
    state = commands.add_parser("state", help="Simulated bulb state")
    state.add_argument("--json", action="store_true")
    bulb = commands.add_parser("bulb", help="Change a simulated bulb or room at runtime")
    bulb.add_argument("target", help="MAC or room name")
    for flag in ("--offline", "--online", "--on", "--off"):
        bulb.add_argument(flag, action="store_true")
    tap = commands.add_parser("tap", help="Tap a node by exact text/content-desc")
    tap.add_argument("label")
    tap.add_argument("--contains", action="store_true")
    tap_room = commands.add_parser("tap-in", help="Tap a label inside one room card, e.g. tap-in 'Living room' Night")
    tap_room.add_argument("room")
    tap_room.add_argument("label")
    wait = commands.add_parser("wait", help="Wait until text is visible")
    wait.add_argument("label")
    wait.add_argument("--contains", action="store_true")
    wait.add_argument("--timeout", type=float, default=25)
    scroll = commands.add_parser("scroll", help="Scroll down (or --up / --to LABEL / --top)")
    scroll.add_argument("--up", action="store_true")
    scroll.add_argument("--top", action="store_true")
    scroll.add_argument("--to")
    shoot = commands.add_parser("shot", help=f"Screenshot into {OUT} and refresh index.html")
    shoot.add_argument("name")
    shoot.add_argument("--caption")
    tree = commands.add_parser("tree", help="Visible texts (or --xml for the full UI tree)")
    tree.add_argument("--xml", action="store_true")
    args = parser.parse_args(argv)
    if getattr(args, "offline", None) is None and args.command in ("up", "scenario"):
        args.offline = ["Bedroom"] if args.rooms == "Living room=2,Bedroom=1" else []

    try:
        if args.command == "up":
            up(args)
        elif args.command == "scenario":
            scenario(args)
        elif args.command == "down":
            down(args)
        elif args.command == "status":
            session = load_session()
            status = manager_status(session)
            print(json.dumps(session, indent=2))
            print("Manager rooms:", rooms_of(status), "errors:", status["errors"])
        elif args.command == "state":
            cmd_state(args)
        elif args.command == "bulb":
            cmd_bulb(args)
        elif args.command == "tap":
            android().tap(args.label, exact=not args.contains)
        elif args.command == "tap-in":
            tap_in(android(), args.room, args.label, rooms_of(manager_status()))
        elif args.command == "wait":
            android().wait_for(args.label, timeout=args.timeout, exact=not args.contains)
        elif args.command == "scroll":
            device = android()
            if args.to:
                device.scroll_to(args.to)
            elif args.top:
                device.scroll_top()
            else:
                device.scroll(up=args.up)
        elif args.command == "shot":
            print(shot(args.name, args.caption))
        elif args.command == "tree":
            cmd_tree(args)
    except (Error, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"mock-e2e: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
