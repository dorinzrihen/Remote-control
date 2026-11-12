# Agent instructions

- For GUI changes, verify end-to-end with the mock lights harness
  ([docs/mock-e2e.md](docs/mock-e2e.md)):
  `just mock-lights scenario --build`, then drive/check your change with
  `python3 tools/mock_e2e.py tap|tap-in|wait|tree|state|shot …`, and finish with
  `just mock-lights down`. Screenshots: `/tmp/uniremote-mock-e2e/index.html`.
  In the final message, inline the key screenshots as markdown images, each
  followed by a full-size `file://` link (see the global image instructions).
- For the lock-screen TV widget (or anything else needing Android 16 / a simulated TV), use
  `python3 tools/lockscreen_widget_demo.py scenario --build` (disposable AVD `uniremote-android16`
  on `emulator-5584`, mock LG TV on loopback; details in
  [docs/lockscreen-widget.md](docs/lockscreen-widget.md)), and finish with `… down`.
  Media: `~/uniremote-lockscreen-widget-demo/index.html`. Never send commands to real TVs.
- Never target the everyday emulator `uniremote-pixel-8a` (no resets, installs
  of test data or wipes); the harness uses only the disposable `uniremote-preview`.
- Never send commands to real bulbs or the household lighting manager.
- Checks: `./gradlew testDebugUnitTest testReleaseUnitTest assembleDebug`,
  `python3 -m unittest discover -s butler`,
  `python3 -m unittest discover -s tools -p 'test_*.py'`.
