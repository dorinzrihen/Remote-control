#!/usr/bin/env python3
"""Persistent Google Pixel 8a development device. No fixtures, data resets or downloads."""
import argparse
import contextlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
AVD = "uniremote-pixel-8a"
PACKAGE = "com.dorin.uniremote.preview"
ACTIVITY = "com.dorin.remote.ui.MainActivity"


class Error(RuntimeError):
    pass


def run(args, *, env=None, check=True, timeout=30, capture=True, input=None):
    result = subprocess.run([str(a) for a in args], cwd=ROOT, env=env,
                            text=True, input=input, timeout=timeout,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.STDOUT if capture else None)
    if check and result.returncode:
        raise Error(f"Command failed ({result.returncode}): {args[0]}\n{result.stdout or ''}")
    return result


def sdk_candidates(env, home, system, root=ROOT):
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if env.get(key):
            yield Path(env[key]).expanduser()
    props = root / "local.properties"
    if props.exists():
        for line in props.read_text().splitlines():
            match = re.match(r"\s*sdk\.dir\s*[=:]\s*(.*)", line)
            if match:
                # Java properties escapes Windows drive letters/backslashes/spaces.
                yield Path(re.sub(r"\\([\\: =])", r"\1", match[1]))
    if system == "Darwin":
        yield home / "Library/Android/sdk"
    elif system == "Windows":
        yield Path(env.get("LOCALAPPDATA", str(home / "AppData/Local"))) / "Android/Sdk"
    else:
        yield home / "Android/Sdk"
        yield home / "Android/sdk"
    yield root / ".local/build-tools/android-sdk"


def image_abi(machine):
    if machine.lower() in ("arm64", "aarch64"):
        return "arm64-v8a"
    if machine.lower() in ("amd64", "x86_64"):
        return "x86_64"
    raise Error(f"Unsupported emulator host architecture: {machine}")


