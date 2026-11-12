#!/usr/bin/env python3
"""Lock-screen TV widget proof on a DISPOSABLE Android 16 emulator against a SIMULATED LG TV.

  up          create (if missing) and boot the uniremote-android16 AVD headless, switch on the
              lock-screen widget hub, start tools/mock_tv.py on 127.0.0.1:3000, install Preview
              pointed at the mock (10.0.2.2 = host loopback) and set the screen-lock PIN
  add-widget  add the "TV volume & arrows" widget to the lock-screen hub (enters the PIN once,
              as a real phone asks for it to edit the hub)
  scenario    up + add-widget, then lock the phone and tap Vol +, Vol -, Up, Down, Left, Right
              on the lock screen WITHOUT unlocking; checks every command in the mock TV's log
  press KEY…  tap widget buttons on the locked hub (vol_up vol_down up down left right)
  tv | tree | shot NAME | down

Artifacts (screenshots, recording, GIFs, index.html): ~/uniremote-lockscreen-widget-demo
(override: UNIREMOTE_LOCKSCREEN_DEMO_DIR). Only the uniremote-android16 AVD is ever started,
changed or stopped; the everyday uniremote-pixel-8a and uniremote-preview AVDs are refused.
"""

import argparse
import html
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import android_ui  # noqa: E402
from android_ui import Android, center, find  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
AVD = "uniremote-android16"
REFUSED_AVDS = ("uniremote-pixel-8a", "uniremote-preview")
CONSOLE_PORT = 5584  # adb only auto-discovers emulators on console ports 5554-5584
SERIAL = f"emulator-{CONSOLE_PORT}"
API = "android-36.1"  # Android 16 QPR2: the first release with lock-screen widgets on phones
PIN = "1234"
PACKAGE = android_ui.PACKAGE
APK = ROOT / "app/build/outputs/apk/debug/app-debug.apk"
TV_PORT = 3000  # WebOsClient always uses ws://<ip>:3000
TV_HOST_FROM_EMULATOR = "10.0.2.2"
OUT = Path(os.environ.get("UNIREMOTE_LOCKSCREEN_DEMO_DIR", Path.home() / "uniremote-lockscreen-widget-demo"))
RUN = OUT / "run"
SESSION = RUN / "session.json"
WIDGET_NAME = "TV volume & arrows"

# The emulator image ships the hub code (aconfig communal_hub / glanceable_hub_v2 are on) but, unlike
# a Pixel, not the device overlay that turns it on. These runtime overlays + the user setting do.
HUB_OVERLAYS = (
    ("hubfw", "android", "android:bool/config_glanceableHubEnabled"),
    ("hubsysui", "com.android.systemui", "com.android.systemui:bool/config_communalServiceEnabled"),
    ("hubswipe", "com.android.systemui", "com.android.systemui:bool/config_swipeToOpenGlanceableHub"),
)

# Widget button -> what the mock TV logs for it.
BUTTONS = {
    "vol_up": ("TV volume up", ("ssap", "audio/volumeUp")),
    "vol_down": ("TV volume down", ("ssap", "audio/volumeDown")),
    "up": ("Up", ("pointer", "UP")),
    "down": ("Down", ("pointer", "DOWN")),
    "left": ("Left", ("pointer", "LEFT")),
    "right": ("Right", ("pointer", "RIGHT")),
}


class Error(RuntimeError):
    pass


# ---------------------------------------------------------------- pure helpers (unit-tested)

def require_disposable(name):
    if name != AVD or name in REFUSED_AVDS:
        raise Error(f"Refusing to touch AVD {name!r}; only the disposable {AVD} is used")
    return name


def fix_avd_ini(text, api=API):
    """Old avdmanager versions write target=android-0 for "36.1"-style images. The emulator then
    misconfigures graphics and SurfaceFlinger crash-loops (hasReadColorBufferDma assertion)."""
    lines = [line for line in text.splitlines() if not line.startswith("target=")]
    return "\n".join(lines + [f"target={api}"]) + "\n"


