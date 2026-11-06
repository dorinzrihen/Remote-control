# WiZ native Rhythms investigation

## Result (2026-11-05)

**Native timetable upload over local UDP is blocked on the initially tested bulb.**
This is evidence from this hardware/firmware, not an assumption imported from a
different model. Native scheduling through an authenticated WiZ cloud route is
not ruled out, but no usable authenticated route was established in this work.
Do not present the local lighting manager as native Rhythms.

Initially one powered/reachable bulb answered three LAN broadcasts:

| Read-only observation | Result |
|---|---|
| MAC suffix | `…fbba` |
| `getSystemConfig.moduleName` | `ESP24_SHRGBC_01` |
| `getSystemConfig.fwVersion` | `1.29.0` |
| Region | `eu` |
| `getModelConfig.cctRange` | `[2200,2700,6500,6500]` |
| Initial and post-probe pilot | on, 20%, 2700K, scene 0 |
| `getSchd`, `getSchdPset` | `-32601 Method not found` |
| `setSchd`, `setSchdPset` with **empty** `params` | `-32600 Invalid Request` |

During that investigation a second bulb answered: MAC suffix `…a582`, module
`ESP14_SHRGB1C_01`, firmware `1.38.0`. It was inventoried with read-only queries
and was **off**. At that stage no lighting or native scheduling writes had
been sent to it; the first bulb's native transport conclusion does not establish
support on this different module/firmware. No factory reset, registration, flash,
OTA, Wi-Fi change, cloud interception or valid configuration write was performed.
The readable system/user configuration and pilot matched before and after the
probes (apart from signal strength). This is not a backup of the unreadable
native timetable.

## Exact firmware evidence

Downloaded for **offline analysis only**:

`http://firmware.wiz.world/firmwares/ESP24_SHRGBC_01/1.29.0/wizlight.bin`

SHA-256:
`41804cb950f23685bfd75051707c9ba40876dd2b56020074a4c39ae200b83ec6`

The vendor endpoint served HTTP, not HTTPS. This hash identifies the analyzed
download; it is not a verified vendor signature or a dump read from the bulb.
The running module/version matches the download path. Never flash this artifact.

The ESP image contains RISC-V code at `0x42000020`, mapped from file offset
`0x30020`, and DROM at `0x3c180020`, file offset `0x20`.
Twelve-byte dispatch entries contain name pointer, handler pointer and flags:

| Method | Dispatch file offset | Handler | Flags |
|---|---|---|---|
| `setSchd` | `0x1414` | `0x4202f3a8` | `0x00000004` |
| `setSchdPset` | `0x1420` | `0x4200cc32` | `0x00000004` |
| `setState` | `0x1480` | `0x4200bc3c` | `0x00020206` |
| `setPilot` | `0x148c` | `0x4200bc70` | `0x00020206` |
| `getPilot` | `0x1498` | `0x4200bd84` | `0x00000606` |
| `getSystemConfig` | `0x14e0` | `0x4200dd12` | `0x00000606` |

The schedule setters lack the UDP-access byte present on working LAN methods;
the observed `Invalid Request` replies agree with the cloud-only interpretation
in the firmware research. A missing `getSchd` alone would **not** prove this.

Before sending the two empty-parameter probes, both handlers were disassembled
with Capstone 5.0.9 (RV32 + compressed instructions). With `{}`, neither handler
reaches a mutation: no `deleteAll` key, then no required `id`, so the handler
would return an invalid-parameter status even if dispatch allowed it. No `id`,
timestamps, deletion keys, guessed arrays or valid schedules were sent.

## Recovered timetable payload structure

The native rhythm handler `setSchdPset` parses a **single timetable point per
message**, not the standard `setPilot` shape and not a demonstrated array upload.
The following are actual key lookups in the matching firmware:

| Key | Handler behavior |
|---|---|
| `id` | required; stored as one byte (native rhythm/preset identity) |
| `confTs` | required; stored as a 32-bit value; synchronization semantics not fully traced |
| `pos` | required; packed decimal point index/count, not a plain minute-of-day |
| `days` | required array of exactly 7; nonzero entries become weekday-mask bits |
| `hrs`, `mins` | required; stored as bytes |
| `dura` | required; stored as 16 bits; units not verified |
| `mode` | required array of exactly 7 numbers; first 6 stored as bytes, last as 16 bits |
| `dim` | optional brightness byte |
| `type` | required string: `custom` or `circ` |
| `sType` | optional, only accepted for `circ`: `wake` or `sleep` |

At `0x4200ce56` onward, the handler computes `pos / 10 - 1` as the zero-based
point index. The persistence routine at `0x4202046a` uses `pos % 10` as the number
of points, copies 24-byte entries into a 120-byte staging buffer, and commits
when the last point arrives. Thus a two-point rhythm appears to use `pos:12`
and `pos:22`; the staging buffer appears to accommodate five points. These are
**static deductions**, not a validated upload recipe. Weekday ordering, mode
element meanings, duration units, activation and timezone synchronization still
need tracing or an authorized known-good cloud capture. No guessed complete
payload is included in the app.

