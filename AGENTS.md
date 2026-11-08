# Agent instructions

- For GUI changes, verify end-to-end with the mock lights harness
  ([docs/mock-e2e.md](docs/mock-e2e.md)):
  `just mock-lights scenario --build`, then drive/check your change with
  `python3 tools/mock_e2e.py tap|tap-in|wait|tree|state|shot …`, and finish with
  `just mock-lights down`. Screenshots: `/tmp/uniremote-mock-e2e/index.html`.
- Never target the everyday emulator `uniremote-pixel-8a` (no resets, installs
  of test data or wipes); the harness uses only the disposable `uniremote-preview`.
- Never send commands to real bulbs or the household lighting manager.
- Checks: `./gradlew testDebugUnitTest testReleaseUnitTest assembleDebug`,
  `python3 -m unittest discover -s butler`,
  `python3 -m unittest discover -s tools -p 'test_*.py'`.
