# Optional laptop timetable

This is a **fallback**, not native WiZ Rhythms. See the
[actual-bulb investigation](../docs/wiz-rhythms.md) first. Nothing is installed,
started or enabled automatically. Requires Python 3.11+ and system timezone data.

## Start on the always-on laptop

1. Copy this repository (or just `butler/wiz_butler.py`) to the laptop. Reserve a
   stable LAN IP for the laptop. Keep it awake and connected to the bulb LAN.
2. Generate a secret: `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`.
   Set that value as `UNIREMOTE_TOKEN` in the laptop's environment. Do not commit it.
3. Start in the foreground, substituting the **laptop's** LAN IP and broadcast:

   ```sh
   python3 butler/wiz_butler.py --listen 192.168.1.10 --broadcast 192.168.1.255
   ```

   Defaults: loopback-only listen, port `8788`, timetable disabled, no bulbs.
   LAN binding is deliberate; do not bind/expose it on the public internet.
   HTTP carries the bearer token in cleartext: use only a trusted, isolated home
   LAN, or put the loopback listener behind an HTTPS reverse proxy. The Android
   client accepts HTTPS with a normally trusted certificate. No port forwarding.
   Limit the firewall to the phone/home subnet. WiZ UDP itself is unauthenticated.

4. Build/install the updated Android app. **Quick actions → Bulbs → Laptop
   timetable**: enter `http://192.168.1.10:8788` and the token, then **Load**.
   Choose Night/Day times, polling interval, the **home** IANA timezone, and toggle **Use laptop
   timetable**. **Save** uploads the remote's saved bulb list and settings to
   the laptop, not to bulb firmware. All timetable controls stay in this remote.
5. Use the supervised acceptance checklist below before leaving it running.
   Once satisfied, an optional user service template is provided; edit paths/IPs
   before installing it. This repository never runs `systemctl` for you.

State is atomically saved at `~/.local/state/uniremote-wiz/state.json` (0600).
It contains the timetable, bulb identities and manual holds, not a backup of
native bulb configuration. Run only one service instance per state file/home.
Use one controller phone; another old app version can issue uncoordinated UDP
commands. Disabling or killing the laptop does not rewrite native configuration.

## Behavior

- Defaults (not fixed times): Night **21:00–06:00**, **20%, 2700K**; Regular **100%, 6500K**.
  Both times, including minutes, and home timezone are editable in the remote.
  For example, setting **22:15 / 07:45** means 21:00 does nothing. Settings are
  persisted on the laptop and cached on the phone, then reloaded when you open
  the settings. Daylight saving is handled
  in that timezone; ambiguous boundary times fire once, spring gaps normalize
  forward. Prefer the default hours, away from DST transition hours.
- Polls saved bulbs at the configured interval: **1 second by default**, editable
  from **1–300 seconds**. Query time counts toward the interval rather than
  adding another full delay afterward; long timeouts can still overrun it.
  Saving settings wakes the polling
  loop immediately; timetable boundaries wake it earlier than the interval.
  It does not continuously force a preset. Rediscovers IPs
  every minute. A MAC-matched read is required before a write. Bulbs observed
  off or unreachable are skipped; see the independent-controller race below.
- At either timetable boundary, bulbs already on receive that period's preset.
  This adds a **Day-start transition** (default 06:00), unlike the original phone's evening-only job.
- On a detected off/unreachable → on transition, apply the time-appropriate preset.
  A wall-powered bulb must reconnect to Wi-Fi before this can happen, so the old
  preset can be visible briefly. The earlier 30-second estimate included bulb
  boot/Wi-Fi reconnection, not a 30-second software timer. Once reachable, a
  single healthy bulb is normally corrected within one polling cycle; this
  cannot guarantee three seconds measured from restoring wall power.
  This is not as immediate/reliable as native
  firmware scheduling.
- Automatic updates recheck that the bulb is on immediately before sending a
  preset. **Live testing found that `setState` also turns this firmware on**,
  even without `state:true`; it is not an atomic "only if on" operation. The
  manager uses guarded `setPilot` writes instead. Commands through its API are
  serialized, but another independent controller can still race the UDP
  read/write pair. WiZ provides no tested compare-and-set operation here.
- **Regular/Night/Off** buttons are serialized through the laptop and persist a
  manual hold until the **next timetable boundary**. They are not fought by each
  poll. Manual temperature/brightness changes observed from another controller
  while already on also create a hold. Holds survive daemon restart.
