# WiZ lighting manager

The manager is the **sole bulb owner**: discovery, reads, identification flashes,
room commands and automatic scheduling run here. Android uses home-LAN HTTP
only, never direct WiZ UDP. This is **not native WiZ Rhythms**; see the
[hardware investigation](../docs/wiz-rhythms.md). Requires Python 3.11+ and system
timezone data. Keep the computer awake and connected to the bulb LAN.

## Connect and configure

1. Copy `butler/` to the computer and reserve a stable LAN address.
2. Start with the computer's LAN IP and broadcast, for example:

   ```sh
   python3 butler/wiz_butler.py --listen 192.168.1.10 --broadcast 192.168.1.255
   ```

   Defaults: loopback listener, port `8788`, timetable disabled, no bulbs.
   Access to the configured home LAN is trusted: anyone who can reach this API
   can control lights and schedules. No password, token, code or approval is
   required. Do not expose it publicly or forward its port. The deployed Mac stays
   bound to `10.100.102.19:8788`; no firewall or Tailscale route is added.
3. In the updated Android app, open **Quick actions → Bulbs** on the same Wi-Fi.
   A sole macOS manager is discovered with Bonjour and connected automatically,
   including on a fresh install with no saved settings. If multiple managers are
   found, choose one by name. **Advanced connection** offers only an optional
   manual URL for platforms or networks blocking multicast. Existing saved
   lighting tokens are ignored. Connecting reads existing bulbs/settings without
   changing lights; old phone-saved bulbs are not imported. Android v1.7 lacks
   discovery; the separate unpublished Preview app has the new flow.
4. Open **Manage bulbs → Find new bulbs → Blink → room → Add** to register bulbs.
   **Rename** changes a saved bulb's name on the manager; bulbs given the same name
   form one room. Hold **Remove** to delete one from the manager; removal does not
   turn it off.
   These operations work with the timetable enabled or disabled.
5. Open **Edit timetable**, choose Night/Day times, home IANA timezone and polling
   interval, then **Save timetable**. The timetable switch changes only scheduling, not the
   connection or ownership. Manual commands/status still require the manager
    when the timetable is off. Save preserves bulbs and explicit manual intent;
    its next polling cycle uses the new timetable. After an unconfirmed Save,
    reconnect before retrying. A conflicting edit must be reloaded before saving.

### Discovery scope and LAN trust

macOS advertises `Butler Lights._uniremote._tcp.local.` with its actual HTTP port
and TXT metadata (`api=1`, `auth=none`, bound `address` when specific).
It uses the system DNS-SD library, adds no Python package dependency, retries
registration failures, and removes the advertisement when the process exits.
Loopback-only services are not advertised. Keep the configured LAN address valid
(for example with a router DHCP reservation); discovery does not change the bind.
Android uses NSD only while Bulbs is open, holds/releases a multicast lock, and
resolves managers serially. It does not broadcast WiZ commands.

mDNS and HTTP provide neither authentication nor encryption. This intentionally
trusts the home LAN, matching the household's requested lighting access policy.
OpenCode and Tailscale authentication are separate and unchanged.
Discovery does not traverse Tailscale or Wi-Fi client isolation automatically.

State is atomically saved at `~/.local/state/uniremote-wiz/state.json` (0600),
including bulb identities, timetable, manual holds and explicit desired intent.
Schema version 2 retains the old `config`/`holds` fields. Updating with the same
state path preserves configuration and legacy timestamp-only holds: their preset
is unknown, so the manager leaves their observed settings alone until the stored
expiry, including across restarts. It does not invent a preset during migration.
New explicit holds carry their request time and preset; timetable edits recompute
their expiry from that request against the edited timetable. Legacy holds retain
their original expiry because their request time is unknown. No phone upload is
needed. Run one manager per home/state file; keep a state backup before upgrading.

## Behavior and limitations

- Defaults: Night **21:00–06:00**, **20%, 2700K**; Regular **100%, 6500K**.
  Times (including minutes) and home timezone are editable. Daylight saving uses
  that timezone; ambiguous boundaries resolve once and spring gaps normalize forward.
- Saved bulbs are polled even when scheduling is disabled. Default interval is
  **1 second**, editable **1–300 seconds**, including query time; timeouts can
  overrun it. Timetable boundaries wake the loop sooner. IP rediscovery runs
  every minute; new bulbs still require explicit Add.
- Every cycle reads each saved bulb and compares it with the current desired
  settings: an explicit manual override, otherwise the editable timetable when
  enabled. On bulbs with a mismatch are corrected even at startup and arbitrary
  non-boundary times; matching bulbs receive no write. Timetable changes never
  request power: off bulbs stay off. Unreachable bulbs are read again next cycle.
  Add and Save themselves send no command, but the next poll reconciles on bulbs.
