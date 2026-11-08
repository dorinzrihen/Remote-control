# Test before releasing

## Local Preview

```sh
just emulator dev
just emulator stop
```

`dev` builds and opens **UniRemote Preview** in the visible Pixel 8a emulator.
Repeat it to update the same app/window with settings preserved; `stop` retains
data. See [emulator setup and discovery](emulator.md). The host TV-discovery
bridge is debug-emulator-only, not a substitute for phone Wi-Fi testing.

For a phone APK, run `./gradlew assembleDebug` with JDK 17 and the Android SDK
configured. Install `app/build/outputs/apk/debug/app-debug.apk` on the phone.
Preview uses the separate package `com.dorin.uniremote.preview`, installs beside
UniRemote 1.7 with separate settings, and disables public update prompts.
No production signing key or published release is needed.

## GUI end-to-end with mock lights

```sh
just mock-lights scenario --build
just mock-lights down
```

Runs the real Preview APK in the disposable `uniremote-preview` emulator against
the real lighting manager driving simulated bulbs on loopback, checks power,
Regular/Night, offline and discovery, and saves screenshots to
`/tmp/uniremote-mock-e2e/`. See [mock lights e2e](mock-e2e.md) for interactive commands.

## Actual Pixel 8a on home Wi-Fi

- [ ] Install Preview without replacing the working UniRemote app.
- [ ] In TV setup, scan for the real TV and check Connect using its normal TV
  approval flow. Emulator discovery alone does not validate phone multicast.
- [ ] Open the **Bulbs** tab. With one LAN manager, connection should be
  automatic with zero entered fields and no lighting authentication.
- [ ] Check the manager dot: green after a recent successful status response,
  grey while unavailable/checking. A bulb failure is not a manager outage.
- [ ] Confirm the saved bulb list and timetable match the household manager.
  Inspect without saving changes or running bright test commands.
- [ ] Check that Regular, Night and Follow timetable are mutually exclusive;
  the selection must reflect persisted manager state after reopening, not the
  last tapped button. When following, only Follow is selected, even if the room
  status describes the current Night/Regular preset. Unknown/mixed state must
  not invent a selection. Read-only inspection cannot prove mode transitions.

See [lighting validation](lighting-lan-testing.md) for fixtures versus real-LAN
evidence. Physical-phone and schedule-behavior checks remain release gates;
screenshots and passing unit tests do not establish that scheduling bugs are fixed.

## Automated checks and release gate

```sh
./gradlew testDebugUnitTest testReleaseUnitTest assembleDebug assembleRelease
python3 -m unittest discover -s butler -v
python3 -m unittest discover -s tools -p 'test_*.py' -v
```

Use the SDK/JDK setup in [emulator.md](emulator.md) if Gradle cannot find them.
Record actual-phone results and unresolved failures before approving a release.
The Release workflow's `dry_run` builds and checks signing without publishing,
but uploads no APK artifact. Use Preview for review; do not release just to test.