- **On** uses the laptop's home-time preset and rejoins the timetable.
  **Follow timetable** clears a hold and applies the current preset only to on
  bulbs; it leaves off bulbs off.
- Startup/settings Save establishes a baseline without changing existing lights.
  A bulb already on when the daemon starts is not corrected until a detected
  On, the next boundary, or Follow timetable. This preserves unknown overrides.
- Phone evening alarms are suspended while the fallback is selected. Manual
  commands fail visibly when the laptop is down; they do **not** silently fall
  back to UDP and bypass override bookkeeping. If Save loses its HTTP reply,
  the phone suspends its alarm/commands until **Load and Save** confirms state.
- Disable and Save before adding/removing/blinking bulbs or changing laptops.
  This prevents stale bulb lists or identification flashes being treated as On.
  Turning the fallback off restores original direct-UDP controls and the phone
  alarm preference. If the laptop is permanently lost, stop its service first;
  recover its connection/state or clear the app's fallback preferences only
  after ensuring no old scheduler can resume.

### Polling limitations

A network loss looks like power loss. Reconnection without a persisted manual
hold may reapply the timetable once. Fast off/on cycles entirely between polls
can be missed, and external changes during a fade/startup blind interval can be
missed too. There is no guaranteed way to distinguish them using `getPilot`.
For reliable manual holds, use this updated remote. Native Rhythms already
configured on bulbs, or other automation, may compete: there is no known safe
native-timetable readback/disable operation here, so do not deploy competing
schedulers. Unknown cloud configuration is preserved, not overwritten.

## Supervised acceptance checklist

Live checks are recorded in `docs/wiz-rhythms.md`. During supervised tests,
both presets were capped at **10–20%** in the test processes only; production Regular
remains the requested 100%. Do not leave a bright test preset on while waiting
for a timetable boundary.

1. Read hardware/firmware for **every bulb** in the remote; inventory unreachable
   bulbs after restoring wall power. Save a read-only snapshot with `wiz_inspect.py`.
2. Confirm the service starts disabled and Save itself changes no lights.
3. Verify that automatic scheduling and Follow timetable skip a bulb already
   off. Do not assume `setState` is safe: the tested bulb turns on with it.
4. Use temporary timetable boundaries a few minutes apart. Verify both presets,
   off bulbs staying off, and a wall On after a fully observed power outage.
5. Press Regular during Night; verify repeated polls preserve it. Restart the
   daemon, verify the hold remains. Use Follow timetable; then verify hold expiry
   at the next boundary. Off must remain off at all boundaries.
6. Verify DHCP rediscovery, laptop outage messages, token rejection, and disabling
   the laptop timetable before restoring the phone alarm.
7. Restore your desired timetable. Do not leave short test boundaries set.

## Tests

```sh
cd butler
python3 -m unittest -v
```

Tests use fake bulbs and loopback HTTP; they send no packets to physical bulbs.

## Optional user service (edit first)

See `uniremote-wiz.service.example` and `uniremote-wiz.env.example`. Store the
real environment file outside the repo with permissions `0600`. The service
does not need root. Ensure the laptop does not suspend; a logged-out user service
requires the usual OS-specific user-service/lifecycle setup.

## Migrate to the macOS butler

Copy the `butler/` directory; no Linux-only Python dependency is required. Use a
Python **3.11+** interpreter (macOS's bundled Python may be too old). The manager
uses the standard library, including the OS's IANA timezone database.

1. Create `~/.config/uniremote-wiz.env` from `uniremote-wiz.env.example`, permissions
   `0600`. Set its token, Mac LAN IP/broadcast and absolute Python interpreter path.
2. Run `sh /absolute/path/to/butler/run-butler.sh` in a terminal and complete the
   acceptance checklist. The manager is disabled until configured from the remote.
3. Optional: edit **all** `/Users/YOU/...` paths in `com.uniremote.wiz.plist.example`,
   copy it to `~/Library/LaunchAgents/com.uniremote.wiz.plist`, then load it:

   ```sh
   launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.uniremote.wiz.plist"
   ```

   To stop it:

   ```sh
   launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.uniremote.wiz.plist"
   ```

   Launchd does not expand `~` in plist paths; use absolute paths. This user agent
   runs while that user is logged in. Keep the Mac awake and on the bulb network.

Disable and Save the old manager from the remote **before** changing its URL to
the Mac. Then configure/save on the Mac. Do not leave both schedulers running.
If migrating existing settings, copy the old `~/.local/state/uniremote-wiz/`
directory while both processes are stopped; the state file includes manual holds.