`delete` and `deleteAll` also exist. **Never experiment with them.** In particular,
the separate `setSchd` handler tests for the *presence* of `deleteAll`, making even
`"deleteAll":false` unsafe. `setSchd` is a separate alarm/schedule handler: required
keys include `id`, `confTs`, `hrs`, `mins`, `days`; optional lookups include
`intent`, `ignore` (`ifOff`/`ifOn`), `next`, `dura`, `scene`, `temp`, `color`, `dim`.
Do not confuse alarms with the Rhythm timetable.

## Why not send the payload over MQTT?

The bulb is already associated with a WiZ home/room and cloud region. Discovering
those numeric IDs is **not authorization** to publish to its cloud MQTT connection.
The cited research's local MQTT technique involves redirecting/intercepting the
bulb's cloud traffic; it is not a supported LAN MQTT endpoint. No authenticated
WiZ app/cloud session or official cloud provisioning flow was available here.
No DNS/network interception, broker replacement or certificate modification was
attempted, because that would alter the existing environment and could damage
configuration synchronization.

The official local-control library documents pilot operations, not timetable
upload. `pywizlight` supports rejoining an already configured rhythm using plain
On; that does not provision a rhythm. Adding `schdPsetId` to a pilot command also
does not supply the timetable. Native cloud provisioning remains a possible
future research track with explicit account authorization and a configuration
export/readback strategy—not something this manager silently does.

## Reproduce without writes

```sh
python3 tools/wiz_inspect.py --broadcast 192.168.1.255 --output /private/path/inventory.json
python3 tools/wiz_inspect.py --ip 192.168.1.20
python3 tools/wiz_inspect.py --firmware /private/path/wizlight.bin
```

Substitute your bulb LAN's broadcast/address. The tool never sends setters.
Inventory output includes private device/home/room
identifiers; do not commit it. Firmware bytes and private raw replies from this
session are preserved in the repository's **git-ignored private**
`.local/wiz-investigation/` directory. They are not staged or published.

## Implementation and validation scope

- The [lighting manager](../butler/README.md) is now the sole bulb owner. Android
  uses authenticated HTTP for discovery, Blink, add/remove, status and room
  commands; it has no direct WiZ transport or evening alarm. The legacy receiver
  only cancels leftover alarms on upgrade/startup.
- The timetable toggle controls automatic scheduling only. Status/manual controls
  still use the manager when disabled. On uses the current home-time preset and
  creates a hold, like Regular/Night/Off; only Follow (`AUTO`) explicitly clears
  one before its next-boundary expiry. Save changes timetable fields, never
  overwrites bulbs from a phone list, and preserves holds without a light command.
- `GET /v1/status` and `/v1/config` return manager-owned bulbs, MAC-keyed pilots,
  read-only system configurations, observation timestamps and errors. Android
  treats stale/error/mismatched observations as unknown, not off. See the
  [HTTP contract](../butler/README.md#http-contract) for endpoints and freshness rules.
- Automated fake-bulb/loopback HTTP and Android JVM tests cover scheduling,
  authentication, persistence, DST, holds, identity/freshness checks, explicit
  inventory operations and manager-only behavior. These are not physical-bulb
  or installed-phone acceptance tests.
- Supervised live testing found a critical difference from the public research:
  on `ESP24_SHRGBC_01` / `1.29.0`, `setState` with a temperature/brightness preset
  **turns an off bulb on**, even without `state:true`. The manager was corrected
  to recheck that a bulb is on immediately before a `setPilot` write. Its own
  API commands are serialized, but an independent controller can still race
  that read/write pair; the local API has no tested atomic conditional write.
  Earlier supervised hardware checks passed against the compatible scheduling
  core, before the manager-only Android rewrite: actual manager process/API,
  manually configured real-time Night and Day transitions, manual overrides,
  resuming the timetable, software Off remaining off, and physical wall-power
  recovery. The final wall test observed power loss at 21:41:16 UTC and confirmed
  automatic correction at 21:41:35 UTC (the user confirmed success). That interval
  includes the requested 10 seconds with the switch off; the exact wall-On time
  was not instrumented, so it is not a measured 19-second correction delay.
  The tests used dimmed preset values, and restored the final starting state
  of 10% / 2200K. Temporary manager processes were stopped afterward; this is
  not evidence of full end-to-end testing of the new Android release. Default
  polling is one second, including query time; the completed wall test used
  two-second polling.
- A release APK has been built for the manager-only rewrite; build/unit-test
  success does **not** establish that the actual release has been installed and
  fully exercised on a phone. Release/signing procedures are in the
  [release guide](releases.md).
- The Mac manager deployment uses the two known bulbs, an enabled **21:00–06:00**
  timetable in **Asia/Jerusalem**, and **1-second** polling. Updating the same
  state file preserves prior configuration and holds. Its LaunchAgent remains
  login-only; boot/lid/sleep changes are outside this work. Manager URL/token
  entry remains manual: mDNS/Bonjour auto-discovery was explicitly deferred.

## Sources

- [Official local-control library](https://gitlab.com/wizlighting/wiz-local-control)
- [Firmware research](https://github.com/alxgmpr/wiz-re/blob/main/PROTOCOL.md)
- [Community library](https://github.com/sbidy/pywizlight)
- [WiZ: What are Rhythms?](https://faq.wizconnected.com/hc/en/3-wiz/faq/221-what-are-rhythms)
- [WiZ: enabling Rhythms](https://faq.wizconnected.com/hc/en/7-wiz-v2/faq/645-enabling-rhythms)
