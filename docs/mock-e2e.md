# GUI end-to-end testing with mock lights

Verify Android GUI changes against **simulated WiZ bulbs** and the **real**
`butler/wiz_butler.py` manager, in a **disposable** emulator. No real bulbs,
household manager or everyday emulator are involved.

```sh
just mock-lights scenario --build   # build, boot, run the scripted proof (leaves it running)
just mock-lights down               # stop mocks + disposable emulator
```

(`just mock-lights …` = `python3 tools/mock_e2e.py …`.) Results and screenshots:
`/tmp/uniremote-mock-e2e/index.html` (plus `results.json`; logs in `run/`).

## Interactive use (agents)

```sh
python3 tools/mock_e2e.py up [--build] [--rooms 'Living room=2,Bedroom=1'] [--new 1] [--offline Bedroom] [--window]
python3 tools/mock_e2e.py state                 # simulated bulb power/dimming/temp/online (--json)
python3 tools/mock_e2e.py tree                  # visible texts/content-descs (--xml for full tree)
python3 tools/mock_e2e.py tap 'Manage bulbs'    # by exact text or content-desc (--contains)
python3 tools/mock_e2e.py tap-in 'Living room' Night   # a label inside one room card
python3 tools/mock_e2e.py tap 'Living room on / off'   # room power button
python3 tools/mock_e2e.py wait '2 bulbs  ·  Night'     # (--contains, --timeout)
python3 tools/mock_e2e.py scroll [--up | --top | --to LABEL]
python3 tools/mock_e2e.py shot my-change --caption 'What this shows'   # adds to index.html
python3 tools/mock_e2e.py bulb Bedroom --offline     # or --online/--on/--off; room or MAC
python3 tools/mock_e2e.py status | down
```

`up` (re)starts the mocks, resets only the Preview app's data on the disposable
emulator and opens the Bulbs tab connected to the mock. Defaults: Living room
(2 bulbs, on, Night), Bedroom (1 bulb, offline), 1 undiscovered bulb for
**Find new bulbs**. Timetable is off by default so state does not depend on the
clock (`--timetable` enables it). For scripted checks, import
`tools/android_ui.py` (`Android`: hierarchy/wait/tap/scroll/screenshot) and
`tools/mock_e2e.py` (`bulb_state`, `manager_status`, `section`, `shot`).
The manager is the real code, so a new GUI feature needing a new manager
endpoint is exercised end-to-end too.

## How it works

- `tools/mock_lights.py`: stateful bulbs, each bound to its own `127.0.0.11+`
  address on one UDP port, answering `getPilot`, `setPilot`, `setState`,
  `getSystemConfig`, `registration`. `127.0.0.10` stands in for the broadcast
  address; online bulbs reply to discovery from their own address. Loopback HTTP
  control API: `GET /bulbs`, `POST /bulbs/<mac|room>`.
- `wiz_butler.py --test-loopback-bulbs --test-bulb-port P --broadcast 127.0.0.10
  --listen 127.0.0.1 --state <temp>`: the test-only mode. Production defaults
  (port 38899, LAN-only bulb IPs, Bonjour) are unchanged when the flag is absent.
- Emulator: AVD `uniremote-preview` on `emulator-5580`, headless, `-read-only`
  (disk changes discarded). `adb reverse tcp:8789` reaches the mock manager;
  seeded prefs pin the app to it, with a service name that prevents NSD
  switching to the household manager.

## Safety

- Test mode refuses non-loopback `--listen`/`--broadcast`, the household state
  file, and any non-127/8 bulb IP; its UDP client drops any non-loopback target
  before opening a socket, and Bonjour is never started.
- The simulator binds only 127/8 and ignores non-loopback senders.
- Only the `uniremote-preview` AVD is started/killed; `uniremote-pixel-8a` is refused.
