#!/usr/bin/env python3
"""Capture the actual Preview APK in a dedicated emulator, without light commands.

Requires a booted Android emulator and a built app-debug.apk. Resets only the
separate com.dorin.uniremote.preview app on that emulator. No real manager calls.
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PACKAGE = "com.dorin.uniremote.preview"
STATE_SCREENSHOTS = ("bulbs-regular.png", "bulbs-night.png", "bulbs-follow.png")


def fixture_preferences():
    # Active schedule + deliberately different saved service name prevent NSD
    # from switching to the household manager, even if the fixture goes offline.
    return b'''<?xml version="1.0" encoding="utf-8"?>
<map><string name="butler_url">http://127.0.0.1:8789</string>
<string name="butler_service_name">Preview fixture only - never household</string>
<boolean name="butler_enabled" value="true" /></map>'''


def fixture(mode="mixed"):
    """Generate fresh observations; preset/follow states never depend on wall time."""
    if mode not in ("mixed", "regular", "night", "follow"):
        raise ValueError("Unknown screenshot fixture mode")
    now = time.time()
    bulbs = [{"mac": "aabb00000001", "ip": "192.168.50.11", "room": "Living room"},
             {"mac": "aabb00000002", "ip": "192.168.50.12", "room": "Bedroom"}]
    status = {"config": {"enabled": True, "night": "21:00", "morning": "06:00",
                       "timezone": "Asia/Jerusalem", "pollSeconds": 1, "bulbs": bulbs},
            "holds": {}, "errors": {bulbs[1]["mac"]: "unreachable"},
            "pilots": {bulbs[0]["mac"]: {"mac": bulbs[0]["mac"], "state": False, "dimming": 20, "temp": 2700}},
            "systemConfigs": {}, "observedAt": {bulbs[0]["mac"]: now},
             "lastPoll": now, "statusAt": now, "native": False}
    if mode != "mixed":
        dimming, temp = (100, 6500) if mode == "regular" else (20, 2700)
        status["errors"] = {}
        status["pilots"] = {b["mac"]: {"mac": b["mac"], "state": True,
                                         "dimming": dimming, "temp": temp} for b in bulbs}
        status["observedAt"] = {b["mac"]: now for b in bulbs}
        status["holds"] = {} if mode == "follow" else {b["mac"]: now + 3600 for b in bulbs}
    return status


def copy_state_screenshots(source, destination):
    """Copy only the allowlisted fixture states, never live evidence or HTML."""
    destination.mkdir(parents=True, exist_ok=True)
    for name in STATE_SCREENSHOTS:
        shutil.copy2(source / name, destination / name)


def selected_controls(tree):
    # Compose selectable(Role.RadioButton) exports Checked on the parent View,
    # with its text in a child; it is not Android's legacy Selected attribute.
    return [child.get("text") for node in tree.iter("node")
            if node.get("checkable") == "true" and node.get("checked") == "true"
            for child in node.iter("node") if child.get("text") in ("Regular", "Night", "Follow timetable")]


class FixtureHandler(BaseHTTPRequestHandler):
    def respond(self, code, value):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/status":
            self.respond(200, fixture(getattr(self.server, "fixture_mode", "mixed")))
        else:
            self.respond(404, {"error": "Not found"})

    def do_POST(self):
        # Optional canned discovery is read-only too: no socket to a bulb or
        # household manager exists here. All configuration/control stays denied.
        if self.path == "/v1/discover" and getattr(self.server, "fixture_discovery", False):
            self.respond(200, {"status": fixture(getattr(self.server, "fixture_mode", "mixed")),
                               "discovered": [{"ip": "192.168.50.13", "mac": "aabb00000003",
                                               "pilot": {"mac": "aabb00000003", "state": True,
                                                         "dimming": 20, "temp": 2700}}]})
            return
        self.respond(403, {"error": "Screenshot fixture is read-only; no hardware attached"})

    def log_message(self, *_args):
        pass


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=Path, default=root / ".local/build-tools/android-sdk/platform-tools/adb")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--apk", type=Path, default=root / "app/build/outputs/apk/debug/app-debug.apk")
    parser.add_argument("--output", type=Path, help="Capture directory (fixtures-only defaults to .local/preview/fixture)")
    parser.add_argument("--fixtures-only", action="store_true", help="Capture sample states without writing a gallery or contacting the Mac")
    parser.add_argument("--copy-states-to", type=Path, help="Copy only Regular/Night/Follow PNGs; preserve existing live evidence")
    args = parser.parse_args()
    if args.copy_states_to and not args.fixtures_only:
        parser.error("--copy-states-to requires --fixtures-only")
    if args.output is None:
        args.output = root / (".local/preview/fixture" if args.fixtures_only else ".local/preview")
    if args.copy_states_to and args.output.resolve() == args.copy_states_to.resolve():
        parser.error("Fixture output and gallery copy destination must differ")
    if not args.serial.startswith("emulator-"):
        parser.error("Use a dedicated emulator, never a physical phone, for fixture capture")
    args.output.mkdir(parents=True, exist_ok=True)

    def adb(*arguments, data=None, timeout=30):
        return subprocess.run([str(args.adb), "-s", args.serial, *arguments],
                              input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, check=True).stdout

    def hierarchy():
        adb("shell", "uiautomator", "dump", "/sdcard/uniremote-preview.xml")
        return ET.fromstring(adb("exec-out", "cat", "/sdcard/uniremote-preview.xml"))

    def find(tree, label):
        return next((node for node in tree.iter("node")
                     if label in (node.get("text"), node.get("content-desc"))), None)

    def wait_for(label):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            tree = hierarchy()
            node = find(tree, label)
            if node is not None:
                return tree, node
            time.sleep(0.3)
        raise RuntimeError(f"UI never showed {label!r}")

    def tap(label):
        _tree, node = wait_for(label)
        x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds")))
        adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))

    size = None

    def scroll(up=False):
        nonlocal size
        if size is None:
            size = tuple(map(int, re.findall(rb"(\d+)x(\d+)", adb("shell", "wm", "size"))[-1]))
        width, height = size
        start, end = (0.35, 0.78) if up else (0.78, 0.35)
        adb("shell", "input", "swipe", str(width // 2), str(int(height * start)),
            str(width // 2), str(int(height * end)), "350")

    def scroll_to(label):
        for _ in range(8):
            if find(hierarchy(), label) is not None:
                return
            scroll()
        raise RuntimeError(f"Could not scroll to {label!r}")

    def scroll_top():
        for _ in range(4):
            if find(hierarchy(), "Bulbs") is not None:
                return
            scroll(up=True)
        wait_for("Bulbs")

    def open_bulbs():
        adb("shell", "am", "start", "-n", PACKAGE + "/com.dorin.remote.ui.MainActivity")
        tap("Done")
        tap("Quick actions")
        tap("Bulbs")

    def screenshot(name):
        image = adb("exec-out", "screencap", "-p")
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Emulator did not return a PNG")
        (args.output / name).write_bytes(image)

    adb("wait-for-device", timeout=90)
    adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
    adb("shell", "wm", "dismiss-keyguard")
    for setting in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
        adb("shell", "settings", "put", "global", setting, "0")
    adb("install", "-r", str(args.apk.resolve()), timeout=90)
    adb("shell", "pm", "clear", PACKAGE)
    # Seed before the FIRST Bulbs open: fresh unauthenticated Preview otherwise
    # automatically connects to the real Bonjour manager.
    with ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler) as server:
        server.fixture_discovery = args.fixtures_only
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = str(server.server_port)
        adb("reverse", "tcp:8789", "tcp:" + port)
        try:
            adb("shell", "am", "force-stop", PACKAGE)
            adb("shell", "run-as", PACKAGE, "sh", "-c", "'mkdir -p shared_prefs; cat > shared_prefs/uniremote.xml'", data=fixture_preferences())
            open_bulbs()
            wait_for("Living room")
            # Content arrives after the sheet opens; drag only its handle to
            # settle the expanded anchor, never swipe/tap a light-control pill.
            _tree, handle = wait_for("Drag handle")
            x1, y1, x2, y2 = map(int, re.findall(r"\d+", handle.get("bounds")))
            adb("shell", "input", "swipe", str((x1 + x2) // 2), str((y1 + y2) // 2),
                str((x1 + x2) // 2), "100", "400")
            tree, _node = wait_for("Connected · 2 bulbs")
            assert find(tree, "Living room") is not None
            assert find(tree, "Bedroom") is not None
            assert find(tree, "Manager URL") is None
            assert find(tree, "Save timetable") is None
            screenshot("bulbs-connected.png")
            tap("Edit timetable")
            wait_for("Night HH:MM")
            screenshot("bulbs-timetable.png")
            if args.fixtures_only:
                tap("Hide timetable")
                scroll_top()
                for mode, label, choice in (("regular", "Regular", "Regular"), ("night", "Night", "Night"),
                                            ("follow", "Following · Night", "Follow timetable")):
                    server.fixture_mode = mode
                    wait_for("1 bulb  ·  " + label)
                    time.sleep(1.3)
                    tree = hierarchy()
                    selected = selected_controls(tree)
                    assert selected == [choice, choice], f"Wrong active controls for {mode}: {selected}"
                    (args.output / ("bulbs-" + mode + ".xml")).write_bytes(ET.tostring(tree))
                    screenshot("bulbs-" + mode + ".png")
                scroll_to("Advanced connection")
                tap("Advanced connection")
                scroll_to("Connect")
                tree = hierarchy()
                assert find(tree, "Manager URL") is not None
                assert find(tree, "Access token") is None, "Lighting has no authentication field"
                screenshot("bulbs-advanced.png")
                tap("Hide connection")
                scroll_to("Manage bulbs")
                tap("Manage bulbs")
                scroll_to("Find new bulbs")
                tap("Find new bulbs")
                scroll_to("Add to Bedroom")
                screenshot("bulbs-manage.png")
                assert find(hierarchy(), "Remove") is not None, "Saved bulb controls must be visible"
                assert find(hierarchy(), "Find new bulbs") is not None
                print("PASS: Advanced connection, Manage bulbs, Regular, Night, and Follow timetable captured from the running APK.")
                print("PASS: exactly one selected control per room; Follow is distinct from manual Night.")
            print("PASS: Preview APK installed/launched against the isolated fixture; connected rooms render; timetable expands.")
            print("Connected screenshots use read-only sample data. No real TV/bulb control commands sent.")
        finally:
            server.shutdown()
            adb("reverse", "--remove", "tcp:8789")
        description = "Connected screens use read-only sample data. No real lights were controlled. This checks the interface, not discovery across your home Wi-Fi."

    if args.fixtures_only:
        if args.copy_states_to:
            copy_state_screenshots(args.output, args.copy_states_to)
            print("Extra fixture states copied to:", args.copy_states_to)
        print("Fixture screenshots:", args.output)
        return

    page = '''<!doctype html><meta charset="utf-8">
<title>UniRemote Preview — actual emulator screenshots</title>
<style>body{font:17px system-ui;background:#12141a;color:#eee;margin:32px}h1{font-size:25px}
.screens{display:flex;gap:28px;align-items:flex-start;flex-wrap:wrap}figure{margin:0;max-width:360px}
img{width:100%;border:1px solid #555;border-radius:16px}figcaption{margin:12px 0;font-weight:bold}
p{color:#c9cbd3;max-width:900px}a{color:#9bd}</style>
<h1>UniRemote Preview — running in Android 15</h1>
<p>Actual screenshots from the compiled app in an Android emulator, not a design mockup.
PREVIEW_DESCRIPTION</p>
<p><a href="UniRemote-Preview.apk" download>Download unpublished UniRemote Preview APK</a>.
It installs beside the normal app without replacing it. Nothing has been released.</p>
<div class="screens">
<figure><figcaption>Connected — default screen</figcaption><a href="bulbs-connected.png"><img src="bulbs-connected.png"></a></figure>
<figure><figcaption>Only after tapping Edit timetable</figcaption><a href="bulbs-timetable.png"><img src="bulbs-timetable.png"></a></figure>
</div>'''
    (args.output / "index.html").write_text(page.replace("PREVIEW_DESCRIPTION", description))
    shutil.copy2(args.apk, args.output / "UniRemote-Preview.apk")
    print("Review page:", args.output / "index.html")


if __name__ == "__main__":
    main()