def tune_config(text):
    settings = {"hw.ramSize": "4096", "hw.keyboard": "yes", "hw.gpu.enabled": "yes", "hw.gpu.mode": "swiftshader_indirect"}
    out, seen = [], set()
    for line in text.splitlines():
        key = line.split("=", 1)[0]
        if key in settings:
            line, _ = f"{key}={settings[key]}", seen.add(key)
        out.append(line)
    out += [f"{k}={v}" for k, v in settings.items() if k not in seen]
    return "\n".join(out) + "\n"


def tv_commands(state, since=0.0):
    """Mock TV log -> [("ssap", "audio/volumeUp"), ("pointer", "UP"), ...] after `since`."""
    result = []
    for c in state.get("commands", []):
        if c.get("t", 0) < since:
            continue
        if c.get("source") == "pointer":
            result.append(("pointer", (c.get("payload") or {}).get("name")))
        elif c.get("source") == "ssap" and c.get("command") != "register":
            result.append(("ssap", c.get("command")))
    return result


def widget_nodes(tree):
    """resource-id suffix (w_vol_up, …) -> node, for the widget's buttons currently on screen."""
    nodes = {}
    for node in tree.iter("node"):
        rid = node.get("resource-id") or ""
        if rid.startswith(PACKAGE + ":id/w_"):
            nodes[rid.split(":id/", 1)[1]] = node
    return nodes


def preferences():
    # LG TV = the mock. The lighting fields mirror mock_e2e's fixture so NSD never picks the household manager.
    return f'''<?xml version="1.0" encoding="utf-8"?>
<map><string name="lg_ip">{TV_HOST_FROM_EMULATOR}</string>
<string name="butler_url">http://127.0.0.1:9</string>
<string name="butler_service_name">Preview fixture only - never household</string>
<boolean name="migrated_stremio_app" value="true" /></map>'''.encode()


# ---------------------------------------------------------------- SDK / emulator

