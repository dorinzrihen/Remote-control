# Lighting validation

The home LAN is trusted: no lighting authentication or credential entry.
A sole discovered manager connects automatically; several managers allow selection.
Advanced connection is an optional manual URL fallback.

## What to check

- The Bulbs dot is green only after a successful manager status response within
  five seconds; otherwise it is grey, including while checking. Individual bulb
  failures and timetable enabled/disabled state do not set its color.
- `Connected · 2 bulbs` describes manager access and saved inventory, not two
  responsive bulbs. Zero bulb acknowledgements must report a bulb-level failure,
  not a manager outage; uncertain requests must not be described as never applied.
- Regular, Night and Follow timetable are mutually exclusive, derived from
  persisted manager state and fresh observations, not tap memory. Following may
  show the current physical preset in room status without selecting a second
  button. Mixed/unknown state must not claim a known preset.

The fake-bulb/HTTP and Android checks are listed in [testing.md](testing.md).
Relevant sources are `butler/test_*.py`, `app/src/test/`, and the controlled-response
indicator UI test in `app/src/androidTest/java/com/dorin/remote/ManagerConnectionIndicatorTest.kt`.
Unit tests do not run that instrumented UI test or prove physical scheduling.

## Screenshot fixtures: no household connection

With a built Preview APK and a **disposable, booted emulator**:

```sh
python3 tools/android_preview.py --serial emulator-5554 --fixtures-only
```

Replace the serial with that emulator's actual serial. The script resets Preview
data, seeds a loopback-only read-only sample manager before opening Bulbs, and
blocks switching to household discovery. Regular/Night/Follow screenshots in
`.local/preview/fixture/` are sample UI evidence, not real-manager or bulb tests.
Do not target the everyday emulator if you want to preserve its settings.

## Real LAN: read-only connection check

With a built Preview APK, a disposable booted emulator and the manager available:

```sh
python3 tools/android_lan_preview.py --serial emulator-5554 --manager-url http://10.100.102.19:8788
```

This helper uses the checkout's `.local/build-tools/android-sdk/platform-tools/adb`.
Use the actual emulator serial and current manager URL. The URL is a readback
assertion, never entered into the app. It resets only Preview emulator data,
checks zero-input discovery/connection, reads `/v1/status`, inspects saved discovery
settings and read-only timetable/advanced views, and compares inventory, timetable
and holds before/after. It never taps light controls or saves configuration.
PNG/XML evidence and the unpublished APK are saved in `.local/preview/live/`.

This does not validate mode transitions or schedule execution. For everyday
settings-preserving development use [emulator.md](emulator.md); for the required
actual Pixel 8a home-Wi-Fi checks use [testing.md](testing.md).
