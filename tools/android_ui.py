"""Shared adb + uiautomator helpers for driving UniRemote Preview in an emulator.

Used by android_preview.py (read-only fixture screenshots) and mock_e2e.py
(stateful mock lights). Only `emulator-*` serials are accepted.
"""

from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "com.dorin.uniremote.preview"
ACTIVITY = "com.dorin.remote.ui.MainActivity"
DEFAULT_ADB = ROOT / ".local/build-tools/android-sdk/platform-tools/adb"
MODE_LABELS = ("Regular", "Night", "Follow timetable")


def preferences(url="http://127.0.0.1:8789", service="Preview fixture only - never household"):
    # Active manager + deliberately different saved service name prevent NSD
    # from switching to the household manager, even if the fixture goes offline.
    return f'''<?xml version="1.0" encoding="utf-8"?>
<map><string name="butler_url">{url}</string>
<string name="butler_service_name">{service}</string>
<boolean name="butler_enabled" value="true" /></map>'''.encode()


def find(tree, label, exact=True):
    """First node whose text or content-desc equals (or, exact=False, contains) label."""
    for node in tree.iter("node"):
        values = (node.get("text") or "", node.get("content-desc") or "")
        if (label in values) if exact else any(label in value for value in values):
            return node
    return None


def texts(tree):
    return [value for node in tree.iter("node")
            for value in (node.get("text"), node.get("content-desc")) if value]


def center(node):
    x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds")))
    return (x1 + x2) // 2, (y1 + y2) // 2


def selected_controls(tree):
    # Compose selectable(Role.RadioButton) exports Checked on the parent View,
    # with its text in a child; it is not Android's legacy Selected attribute.
    return [child.get("text") for node in tree.iter("node")
            if node.get("checkable") == "true" and node.get("checked") == "true"
            for child in node.iter("node") if child.get("text") in MODE_LABELS]


def room_card(tree, room):
    """Texts of the room card containing `room` (its title, status line and buttons)."""
    best = None
    for node in tree.iter("node"):
        children = list(node.iter("node"))
        if any(child.get("text") == room for child in children[1:]) and \
                any(child.get("content-desc") == f"{room} on / off" for child in children):
            if best is None or len(children) < len(list(best.iter("node"))):
                best = node
    return best


class Android:
    def __init__(self, serial, adb=DEFAULT_ADB, timeout=25):
        if not serial.startswith("emulator-"):
            raise ValueError("Use a dedicated emulator, never a physical phone")
        self.serial, self.adb_path, self.timeout = serial, Path(adb), timeout
        self._size = None

    def adb(self, *arguments, data=None, timeout=30, check=True):
        return subprocess.run([str(self.adb_path), "-s", self.serial, *map(str, arguments)],
                              input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, check=check).stdout

    def shell(self, *arguments, **kwargs):
        return self.adb("shell", *arguments, **kwargs)

    def hierarchy(self):
        # uiautomator occasionally fails while the UI is changing; retry briefly.
        for attempt in range(3):
            try:
                self.shell("uiautomator", "dump", "/sdcard/uniremote-ui.xml")
                return ET.fromstring(self.adb("exec-out", "cat", "/sdcard/uniremote-ui.xml"))
            except (subprocess.CalledProcessError, ET.ParseError):
                if attempt == 2:
                    raise
                time.sleep(0.5)

    def wait_for(self, label, timeout=None, exact=True):
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            tree = self.hierarchy()
            node = find(tree, label, exact)
            if node is not None:
                return tree, node
            time.sleep(0.3)
        raise RuntimeError(f"UI never showed {label!r}")

    def wait_until(self, predicate, description, timeout=None):
        """Poll the UI tree until predicate(tree) is truthy; return the tree."""
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            tree = self.hierarchy()
            if predicate(tree):
                return tree
            time.sleep(0.4)
        raise RuntimeError(f"UI never satisfied: {description}")

    def tap(self, label, exact=True):
        _tree, node = self.wait_for(label, exact=exact)
        self.tap_xy(*center(node))

    def tap_xy(self, x, y):
        self.shell("input", "tap", x, y)

    def size(self):
        if self._size is None:
            self._size = tuple(map(int, re.findall(rb"(\d+)x(\d+)", self.shell("wm", "size"))[-1]))
        return self._size

    def scroll(self, up=False):
        width, height = self.size()
        start, end = (0.35, 0.78) if up else (0.78, 0.35)
        self.shell("input", "swipe", width // 2, int(height * start), width // 2, int(height * end), "350")

    def scroll_to(self, label, attempts=8, exact=True, up=False):
        for _ in range(attempts):
            tree = self.hierarchy()
            if find(tree, label, exact) is not None:
                return tree
            self.scroll(up=up)
        raise RuntimeError(f"Could not scroll to {label!r}")

    def scroll_top(self):
        # "Bulbs" is both the tab label and the pane title; the title is the top.
        def at_top():
            return sum(node.get("text") == "Bulbs" for node in self.hierarchy().iter("node")) >= 2
        for _ in range(6):
            if at_top():
                return
            self.scroll(up=True)
        if not at_top():
            raise RuntimeError("Could not scroll to the top of the Bulbs tab")

    def screenshot(self, path):
        image = self.adb("exec-out", "screencap", "-p")
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Emulator did not return a PNG")
        Path(path).write_bytes(image)
        return Path(path)

    def prepare(self):
        """Wake, unlock and disable animations for stable automation."""
        self.adb("wait-for-device", timeout=90)
        self.shell("input", "keyevent", "KEYCODE_WAKEUP")
        self.shell("wm", "dismiss-keyguard")
        for setting in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
            self.shell("settings", "put", "global", setting, "0")

    def install_fresh(self, apk, prefs):
        """Install Preview, clear ONLY its data and seed prefs before the first launch."""
        self.adb("install", "-r", Path(apk).resolve(), timeout=120)
        self.shell("pm", "clear", PACKAGE)
        self.shell("am", "force-stop", PACKAGE)
        self.adb("shell", "run-as", PACKAGE, "sh", "-c", "'mkdir -p shared_prefs; cat > shared_prefs/uniremote.xml'", data=prefs)

    def launch(self):
        self.shell("am", "start", "-n", f"{PACKAGE}/{ACTIVITY}")

    def open_bulbs(self):
        self.launch()
        # Fresh app: TV setup first. Right after a cold boot the first tap can be
        # swallowed, so retry until the tab bar is really there.
        for attempt in range(4):
            tree, node = self.wait_for("Done")
            self.tap_xy(*center(node))
            try:
                self.wait_for("Bulbs", timeout=8)
                break
            except RuntimeError:
                if attempt == 3:
                    raise
        self.tap("Bulbs")
