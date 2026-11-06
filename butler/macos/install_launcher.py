#!/usr/bin/env python3
"""Build a user-local Mac app; --install replaces the old login LaunchAgent.

Requires Apple's Command Line Tools, not an Apple Account or App Store login.
Does not grant network permission: the user must approve macOS's own prompt.
"""

import argparse
import datetime
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time

BUNDLE_ID = "com.uniremote.lights"


def application_info(script):
    return {"CFBundleIdentifier": BUNDLE_ID, "CFBundleName": "Butler Lights",
            "CFBundleDisplayName": "Butler Lights", "CFBundleExecutable": "ButlerLights",
            "CFBundlePackageType": "APPL", "CFBundleVersion": "1", "CFBundleShortVersionString": "1.0",
            "LSMinimumSystemVersion": "13.0", "LSUIElement": True,
            "NSLocalNetworkUsageDescription": "Find and control your WiZ light bulbs on the home network, including their timetable.",
            "NSBonjourServices": ["_uniremote._tcp"],
            "ButlerManagerScript": str(script)}


def login_job(home, app):
    return {"Label": "com.uniremote.wiz", "ProgramArguments": ["/usr/bin/open", "-W", "-g", str(app)],
            "AssociatedBundleIdentifiers": [BUNDLE_ID], "RunAtLoad": True, "KeepAlive": True,
            "ThrottleInterval": 10, "StandardOutPath": str(home / "Library/Logs/com.uniremote.wiz-launcher.log"),
            "StandardErrorPath": str(home / "Library/Logs/com.uniremote.wiz-launcher.log")}


def stop_running_app(app):
    # open -W is only a waiter: unloading it does not necessarily quit the app.
    # Match the exact executable, then request its graceful SIGTERM cleanup.
    executable = str(app / "Contents/MacOS/ButlerLights")
    listing = subprocess.check_output(["/bin/ps", "-axo", "pid=,comm="], text=True)
    for line in listing.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or parts[1] != executable:
            continue
        pid = int(parts[0])
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            # Upgrade recovery for the first launcher version: AppKit could
            # suspend its quit callback after Python had already exited. Close
            # ONLY that exact, now-childless wrapper; never orphan a manager.
            remaining = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid=,comm="], text=True)
            processes = [row.strip().split(None, 2) for row in remaining.splitlines()]
            same_app = any(len(row) == 3 and row[0] == str(pid) and row[2] == executable for row in processes)
            has_child = any(len(row) == 3 and row[1] == str(pid) for row in processes)
            if same_app and not has_child:
                print("Closing idle launcher after its manager exited.")
                os.kill(pid, signal.SIGKILL)
            else:
                raise SystemExit("Previous launcher did not quit; no second instance will be started")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Replace the existing manager login job and open the app")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This launcher is for macOS only")
    home = Path.home()
    script = Path(__file__).resolve().parents[1] / "run-butler.sh"
    app = home / "Applications/Butler Lights.app"
    if not script.is_file():
        raise SystemExit("Manager run script not found")
    app.parent.mkdir(parents=True, exist_ok=True)
    if app.exists():
        with (app / "Contents/Info.plist").open("rb") as source:
            existing = plistlib.load(source)
        if existing.get("CFBundleIdentifier") != BUNDLE_ID or existing.get("ButlerManagerScript") != str(script):
            raise SystemExit("Existing app has a different identity/path; refusing to replace it")
        # Keep the same signed executable and UUID across manager updates.
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(app)], check=True)
        print("Keeping existing launcher identity:", app)
    else:
        with tempfile.TemporaryDirectory(prefix="butler-lights-build-", dir=app.parent) as temp:
            staging = Path(temp) / "Butler Lights.app"
            binary = staging / "Contents/MacOS/ButlerLights"
            binary.parent.mkdir(parents=True)
            with (staging / "Contents/Info.plist").open("wb") as output:
                plistlib.dump(application_info(script), output)
            subprocess.run(["/usr/bin/xcrun", "swiftc", "-O", "-o", str(binary), str(Path(__file__).with_name("Launcher.swift"))], check=True)
            subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", "--identifier", BUNDLE_ID, str(staging)], check=True)
            subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(staging)], check=True)
            staging.rename(app)
        print("Built locally signed app:", app)
    if not args.install:
        print("Build only. Use --install to switch the manager login job.")
        return
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / "com.uniremote.wiz.plist"
    if plist.exists():
        with plist.open("rb") as source:
            old = plistlib.load(source)
        if old.get("Label") != "com.uniremote.wiz":
            raise SystemExit("Unexpected existing job identity")
        backup = home / ".config/butler-setup" / ("launcher-before-" + datetime.datetime.now().strftime("%Y%m%dT%H%M%S"))
        backup.mkdir(parents=True, mode=0o700)
        shutil.copy2(plist, backup / plist.name)
        print("Previous login job backed up:", backup)
        loaded = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/com.uniremote.wiz"], capture_output=True)
        if loaded.returncode == 0:
            subprocess.run(["/bin/launchctl", "bootout", f"gui/{os.getuid()}", str(plist)], check=True)
    stop_running_app(app)
    with plist.open("wb") as output:
        plistlib.dump(login_job(home, app), output)
    subprocess.run(["/usr/bin/plutil", "-lint", str(plist)], check=True)
    subprocess.run(["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], check=True)
    print("Login startup now opens Butler Lights.app. Approve its Local Network prompt on this Mac.")
    print("Existing credentials, bulbs, timetable and holds were not changed.")


if __name__ == "__main__":
    main()
