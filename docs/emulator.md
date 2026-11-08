# Everyday Android development

From the repository in an ordinary desktop terminal:

```sh
just emulator dev
just emulator stop
just emulator status
```

`dev` builds the current unpublished **UniRemote Preview** debug app, starts or
reuses a **visible Google Android Emulator**, installs the APK and opens it.
The dedicated device is **uniremote-pixel-8a**, using Google's official **Pixel 8a**
hardware profile (not a renamed Pixel 7), with Android 15 Google APIs.
Run `dev` again after code changes: the same app and device are updated, retaining
settings and data. `stop` closes only this device and retains its data. An existing
headless instance of this device is restarted visibly, also retaining data.
Other emulators and USB phones are never installation/stop targets. No fixture
data, app clearing, device wiping, automatic watching, publication or light commands.
Build failures stop before installation. Emulator startup/boot waits are bounded.

### Real TV discovery

The emulator has real unicast access to the home LAN, but its virtual router
does not forward SSDP multicast. That can make TV scans empty even while a real
TV answers discovery from the host computer. `dev` starts a small **read-only TV
discovery bridge**, bound only to host loopback and forwarded only into this AVD
with `adb reverse`. Each LG/Samsung scan makes fresh, real SSDP queries from the
host; no TV IP or synthetic device list is hardcoded. Connection/pairing still
goes directly from Android to the real TV after you choose Connect. The helper
never pairs or sends power, volume, input or other remote-control commands.

This bridge exists only in debug emulator builds; debug phones and release apps
keep native discovery. Android TV/Xiaomi mDNS discovery is unchanged. Without
the helper (for example, launching from Android Studio alone), the debug app
falls back to native discovery. `stop` also stops the bridge; rerunning `dev`
reuses it, so there is no extra command, installed service or viewer. The host
must itself be on the TV's LAN. This makes the emulator useful for real-TV
development, but does not validate a physical phone's multicast/Wi-Fi behavior.

The older `uniremote-preview` Pixel 7 screenshot-test device is left untouched.
Do not run fixture/reset screenshot scripts against the everyday device if you
want to keep its app settings. A fresh app may first show TV setup: choose **Done**,
then the **Bulbs** tab to review automatic LAN discovery. Emulator testing
does not replace physical-phone testing on home Wi-Fi.

## One-time setup

**This Ubuntu desktop is ready:** `just` is installed at `~/.local/bin/just`,
already on PATH; the existing local SDK/JDK and KVM permissions are sufficient.
No sudo, Android Studio installation or account is needed.

On another computer, install [just](https://github.com/casey/just#installation)
and Python 3. The recipe uses `python3` on Linux/macOS and `python` on Windows
(ensure `python --version` works; otherwise install Python and add it to PATH).
For example, macOS with Homebrew: `brew install just python`; Windows:
`winget install --id Casey.Just --exact` and `winget install --id Python.Python.3.13 --exact`.
Reopen the terminal after changing PATH. Alternatively run the helper directly:
`python3 tools/emulator.py dev` (Windows: `python tools/emulator.py dev`).

Use Android Studio's **SDK Manager** to install:

- SDK Tools: **Android SDK Platform-Tools**, **Android Emulator** and
  **Android SDK Command-line Tools (latest)**.
- SDK Platforms → **Show Package Details** → Android 15 (API 35):
  **Google APIs x86_64 System Image** on Intel/AMD, or **Google APIs ARM 64 v8a
  System Image** on Apple Silicon. Accept Google's SDK licenses when prompted.
- JDK 17, or set `JAVA_HOME` to Android Studio's bundled `jbr` directory.

With command-line tools already configured, the image installation is explicitly:
`sdkmanager "system-images;android-35;google_apis;x86_64"`
(replace `x86_64` with `arm64-v8a` on Apple Silicon).
The helper never downloads a system image automatically. Gradle may download its
ordinary build dependencies on a new machine. Linux needs working `/dev/kvm`
access; Windows needs Android Emulator's supported hardware virtualization enabled.

SDK discovery checks `ANDROID_HOME`, `ANDROID_SDK_ROOT`, `local.properties`
(`sdk.dir`), the standard Android Studio location, then this checkout's
`.local/build-tools/android-sdk`. Standard locations:

- Linux: `~/Android/Sdk`
- macOS: `~/Library/Android/sdk`
- Windows: `%LOCALAPPDATA%\Android\Sdk`

Java discovery checks `JAVA_HOME`, system Java, common Android Studio `jbr`
locations, then `.local/build-tools/java/jdk-17*`. Set `JAVA_HOME` explicitly for
nonstandard installations. No shell configuration is rewritten.

The AVD uses the normal Android AVD home (`~/.android/avd`, or your existing
`ANDROID_AVD_HOME` override), so Android Studio **Device Manager** can also open it.
Do not create a different device under the reserved `uniremote-pixel-8a` name.
SDK errors explain the missing component; emulator logs are in
`.local/emulator/emulator.log`. No additional viewer or launcher is installed.

Verified live on Ubuntu; macOS/Windows discovery and command selection have
unit tests but have not been run live there.

Helper tests: `python3 -m unittest discover -s tools -p 'test_emulator*.py' -v`.
