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
   Hold **Remove** to delete one from the manager; removal does not turn it off.
   These operations work with the timetable enabled or disabled.
5. Open **Edit timetable**, choose Night/Day times, home IANA timezone and polling
   interval, then **Save timetable**. The timetable switch changes only scheduling, not the
   connection or ownership. Manual commands/status still require the manager
   when the timetable is off. Save preserves bulbs and manual holds and sends no
    light command. After an unconfirmed Save, reconnect before retrying.

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
including bulb identities, timetable and manual holds. Updating the existing Mac
manager with the same state path preserves its old configuration and holds; no
phone list upload or migration is needed. Run one manager per home/state file.
Older Android apps and other controllers can bypass its bookkeeping.

## Behavior and limitations

- Defaults: Night **21:00–06:00**, **20%, 2700K**; Regular **100%, 6500K**.
  Times (including minutes) and home timezone are editable. Daylight saving uses
  that timezone; ambiguous boundaries fire once and spring gaps normalize forward.
- Saved bulbs are polled even when scheduling is disabled. Default interval is
  **1 second**, editable **1–300 seconds**, including query time; timeouts can
  overrun it. Timetable boundaries wake the loop sooner. IP rediscovery runs
  every minute; new bulbs still require explicit Add.
- When enabled, each Night/Day boundary or detected off/unreachable → on event
  applies the current preset to on, unheld bulbs. Off/unreachable bulbs are skipped.
  Startup, adding a bulb and settings Save establish a baseline, not a preset
  write. An already-on bulb may wait for a later On event, boundary or Follow.
- **On/Off/Regular/Night** (including the on/off toggle) persist manual holds until
  the **next timetable boundary**, surviving restart. **On** selects the current
  home-time preset and **also creates a hold**; it does not resume automatic mode.
  Only **Follow timetable** (`AUTO`) explicitly clears a hold, applies the current
  preset to on bulbs and leaves off bulbs off. It requires an enabled timetable.
  Observed external colour/brightness changes while already on also create holds
  when scheduling is enabled.
- Every write checks the bulb's MAC at its current IP. Blink is serialized with
  scheduling, preserves holds and attempts to restore the original power/preset;
  a failed restore is reported for inspection. Disabling scheduling is not needed
  for discovery, adding, removal or Blink.
- Manager outages fail visibly: **no UDP fallback and no phone evening alarm**.
  The old Android receiver only cancels leftover alarms on upgrade/startup; it
  never schedules or controls lights.
- Wall power restoration must include boot/Wi-Fi reconnection before correction.
  A network outage looks like power loss; fast off/on cycles between polls and
  changes during fades can be missed. There is no guaranteed wall-On latency.
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
| `POST /v1/config` | Timetable only: `enabled`, `night`, `morning`, `timezone`, `pollSeconds` |
| `POST /v1/discover` | `{}`; returns `discovered` observations and `status`; does not add bulbs |
| `POST /v1/bulbs/add` | `{mac, ip, room}`; verifies identity and persists the bulb |
| `POST /v1/bulbs/remove` | `{mac}`; removes the saved bulb/hold, without a light command |
| `POST /v1/bulbs/blink` | `{mac}`; identifies a saved or manager-discovered bulb |
| `POST /v1/room` | `{room, mode}`; `REGULAR`, `NIGHT`, `OFF`, `ON`, `TOGGLE` or `AUTO` |

Status includes `config` (with manager-owned `bulbs`), MAC-keyed `pilots`,
`systemConfigs` (read-only hardware/firmware), `observedAt` (last successful read,
Unix seconds), `errors`, `holds`, plus `lastPoll`, `statusAt` and `native:false`.
An unreachable/MAC-mismatched bulb loses its current pilot, but retains its last
successful observation time. Android rejects mismatched/error pilots and ages
over `max(5, pollSeconds × 3)` seconds; unknown/stale is **not** reported as off.
If HTTP fails, Android clears current pilots and reports the manager unavailable.
POST config never replaces bulbs: a differing `bulbs` list is rejected; even an
old client's identical list is not adopted. Add/remove use the dedicated endpoints.

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