class Sdk:
    def __init__(self):
        import emulator
        self.device = emulator.Device()  # SDK/JDK discovery only
        self.env = self.device.env
        self.sdk = self.device.sdk
        self.adb = self.device.adb

    def run(self, *args, check=True, timeout=60, input=None):
        return subprocess.run([str(a) for a in args], env=self.env, check=check, timeout=timeout, input=input,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def avd_dir(self):
        home = Path(self.env.get("ANDROID_AVD_HOME") or Path.home() / ".android/avd")
        return home / f"{AVD}.avd", home / f"{AVD}.ini"

    def ensure_avd(self):
        abi = "arm64-v8a" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
        image = f"system-images;{API};google_apis;{abi}"
        if not (self.sdk / "system-images" / API / "google_apis" / abi / "system.img").exists():
            raise Error(f'Missing the Android 16 QPR2 image. Install it once (about 2 GB):\n  sdkmanager "{image}"')
        folder, ini = self.avd_dir()
        if not ini.exists():
            managers = sorted((self.sdk / "cmdline-tools").glob("*/bin/avdmanager"), key=lambda p: p.parent.parent.name != "latest")
            if not managers:
                raise Error("Install Android SDK Command-line Tools (latest).")
            self.device.java()
            self.run(managers[0], "create", "avd", "--name", AVD, "--package", image, "--device", "pixel_8a", input="no\n")
            print(f"Created {AVD} (Pixel 8a profile, {image}).", flush=True)
        ini.write_text(fix_avd_ini(ini.read_text()))
        config = folder / "config.ini"
        config.write_text(tune_config(config.read_text()))

    def serials(self):
        return self.device.serials()

    def avd_name(self, serial):
        result = self.run(self.adb, "-s", serial, "emu", "avd", "name", check=False, timeout=10)
        lines = result.stdout.split()
        return lines[0] if result.returncode == 0 and lines else None

    def start(self, window=False, wipe=False):
        if wipe and SERIAL in self.serials():
            self.stop()
        if SERIAL in self.serials():
            require_disposable(self.avd_name(SERIAL))
            print(f"Reusing {AVD} on {SERIAL}", flush=True)
        else:
            self.ensure_avd()
            for lock in self.avd_dir()[0].glob("*.lock"):
                lock.unlink()  # left behind by a killed emulator
            args = [self.device.emulator, "-avd", AVD, "-port", CONSOLE_PORT, "-no-snapshot", "-no-audio",
                    "-no-boot-anim", "-gpu", "swiftshader_indirect", "-no-metrics"] + ([] if window else ["-no-window"]) \
                + (["-wipe-data"] if wipe else [])
            RUN.mkdir(parents=True, exist_ok=True)
            with (RUN / "emulator.log").open("ab") as log:
                subprocess.Popen([str(a) for a in args], env=self.env, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
            print(f"Booting {AVD} on {SERIAL} ({'windowed' if window else 'headless'})…", flush=True)
            deadline = time.monotonic() + 120
            while SERIAL not in self.serials():
                if time.monotonic() > deadline:
                    raise Error(f"{AVD} did not appear in adb; see {RUN / 'emulator.log'}")
                time.sleep(1)
            require_disposable(self.avd_name(SERIAL))
        deadline = time.monotonic() + 300
        while self.run(self.adb, "-s", SERIAL, "shell", "getprop", "sys.boot_completed", check=False).stdout.strip() != "1":
            if time.monotonic() > deadline:
                raise Error(f"{AVD} did not finish booting")
            time.sleep(2)

    def stop(self):
        if SERIAL not in self.serials():
            return False
        require_disposable(self.avd_name(SERIAL))
        self.run(self.adb, "-s", SERIAL, "emu", "kill", check=False)
        deadline = time.monotonic() + 30
        while SERIAL in self.serials() and time.monotonic() < deadline:
            time.sleep(1)
        return True


def device(sdk=None):
    sdk = sdk or Sdk()
    if SERIAL not in sdk.serials():
        raise Error(f"{AVD} is not running. Run: python3 tools/lockscreen_widget_demo.py up")
    require_disposable(sdk.avd_name(SERIAL))
    return Android(SERIAL, sdk.adb)


def sh(d, *args, check=False, timeout=30):
    return d.shell(*args, check=check, timeout=timeout).decode(errors="replace")


# ---------------------------------------------------------------- mock TV

def http_json(url, body=None, timeout=5):
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST" if data is not None else "GET")
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def tv_state():
    return http_json(f"http://127.0.0.1:{TV_PORT}/state")


def start_tv():
    try:
        tv_state()
        print("Reusing the mock TV on 127.0.0.1:3000", flush=True)
        return None
    except OSError:
        pass
    RUN.mkdir(parents=True, exist_ok=True)
    with (RUN / "mock-tv.log").open("ab") as log:
        tv = subprocess.Popen([sys.executable, str(ROOT / "tools/mock_tv.py"), "--port", str(TV_PORT), "--volume", "12"],
                              cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 10
    while True:
        try:
            tv_state()
            return tv.pid
        except OSError:
            if time.monotonic() > deadline or tv.poll() is not None:
                raise Error(f"Mock TV did not start (is port {TV_PORT} busy?); see {RUN / 'mock-tv.log'}")
            time.sleep(0.2)


def stop_tv():
    if not SESSION.exists():
        return
    pid = json.loads(SESSION.read_text()).get("tvPid")
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except (OSError, TypeError):
        return
    if "mock_tv.py" in cmdline:
        os.kill(pid, signal.SIGTERM)


def wait_tv(predicate, description, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = tv_state()
        if predicate(state):
            return state
        time.sleep(0.25)
    state = tv_state()
    raise Error(f"Mock TV never showed {description}; volume={state['volume']} last={tv_commands(state)[-6:]}")


# ---------------------------------------------------------------- hub / lock screen

def hub_enabled(d):
    return "true" in sh(d, "cmd", "statusbar", "flag", "communal_service_enabled")


def enable_overlays(d):
    """Shell-owned fabricated overlays survive a reboot but can come back disabled (and SystemUI may
    disable them again while it sets up a fresh device), so (re)create, enable and verify each one."""
    for name, target, resource in HUB_OVERLAYS:
        overlay = f"com.android.shell:{name}"
        if overlay not in sh(d, "cmd", "overlay", "list"):
            sh(d, "cmd", "overlay", "fabricate", "--target", target, "--name", name, resource, "0x12", "0xffffffff")
        deadline = time.monotonic() + 30
        while f"[x] {overlay}" not in sh(d, "cmd", "overlay", "list"):
            if time.monotonic() > deadline:
                raise Error(f"Could not enable the runtime overlay {overlay}")
            sh(d, "cmd", "overlay", "enable", "--user", "0", overlay)
            time.sleep(1)


def enable_hub(d):
    """Root + runtime resource overlays + user setting, then restart SystemUI until the hub is on."""
    d.adb("root", check=False)
    deadline = time.monotonic() + 60
    while sh(d, "id", "-u").strip() != "0":  # adbd restarts as root
        if time.monotonic() > deadline:
            raise Error("adb root failed; a Google APIs (not Play Store) image is needed")
        time.sleep(1)
    d.shell("settings", "put", "secure", "glanceable_hub_enabled", "1", check=False)
    for attempt in range(5):
        enable_overlays(d)
        if hub_enabled(d):
            return
        print("Restarting SystemUI to switch on the lock-screen widget hub…", flush=True)
        sh(d, "pkill", "-f", "com.android.systemui$")
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and not hub_enabled(d):
            time.sleep(2)
        time.sleep(5)
    if not hub_enabled(d):
        raise Error("SystemUI did not come back with the hub enabled")


def set_pin(d):
    sh(d, "locksettings", "set-disabled", "false")
    if "verified successfully" in sh(d, "locksettings", "verify", "--old", PIN):
        return
    out = sh(d, "locksettings", "set-pin", PIN)
    if "set to" not in out.lower():
        raise Error(f"Could not set the PIN: {out.strip()}")


def kill_app(d):
    """Kill the app's process the way Android reclaims a background app (not a force-stop)."""
    d.shell("am", "kill", PACKAGE, check=False)
    time.sleep(1)


def device_locked(d):
    return "deviceLocked=1" in sh(d, "dumpsys", "trust")


def lock(d):
    d.shell("input", "keyevent", "KEYCODE_SLEEP", check=False)
    time.sleep(2)
    d.shell("input", "keyevent", "KEYCODE_WAKEUP", check=False)
    time.sleep(1.5)
    if not device_locked(d):
        raise Error("The emulator is not securely locked")


def open_hub(d, timeout=20):
    """From the lock screen, swipe in from the right edge until the hub shows our widget."""
    width, height = d.size()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tree = d.hierarchy()
        if "w_vol_up" in widget_nodes(tree):
            return tree
        if find(tree, "Let’s go") is not None:
            d.tap_xy(*center(find(tree, "Let’s go")))
            time.sleep(1.5)
            continue
        d.shell("input", "keyevent", "KEYCODE_WAKEUP", check=False)
        d.shell("input", "swipe", width - 5, height * 55 // 100, width // 5, height * 55 // 100, 350, check=False)
        time.sleep(1.5)
    raise Error("The lock-screen hub never showed the UniRemote widget")


def unlock(d):
    deadline = time.monotonic() + 60
    while "isKeyguardShowing=true" in sh(d, "dumpsys", "window"):
        if time.monotonic() > deadline:
            raise Error("Could not unlock with the PIN")
        d.shell("input", "keyevent", "KEYCODE_WAKEUP", check=False)
        d.shell("wm", "dismiss-keyguard", check=False)
        time.sleep(1.5)
        if find(d.hierarchy(), "Enter PIN") is not None:
            d.shell("input", "text", PIN, check=False)
            d.shell("input", "keyevent", "KEYCODE_ENTER", check=False)
        time.sleep(2)


def widget_on_hub(d):
    lock(d)
    try:
        open_hub(d, timeout=12)
        return True
    except Error:
        return False


def add_widget(d, on_picker=None):
    """Adds the widget to the lock-screen hub unless it is there. Setup only, so it takes the
    layout-independent path: unlock with the PIN (a phone asks for it to edit the hub too), open
    SystemUI's hub editor, then the launcher's lock-screen widget picker. on_picker(d) runs once
    while the picker shows the UniRemote widget."""
    if widget_on_hub(d):
        print("The widget is already on the lock-screen hub.", flush=True)
        return
    unlock(d)
    d.shell("am", "start", "-n", "com.android.systemui/.communal.widgets.EditWidgetsActivity", check=False)
    time.sleep(2)
    deadline = time.monotonic() + 90
    searched = False
    while time.monotonic() < deadline:
        tree = d.hierarchy()
        label = lambda text: find(tree, text)  # noqa: E731
        if "w_vol_up" in widget_nodes(tree) and label("Done") is not None:
            d.tap_xy(*center(label("Done")))
            time.sleep(2)
            if widget_on_hub(d):
                print("Added the widget to the lock-screen hub.", flush=True)
                return
            raise Error("The widget was added but is not on the lock-screen hub")
        if label("Enter PIN") is not None:
            d.shell("input", "text", PIN)
            d.shell("input", "keyevent", "KEYCODE_ENTER")
        elif label(f"Add {WIDGET_NAME} widget") is not None:
            if on_picker:
                on_picker(d)
                on_picker = None
            d.tap_xy(*center(label(f"Add {WIDGET_NAME} widget")))
        elif len(titles := [n for n in tree.iter("node") if n.get("text") == WIDGET_NAME]) >= 2:
            # UniRemote's row is expanded: tap the widget preview's title to select it.
            d.tap_xy(*center(max(titles, key=lambda n: center(n)[1])))
        elif label("UniRemote Preview") is not None:
            d.tap_xy(*center(label("UniRemote Preview")))
        elif label("Search") is not None and not searched:
            d.tap_xy(*center(label("Search")))
            time.sleep(1)
            d.shell("input", "text", "UniRemote")
            searched = True
        elif label("Got it") is not None:
            d.tap_xy(*center(label("Got it")))
        elif label("Add widget") is not None:
            d.tap_xy(*center(label("Add widget")))
        time.sleep(1.5)
    raise Error("Could not add the widget to the lock-screen hub; see `python3 tools/lockscreen_widget_demo.py tree`")


def press(d, names, pause=1.0):
    tree = open_hub(d)
    nodes = widget_nodes(tree)
    for name in names:
        d.tap_xy(*center(nodes[f"w_{name}"]))
        time.sleep(pause)


# ---------------------------------------------------------------- media + report

def media(kind, name, caption, results=None):
    index = RUN / "media.json"
    items = json.loads(index.read_text()) if index.exists() else []
    items = [i for i in items if i["file"] != name] + [{"file": name, "caption": caption, "kind": kind}]
    index.write_text(json.dumps(items, indent=2))
    write_index(results)


def shot(d, name, caption):
    OUT.mkdir(parents=True, exist_ok=True)
    d.screenshot(OUT / f"{name}.png")
    media("image", f"{name}.png", caption)
    return OUT / f"{name}.png"


class Recording:
    """adb screenrecord of the emulator display (stopped with SIGINT so the MP4 is finalized)."""

    def __init__(self, d, name):
        self.d, self.name = d, name
        d.shell("rm", "-f", "/sdcard/uniremote-demo.mp4", check=False)
        self.process = subprocess.Popen([str(d.adb_path), "-s", d.serial, "shell", "screenrecord", "--bit-rate", "4000000",
                                         "--time-limit", "120", "/sdcard/uniremote-demo.mp4"],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)

    def stop(self, caption):
        self.d.shell("pkill", "-INT", "screenrecord", check=False)
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
        time.sleep(1.5)
        mp4 = OUT / f"{self.name}.mp4"
        self.d.adb("pull", "/sdcard/uniremote-demo.mp4", mp4, timeout=60)
        media("video", mp4.name, caption)
        gif = make_gif(mp4)
        if gif:
            media("image", gif.name, caption + " (GIF)")
        return mp4


def ffmpeg():
    return os.environ.get("FFMPEG") or shutil.which("ffmpeg")


def make_gif(mp4, width=320, fps=8):
    tool = ffmpeg()
    if not tool:
        print("ffmpeg not found (set FFMPEG=/path/to/ffmpeg); skipping the GIF.", flush=True)
        return None
    gif = mp4.with_suffix(".gif")
    filters = f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse=dither=bayer"
    subprocess.run([tool, "-y", "-loglevel", "error", "-i", str(mp4), "-vf", filters, str(gif)], check=True, timeout=180)
    return gif


def write_index(results=None):
    OUT.mkdir(parents=True, exist_ok=True)
    index = RUN / "media.json"
    items = json.loads(index.read_text()) if index.exists() else []
    results_file = RUN / "results.json"
    if results is not None:
        results_file.write_text(json.dumps(results, indent=2))
    results = json.loads(results_file.read_text()) if results_file.exists() else []

    def figure(i):
        src = html.escape(i["file"])
        body = (f'<video src="{src}" controls muted></video>' if i["kind"] == "video"
                else f'<a href="{src}"><img src="{src}"></a>')
        return f'<figure><figcaption>{html.escape(i["caption"])}</figcaption>{body}</figure>'

    checks = "\n".join(f"<li>{html.escape(line)}</li>" for line in results)
    (OUT / "index.html").write_text(f'''<!doctype html><meta charset="utf-8">
<title>UniRemote lock-screen TV widget</title>
<style>body{{font:16px system-ui;background:#12141a;color:#eee;margin:28px}}
.s{{display:flex;gap:22px;flex-wrap:wrap}}figure{{margin:0;width:300px}}img,video{{width:100%;border:1px solid #555;border-radius:14px}}
figcaption{{margin:8px 0;font-weight:bold}}li{{margin:4px 0}}</style>
<h1>UniRemote lock-screen TV widget</h1>
<p>UniRemote Preview on the disposable {AVD} emulator (Android 16 QPR2, {API}), secure PIN lock,
against a simulated LG TV on 127.0.0.1:{TV_PORT}. No real TV.</p>
<ul>{checks}</ul><div class="s">{"".join(figure(i) for i in items)}</div>''')
    return OUT / "index.html"


# ---------------------------------------------------------------- commands

def up(args):
    sdk = Sdk()
    if args.build or not APK.exists():
        sdk.device.java()
        subprocess.run([str(ROOT / "gradlew"), "assembleDebug"], cwd=ROOT, env=sdk.env, check=True, timeout=900)
    RUN.mkdir(parents=True, exist_ok=True)
    tv_pid = start_tv()
    if tv_pid:
        SESSION.write_text(json.dumps({"tvPid": tv_pid}))
    sdk.start(window=args.window, wipe=args.wipe)
    d = device(sdk)
    d.adb("wait-for-device", timeout=90)
    d.shell("settings", "put", "system", "screen_off_timeout", "1800000", check=False)
    for setting in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
        d.shell("settings", "put", "global", setting, "0", check=False)
    enable_hub(d)
    set_pin(d)
    unlock(d)  # setup happens unlocked, like a user opening the app; the test locks again
    d.adb("install", "-r", APK, timeout=180)
    # Reset only the Preview app's TV settings to the mock fixture (the hub keeps its widget). Never
    # force-stop: Android 15+ then cancels the widget's PendingIntents until the app is opened again.
    d.adb("shell", "run-as", PACKAGE, "sh", "-c", "'mkdir -p shared_prefs; cat > shared_prefs/uniremote.xml'", data=preferences())
    kill_app(d)
    # Open the app once, as a user does to set up the TV; it connects to the mock TV.
    d.shell("am", "start", "-W", "-n", f"{PACKAGE}/{android_ui.ACTIVITY}", check=False, timeout=60)
    wait_tv(lambda s: s["clients"] >= 1, "the app connected", timeout=45)
    d.shell("input", "keyevent", "KEYCODE_HOME", check=False)
    print(f"UP: {AVD} on {SERIAL} (PIN {PIN}), lock-screen hub on, mock LG TV at 127.0.0.1:{TV_PORT} "
          f"(emulator: {TV_HOST_FROM_EMULATOR}).", flush=True)


def down(_args):
    stop_tv()
    stopped = Sdk().stop()
    print(f"DOWN: mock TV stopped; {AVD} {'stopped' if stopped else 'was not running'} (AVD and data kept).")


def scenario(args):
    up(args)
    d = device()
    for old in OUT.glob("*.*"):
        if old.suffix in (".png", ".mp4", ".gif"):
            old.unlink()
    (RUN / "media.json").unlink(missing_ok=True)
    (RUN / "results.json").unlink(missing_ok=True)
    results = []
    add_widget(d, on_picker=lambda dev: shot(dev, "00-picker", "Lock-screen widget picker (Android 16 hub): UniRemote's TV volume & arrows widget"))

    def ok(message):
        results.append(f"PASS {message}")
        print(f"PASS {message}", flush=True)
        write_index(results)

    d.shell("input", "keyevent", "KEYCODE_HOME", check=False)
    time.sleep(1)
    kill_app(d)  # the first tap must start the app process from cold
    cold = not sh(d, "pidof", PACKAGE).strip()
    lock(d)
    ok("Phone securely locked with a PIN (dumpsys trust: deviceLocked=1)"
       + ("; the app process was not running before the first tap" if cold else ""))
    shot(d, "01-locked", "Locked with a PIN: the normal lock screen")
    rec = Recording(d, "lockscreen-widget")
    open_hub(d)
    time.sleep(0.8)
    shot(d, "02-hub", "Swipe left on the lock screen: the widget hub with the TV widget (still locked)")
    before = tv_state()["volume"]
    mark = time.time()
    press(d, ["vol_up"], pause=0.3)
    wait_tv(lambda s: s["volume"] == before + 1, f"volume {before + 1}")
    d.wait_for(f"LG TV  ·  Volume {before + 1}", timeout=10)
    shot(d, "03-vol-up", f"After Vol +: the mock TV went {before} → {before + 1}; the widget label shows it")
    press(d, ["vol_up", "vol_down", "up", "down", "left", "right"], pause=1.0)
    expected = [BUTTONS[k][1] for k in ("vol_up", "vol_up", "vol_down", "up", "down", "left", "right")]
    state = wait_tv(lambda s: tv_commands(s, mark) == expected, "Vol + ×2, Vol −, Up, Down, Left, Right in order")
    time.sleep(1)
    shot(d, "04-after-all", "After Vol +, Vol −, Up, Down, Left and Right, still on the locked hub")
    rec.stop("Tapping every widget button on the locked hub")
    if not device_locked(d):
        raise Error("The phone got unlocked during the test")
    log = ", ".join(name for _, name in tv_commands(state, mark))
    ok(f"Every tap reached the mock TV while locked, in order: {log}")
    ok(f"Mock TV volume {before} → {state['volume']} (+2 −1); arrows arrived as pointer-socket buttons")
    ok("Still locked afterwards (deviceLocked=1); no unlock prompt appeared")
    # Idle long enough for Android to cache/freeze the app, then tap again: the widget must recover.
    d.shell("input", "keyevent", "KEYCODE_SLEEP", check=False)
    time.sleep(25)
    lock(d)
    mark, before = time.time(), tv_state()["volume"]
    press(d, ["vol_down", "right"], pause=0.5)
    state = wait_tv(lambda s: tv_commands(s, mark) == [BUTTONS["vol_down"][1], BUTTONS["right"][1]], "Vol − and Right after idling")
    ok(f"After 25 s with the screen off, Vol − and Right still arrived (volume {before} → {state['volume']})")
    if not device_locked(d):
        raise Error("The phone got unlocked during the test")
    path = write_index(results)
    print(f"SCENARIO PASSED. Results: {path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("up", "scenario"):
        p = sub.add_parser(name)
        p.add_argument("--build", action="store_true", help="assembleDebug first")
        p.add_argument("--window", action="store_true", help="show the emulator window")
        p.add_argument("--wipe", action="store_true", help=f"factory-reset the disposable {AVD} first")
    sub.add_parser("add-widget")
    sub.add_parser("down")
    sub.add_parser("tv")
    sub.add_parser("tree")
    p = sub.add_parser("press")
    p.add_argument("keys", nargs="+", choices=sorted(BUTTONS))
    p = sub.add_parser("shot")
    p.add_argument("name")
    p.add_argument("--caption", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "up":
            up(args)
        elif args.command == "scenario":
            scenario(args)
        elif args.command == "down":
            down(args)
        elif args.command == "add-widget":
            add_widget(device())
        elif args.command == "press":
            d = device()
            lock(d)
            press(d, args.keys)
            print(json.dumps(tv_commands(tv_state())[-len(args.keys):]))
        elif args.command == "tv":
            state = tv_state()
            print(json.dumps({k: state[k] for k in ("volume", "muted", "clients")} | {"last": tv_commands(state)[-10:]}, indent=2))
        elif args.command == "tree":
            for node in device().hierarchy().iter("node"):
                text = node.get("text") or node.get("content-desc")
                if text:
                    print(repr(text), node.get("resource-id") or "", node.get("bounds"))
        elif args.command == "shot":
            print(shot(device(), args.name, args.caption))
    except (Error, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