- **On/Regular/Night** (including the toggle's On action) persist their explicit
  desired settings until the **next configured timetable boundary**, surviving
  unreachable bulbs, lost acknowledgements and restart. **On** captures the current
  home-time preset; it does not resume automatic mode. As before, explicit On,
  Regular and Night requests can turn a bulb on. Their power-on request remains
  pending until a read verifies the desired state; thereafter only their preset
  is reconciled on already-on bulbs, so a later wall/software Off stays off.
  Preset intent remains stored while a bulb is off and is corrected when it is
  next observed on.
- **Off** (including the toggle's Off action) is a delivery request, not a sticky
  power guard. It stays pending through unreachability, failed writes and restart
  until a read confirms Off, or until the next timetable boundary expires it.
  Confirmation retires the Off override/hold: the bulb normally remains off, but
  a later physical/software On is allowed and its colour/brightness follows the
  current timetable when enabled. With the timetable disabled, no automatic
  preset is applied. An unconfirmed queued Off is not silently retargeted.
- **Follow timetable** (`AUTO`) clears explicit/legacy holds and pending power
  intent, applies the current preset to on bulbs and leaves off bulbs off. It
  requires an enabled timetable. Disabling the timetable stops automatic preset
  adjustments, not reads or reconciliation of unexpired explicit manual intent.
- Manual overrides now come **only from manager commands**, not inferred external
  colour/brightness changes. External changes are corrected to desired settings,
  not mistaken for a hold that suppresses correction. Other controllers/native
  automations must not compete with this sole-owner manager.
- Every mismatch is observed again next cycle regardless of the last write's
  result. A failed/ambiguous write does not consume intent. Writes are not blindly
  retransmitted within a UDP request; acknowledgement alone is not proof of the
  setting being applied. A fresh successful read does not clear an error while
  the desired mismatch remains unresolved.
- Expiry is effective even if a full/unwritable disk prevents durable cleanup.
  Reads and reconciliation continue; cleanup is retried after each cycle. Pending
  completion updates also do not block other bulbs. `persistenceError` and the
  existing per-bulb `errors` report the storage problem until a save succeeds;
  successful bulb reads do not clear it. Expired records are ignored after restart
  even if storage is still failing. As with any pending command, losing power
  before a delivery confirmation can be saved leaves its old pending record on
  disk; delivery cannot be distinguished from an unconfirmed request on restart.
- Every write checks the bulb's MAC at its current IP. Blink is serialized with
  scheduling, preserves holds and attempts to restore the original power/preset;
  a failed restore is reported for inspection. Disabling scheduling is not needed
  for discovery, adding, removal or Blink.
- Manager outages fail visibly: **no UDP fallback and no phone evening alarm**.
  The old Android receiver only cancels leftover alarms on upgrade/startup; it
  never schedules or controls lights.
- Wall power restoration must include boot/Wi-Fi reconnection before correction.
  A network outage looks like power loss; fast off/on cycles between polls can
  be missed. Fades that still mismatch on the next read are corrected again.
  There is no guaranteed wall-On latency.
- Live tests found that even `setState` without `state:true` can turn an off bulb
  on. Automatic writes use guarded `setPilot` with a fresh on-state check, but
  another controller can still race the read/write pair. Avoid competing native
  Rhythms or automation: no safe native timetable readback/disable was established.
  Unknown native/cloud configuration is preserved.

## HTTP contract

All endpoints are accessible without an Authorization header; POST bodies are JSON.
Legacy Authorization headers and `UNIREMOTE_TOKEN` are ignored. Pairing/identity
endpoints and the `--pair` command have been removed. Every response has
`Cache-Control: no-store`.

| Endpoint | Purpose |
|---|---|
| `GET /v1/status`, `GET /v1/config` | Same cached manager status; no direct bulb query per GET |
| `POST /v1/config` | Timetable fields; optional `expectedConfig` baseline for conflict protection |
| `POST /v1/discover` | `{}`; returns `discovered` observations and `status`; does not add bulbs |
| `POST /v1/bulbs/add` | `{mac, ip, room}`; verifies identity and persists the bulb |
| `POST /v1/bulbs/remove` | `{mac}`; removes the saved bulb/hold, without a light command |
| `POST /v1/bulbs/rename` | `{mac, room}`; changes the saved name and returns status, with no bulb traffic; holds, intents and timetable are untouched; unknown MAC or invalid name returns 400 |
| `POST /v1/bulbs/blink` | `{mac}`; identifies a saved or manager-discovered bulb |
| `POST /v1/room` | `{room, mode}`; `REGULAR`, `NIGHT`, `OFF`, `ON`, `TOGGLE` or `AUTO` |

Status includes `config` (with manager-owned `bulbs`), MAC-keyed `pilots`,
`systemConfigs` (read-only hardware/firmware), `observedAt` (last successful read,
Unix seconds), `errors`, `holds`, plus `lastPoll`, `statusAt` and `native:false`.
The additive `intents` map contains `{mode, createdAt, powerPending}` per explicitly
held MAC; legacy unknown holds have no entry. `holds` remains absolute Unix expiry
seconds for old/new clients' Follow indicators. An override is removed on the first
poll at/after expiry; no boundary event needs to have succeeded. If cleanup cannot
be saved, expired records may remain in status with past expiry timestamps but
have no effect. Confirmed Off holds are omitted immediately, even while durable
cleanup is pending, so Follow indicators do not show a retired override.
An unreachable/MAC-mismatched bulb loses its current pilot, but retains its last
successful observation time. Android rejects mismatched/error pilots and ages
over `max(5, pollSeconds × 3)` seconds; unknown/stale is **not** reported as off.
If HTTP fails, Android clears current pilots and reports the manager unavailable.
POST config never replaces bulbs: a differing `bulbs` list is rejected; even an
old client's identical list is not adopted. Add/remove/rename use the dedicated
endpoints.

`POST /v1/config` accepts `enabled`, `night`, `morning`, `timezone`, `pollSeconds`.
If supplied, `expectedConfig` must be an object containing **exactly those five
fields**, with the same validation as a timetable (including integer polling
seconds). Under the configuration lock, the manager compares it with the current
timetable only, not bulbs or observations. A stale baseline returns **409** with
`{"error":"Timetable changed on another device. Reload before saving."}` and
changes neither configuration, holds, intent nor the saved file. Malformed
baselines return 400. Omitting `expectedConfig` preserves legacy unconditional
Save behavior. Clients should reload after a conflict, not retry the stale form.

Room responses retain `{answered, total, errors}`. `answered` counts verified
matches/no-ops and acknowledged writes whose readback matches; a lost write ACK
still counts zero even if a subsequent read confirms delivery. It does not mean
the manager forgot a request: pending intent remains and future cycles reconcile.

## Service and upgrade

For macOS, create `~/.config/uniremote-wiz.env` from
`uniremote-wiz.env.example` (0600), setting the LAN IP/broadcast and absolute
Python 3.11+ path. With Apple's Command Line Tools installed, run:

```sh
python3 butler/macos/install_launcher.py --install
```

This builds a small native **Butler Lights.app** in `~/Applications`, backs up
and replaces the existing manager login job, and opens the app through macOS.
**On the Mac, choose Allow when Butler Lights asks for Local Network access.**
The Python manager remains the bulb controller; the app only launches/supervises
it and provides a named permission identity. No Apple Account, App Store login,
administrator privileges, privacy bypass or new Python dependency is required.

Why the app: macOS 15 can automatically allow LAN access from SSH/Terminal while
blocking the same Python program as a login background job. Thus a successful
SSH bulb query does not prove the background manager has permission. The app
includes a network-usage description; the login job associates itself with the
app. If denied, use **System Settings → Privacy & Security → Local Network**.
Verify real observations through `/v1/status`, not just HTTP service health.

The locally built app is ad-hoc signed, not Apple-issued Developer ID signed.
Keep this tested app artifact: the installer reuses it rather than recompiling
it on every manager update, preserving its executable identity. Rebuilding or
moving it may require permission validation again. This is a local installation,
not a promise of notarized distribution or identical behavior on every macOS.

The matching plist template is `com.uniremote.wiz.plist.example`; its paths must
be absolute. To stop the login job:

```sh
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.uniremote.wiz.plist"
```

Unload the job **and quit Butler Lights.app** before updating a running manager:
unloading the `open -W` waiter alone may leave the app running. The installer
handles both when run again with `--install`. Do not start a second Python
manager alongside the app.

This is a **login-only** user agent; paths must be absolute. Keep the Mac awake.
Boot-before-login and lid/sleep changes are outside this setup. Linux user-service
templates are also provided (`uniremote-wiz.service.example` and the env example).
Only the explicit `--install` command installs/loads the Mac login job. Running
the Python manager alone does not install a service or change sleep settings.

Before deliberately switching to a different manager, disable and Save the old manager's timetable, then
stop it. To move its state, copy `~/.local/state/uniremote-wiz/` while both managers
are stopped; never leave two schedulers running. A fresh state file starts disabled;
an upgrade reuses the stored enabled setting. Android retains that schedule-safety
restriction for a different manager, not for a fresh connection or rediscovery of
the same saved Bonjour service name at a changed address. Service names are LAN
metadata, not an identity challenge or security boundary. A legacy manually saved
URL is associated with its service name when discovered at that address.

## Validation

Run `python3 -m unittest -v` from `butler/`. Tests use fake bulbs and loopback HTTP,
not hardware. Before unattended use, supervise: both boundaries, off bulbs staying
off, wall-power recovery, manual On/preset holds across restart, Follow, discovery/
Blink/add/remove, credential-free HTTP, stale observations and manager outage.
Use dim test presets and restore the desired timetable afterward. Earlier hardware
tests exercised the compatible scheduling core, **not the complete manager-only
Android release on a phone**; see [validation scope](../docs/wiz-rhythms.md#implementation-and-validation-scope).
