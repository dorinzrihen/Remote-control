# Credential-free lighting validation

The lighting API intentionally trusts access to the configured home LAN. No
lighting password/token, six-digit code or identity challenge is used. This is
unrelated to TV pairing or OpenCode/Tailscale authentication.

`Connected · 2 bulbs` means the manager API is reachable, not that both bulbs
respond. A successful manager response with zero bulb acknowledgements is a
bulb-level failure: the app reports the affected room and keeps manager status
connected. Unconfirmed requests do not claim that the manager is down or that
the command was never applied. Regression tests simulate these cases without
sending real light commands.

The small dot next to **Bulbs** is green only after a fresh successful manager
status response. It is grey on opening/checking, after a failed request, or when
the last success is over five seconds old. Individual bulb errors and timetable
enabled/disabled state do not change it. Its accessibility label describes the
connection state. The indicator's emulator UI test uses controlled HTTP-client
responses, including failure, without touching a real manager or saved settings.

Run fake-bulb/HTTP tests (no hardware writes):

```sh
python3 -m unittest discover -s butler -v
JAVA_HOME=$PWD/.local/build-tools/java/jdk-17.0.21+9 ANDROID_HOME=$PWD/.local/build-tools/android-sdk ./gradlew testDebugUnitTest testReleaseUnitTest assembleDebug assembleRelease
```

With the dedicated Android 15 emulator booted and the LAN manager running:

```sh
python3 tools/android_lan_preview.py
```

This installs the separate `com.dorin.uniremote.preview` debug app, clears its
emulator-only data, opens Bulbs and verifies automatic discovery/connection with
**zero entered fields**. The manager URL option is only a readback assertion;
it is never entered into the app. The script reads `/v1/status` without credentials,
asserts the saved discovered URL/service name and absence of a token, opens the
read-only timetable/advanced views, and checks inventory, timetable and holds are
unchanged. It never taps a light, Save, Blink or bulb-inventory action.

Actual UI screenshots and XML are saved in `.local/preview/live/`:
`bulbs-setup`, `bulbs-connected`, `bulbs-timetable`, `bulbs-advanced`. Setup may
already be connected because there is no onboarding step to wait for. The copied
`UniRemote-Preview.apk` is unpublished, installs beside v1.7, and disables public
update prompts. Compilation and emulator evidence are not physical-phone testing.

Earlier screenshots showing a pairing code or token are obsolete. The older
`tools/android_preview.py --live-butler-ssh` pairing workflow is obsolete; use
`tools/android_lan_preview.py` for this flow. Its old authenticated sample fixture
also needs adapting before reuse. Gallery assembly is independent of validation.
Follow still has no distinct active-mode marker; this change does not add one.

Only a genuinely different manager remains subject to the existing schedule
ownership rule: disable and Save the old manager's timetable before switching.
Fresh installs, an unchanged URL, and the same saved Bonjour service name at a
changed address do not require approval. Service names are trusted LAN metadata,
not an identity proof. Several discovered managers are shown for selection.