class Device:
    def __init__(self):
        self.system = platform.system()
        self.env = os.environ.copy()
        self.home = Path.home()
        self.suffix = ".exe" if self.system == "Windows" else ""
        self.sdk = next((p for p in sdk_candidates(self.env, self.home, self.system)
                         if (p / ("platform-tools/adb" + self.suffix)).is_file()), None)
        if not self.sdk:
            raise Error("Android SDK not found. In Android Studio → SDK Manager install "
                        "Android SDK Platform-Tools and Android Emulator; set ANDROID_HOME "
                        "to the displayed SDK location. See docs/emulator.md.")
        self.env["ANDROID_HOME"] = str(self.sdk)
        self.env["ANDROID_SDK_ROOT"] = str(self.sdk)
        self.adb = self.sdk / ("platform-tools/adb" + self.suffix)
        self.emulator = self.sdk / ("emulator/emulator" + self.suffix)
        self.local = ROOT / ".local/emulator"
        self.local.mkdir(parents=True, exist_ok=True)

    def java(self):
        candidates = []
        if self.env.get("JAVA_HOME"):
            candidates.append(Path(self.env["JAVA_HOME"]))
        java = shutil.which("java")
        if java:
            candidates.append(Path(java).resolve().parent.parent)
        candidates += [Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home"),
                       Path(self.env.get("ProgramFiles", "C:/Program Files")) / "Android/Android Studio/jbr",
                       self.home / "android-studio/jbr", Path("/opt/android-studio/jbr")]
        candidates += sorted((ROOT / ".local/build-tools/java").glob("jdk-17*"))
        for candidate in candidates:
            if (candidate / ("bin/java" + self.suffix)).is_file():
                self.env["JAVA_HOME"] = str(candidate)
                self.env["PATH"] = str(candidate / "bin") + os.pathsep + self.env.get("PATH", "")
                return
        raise Error("Java not found. Install JDK 17 or set JAVA_HOME to Android Studio's jbr directory.")

    def adb_run(self, *args, **kwargs):
        return run([self.adb, *args], env=self.env, **kwargs)

    def serials(self):
        devices = self.adb_run("devices").stdout
        return [line.split()[0] for line in devices.splitlines()
                if re.match(r"^emulator-\d+\s", line)]

    def ours(self):
        matches = []
        for serial in self.serials():
            try:
                result = self.adb_run("-s", serial, "emu", "avd", "name", check=False, timeout=5)
            except subprocess.TimeoutExpired:
                continue
            if result.returncode == 0 and AVD in result.stdout.splitlines():
                matches.append(serial)
        if len(matches) > 1:
            raise Error(f"Multiple instances of {AVD} found; close duplicates in Device Manager first.")
        return matches[0] if matches else None

    def processes(self):
        if self.system == "Windows":
            args = ["powershell.exe", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'qemu|emulator' } | Select-Object -ExpandProperty CommandLine"]
        else:
            args = ["ps", "-ax", "-o", "args="]
        lines = run(args).stdout.splitlines()
        pattern = r"(?:-avd\s+|@)" + re.escape(AVD) + r"(?:\s|$|\")"
        return [line for line in lines if re.search(pattern, line) and
                ("qemu" in line or "emulator" in line)]

    def headless(self):
        processes = self.processes()
        if not processes:
            raise Error(f"Cannot verify {AVD}'s window mode. Run `just emulator stop`, then retry dev.")
        return any("-no-window" in p or "-headless" in p for p in processes)

    def stop(self, serial):
        # Only serials positively identified by adb emu avd name reach this method.
        self.adb_run("-s", serial, "emu", "kill", timeout=10)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if serial not in self.serials() and not self.processes():
                print(f"Stopped {AVD}; saved data retained.", flush=True)
                return
            time.sleep(1)
        raise Error(f"{AVD} did not stop within 45s. Close it in Device Manager and retry.")

    def ensure_avd(self):
        if not self.emulator.is_file():
            raise Error("Install Android Emulator in Android Studio → SDK Manager → SDK Tools.")
        names = run([self.emulator, "-list-avds"], env=self.env).stdout.splitlines()
        if AVD in names:
            return
        abi = image_abi(platform.machine())
        image = f"system-images;android-35;google_apis;{abi}"
        if not (self.sdk / "system-images/android-35/google_apis" / abi / "package.xml").exists():
            raise Error(f"Missing Android 15 Google APIs {abi} image. In Android Studio → "
                        "SDK Manager → SDK Platforms → Show Package Details install it, or run "
                        f'`sdkmanager "{image}"`. No image was downloaded automatically.')
        bat = ".bat" if self.system == "Windows" else ""
        managers = list((self.sdk / "cmdline-tools").glob("*/bin/avdmanager" + bat))
        managers.sort(key=lambda p: (p.parent.parent.name != "latest", str(p)))
        if not managers:
            raise Error("Install Android SDK Command-line Tools (latest) in SDK Manager → SDK Tools.")
        manager = managers[0]
        profiles = run([manager, "list", "device"], env=self.env).stdout
        if '"pixel_8a"' not in profiles:
            raise Error("Update Android SDK Command-line Tools (latest): official pixel_8a profile is missing.")
        run([manager, "create", "avd", "--name", AVD, "--package", image,
             "--device", "pixel_8a"], env=self.env, input="no\n")
        print(f"Created {AVD} using Google's Pixel 8a profile.", flush=True)

    def launch(self):
        if self.system == "Linux" and not (self.env.get("DISPLAY") or self.env.get("WAYLAND_DISPLAY")):
            raise Error("No graphical desktop session. Run `just emulator dev` in a desktop terminal.")
        # Software GPU also works on hosts whose graphics drivers are incompatible with the SDK.
        args = [str(self.emulator), "-avd", AVD, "-gpu", "swiftshader", "-no-metrics"]
        kwargs = {"start_new_session": True} if self.system != "Windows" else {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
        log = self.local / "emulator.log"
        with log.open("ab") as output:
            process = subprocess.Popen(args, env=self.env, cwd=ROOT, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, **kwargs)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise Error(f"Emulator exited ({process.returncode}); inspect {log}. No sudo needed by this command.")
            serial = self.ours()
            if serial:
                return serial
            time.sleep(1)
        raise Error(f"Emulator not reachable after 180s; inspect {log}.")

    def boot(self, serial):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                result = self.adb_run("-s", serial, "shell", "getprop", "sys.boot_completed",
                                      check=False, timeout=5)
                if result.returncode == 0 and result.stdout.strip() == "1":
                    return
            except subprocess.TimeoutExpired:
                pass
            time.sleep(1)
        raise Error(f"{AVD} ({serial}) did not boot in 180s. See {self.local / 'emulator.log'}.")

    def dev(self):
        self.java()
        # Build first: never install an old APK after a failed build.
        wrapper = "gradlew.bat" if self.system == "Windows" else "gradlew"
        run([ROOT / wrapper, "assembleDebug"], env=self.env, capture=False, timeout=900)
        self.ensure_avd()
        serial = self.ours()
        if serial and self.headless():
            print("Restarting the dedicated headless device with a visible window…", flush=True)
            self.stop(serial)
            serial = None
        if not serial:
            # A starting/offline process cannot safely be replaced or duplicated.
            if self.processes():
                deadline = time.monotonic() + 30
                while not serial and time.monotonic() < deadline:
                    serial = self.ours()
                    if not serial:
                        time.sleep(1)
                if not serial:
                    raise Error(f"{AVD} is running but ADB cannot identify it. Close it in Device Manager and retry.")
                if self.headless():
                    self.stop(serial)
                    serial = None
            serial = serial or self.launch()
        self.boot(serial)
        self.adb_run("-s", serial, "install", "-r", ROOT / "app/build/outputs/apk/debug/app-debug.apk", timeout=120)
        result = self.adb_run("-s", serial, "shell", "am", "start", "-W", "-n", f"{PACKAGE}/{ACTIVITY}")
        if "Error:" in result.stdout or "Status: ok" not in result.stdout:
            raise Error(f"Preview failed to launch:\n{result.stdout}")
        print(f"Preview open on visible Pixel 8a: {AVD} ({serial}). Data/settings retained.", flush=True)


@contextlib.contextmanager
def lock(path):
    """OS releases this lock even on interruption; concurrent dev cannot create two devices."""
    with path.open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise Error("Another emulator command is running; wait for it to finish.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("dev", "stop", "status"), nargs="?", default="dev")
    action = parser.parse_args().action
    try:
        device = Device()
        with lock(device.local / "command.lock"):
            if action == "dev":
                device.dev()
            else:
                serial = device.ours()
                if action == "stop" and serial:
                    device.stop(serial)
                elif serial:
                    print(f"{AVD}: {serial}, {'headless' if device.headless() else 'windowed'}")
                elif device.processes():
                    raise Error(f"{AVD} process exists but ADB is not ready; retry shortly or close in Device Manager.")
                else:
                    print(f"{AVD}: stopped (saved data retained)")
    except (Error, OSError, subprocess.TimeoutExpired) as exc:
        print(f"emulator: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; emulator data was not reset.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
