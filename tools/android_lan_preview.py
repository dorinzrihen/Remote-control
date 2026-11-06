#!/usr/bin/env python3
"""Validate zero-input live LAN discovery in the separate Preview emulator app.

Clears only Preview emulator data. Reads the real manager; never sends a POST or
touches light/timetable controls. Screenshots come from the actual running APK.
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.request import urlopen
import xml.etree.ElementTree as ET

PACKAGE = "com.dorin.uniremote.preview"


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--manager-url", default="http://10.100.102.19:8788", help="Readback assertion only; never entered into the app")
    parser.add_argument("--output", type=Path, default=root / ".local/preview/live")
    args = parser.parse_args()
    if not args.serial.startswith("emulator-"):
        parser.error("Use only the dedicated emulator, not a physical phone")
    adb_path = root / ".local/build-tools/android-sdk/platform-tools/adb"
    apk = root / "app/build/outputs/apk/debug/app-debug.apk"
    args.output.mkdir(parents=True, exist_ok=True)

    def status():
        with urlopen(args.manager_url + "/v1/status", timeout=10) as response:
            assert response.status == 200
            value = json.load(response)
            return {key: value[key] for key in ("config", "holds")}

    before = status()

    def adb(*arguments, timeout=30):
        return subprocess.run([str(adb_path), "-s", args.serial, *arguments],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, check=True).stdout

    def hierarchy():
        adb("shell", "uiautomator", "dump", "/sdcard/uniremote-lan-preview.xml")
        return ET.fromstring(adb("exec-out", "cat", "/sdcard/uniremote-lan-preview.xml"))

    def find(tree, label):
        return next((node for node in tree.iter("node")
                     if label in (node.get("text"), node.get("content-desc"))), None)

    def wait_for(label):
        deadline = time.monotonic() + 45
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

    def screenshot(name, tree):
        labels = [node.get("text", "") for node in tree.iter("node")]
        assert not any("Token" in text or "Pairing" in text or text == "Pair" for text in labels)
        assert not any(node.get("class") == "android.widget.EditText" for node in tree.iter("node")) or name in ("bulbs-timetable", "bulbs-advanced")
        image = adb("exec-out", "screencap", "-p")
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        (args.output / (name + ".png")).write_bytes(image)
        ET.ElementTree(tree).write(args.output / (name + ".xml"), encoding="utf-8")

    def scroll_to(label):
        for _ in range(8):
            tree = hierarchy()
            if find(tree, label) is not None:
                return tree
            width, height = map(int, re.findall(rb"(\d+)x(\d+)", adb("shell", "wm", "size"))[-1])
            adb("shell", "input", "swipe", str(width // 2), str(int(height * .78)),
                str(width // 2), str(int(height * .35)), "350")
        raise RuntimeError(f"Could not scroll to {label!r}")

    adb("wait-for-device", timeout=90)
    adb("install", "-r", str(apk), timeout=90)
    adb("shell", "pm", "clear", PACKAGE)
    adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
    adb("shell", "wm", "dismiss-keyguard")
    adb("shell", "am", "start", "-n", PACKAGE + "/com.dorin.remote.ui.MainActivity")
    tap("Done")
    tap("Quick actions")
    tap("Bulbs")
    tree, _ = wait_for("Advanced connection")
    assert find(tree, "Manager URL") is None
    screenshot("bulbs-setup", tree)
    tree, _ = wait_for("Connected · " + str(len(before["config"]["bulbs"])) + " bulbs")
    assert find(tree, "Manager URL") is None
    assert find(tree, "Save timetable") is None
    screenshot("bulbs-connected", tree)
    preferences = ET.fromstring(adb("exec-out", "run-as", PACKAGE, "cat", "shared_prefs/uniremote.xml"))
    values = {entry.get("name"): entry.text for entry in preferences}
    assert values["butler_url"] == args.manager_url
    assert values["butler_service_name"]
    assert not values.get("butler_token")
    tap("Edit timetable")
    tree, _ = wait_for("Night HH:MM")
    screenshot("bulbs-timetable", tree)
    tap("Hide timetable")
    scroll_to("Advanced connection")
    tap("Advanced connection")
    tree = scroll_to("Connect")
    assert find(tree, "Manager URL") is not None
    assert len([node for node in tree.iter("node") if node.get("class") == "android.widget.EditText"]) == 1
    screenshot("bulbs-advanced", tree)
    assert status() == before, "Manager inventory, timetable or holds changed during read-only validation"
    shutil.copy2(apk, args.output / "UniRemote-Preview.apk")
    print("PASS: fresh Preview emulator automatically discovered and connected to the real Mac.")
    print("Zero entered fields, no saved token, no pairing, no light-control or configuration commands.")
    print("Manager bulbs, timetable and holds unchanged. Actual UI screenshots:", args.output)


if __name__ == "__main__":
    main()
