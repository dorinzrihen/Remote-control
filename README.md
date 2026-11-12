# UniRemote

One Android remote for an LG webOS TV, a Samsung Tizen TV, a Xiaomi Android TV streamer, and (through the TV over HDMI ARC) the LG soundbar. Set up only the devices you have; the app shows a tab per device.

## Install
Download `UniRemote.apk` from the [latest release](https://github.com/dorinzrihen/Remote-control/releases/latest) on the phone and open it (allow "install from unknown sources").

After that the app checks GitHub Releases on every launch and offers to download and install new versions itself.

## First run
1. Put the phone on the same Wi-Fi as the TV and the Xiaomi.
2. Tap **Scan the network**, or type the IP addresses by hand.
3. **LG TV** → Connect → press *Yes* on the TV prompt (once).
4. **Samsung TV** (2016 or newer, Tizen) → Connect → choose *Allow* on the TV prompt (once). The TV then gives the app a token that is kept.
5. **Xiaomi** → Pair → type the 6-character code the TV shows (once).
6. Pick which HDMI input the Xiaomi is on (LG: from the TV's input list; Samsung: HDMI 1–4), so the app switches modes by itself.

## Using it
- **LG TV / Samsung / Xiaomi** tabs choose where navigation goes. The Xiaomi tab also switches the TV input.
- **Touchpad**: on LG and Samsung it moves the real cursor (tap = click; two fingers = scroll on LG). On Xiaomi swipes become d-pad presses.
- **Keyboard** button opens the phone keyboard and types straight into the TV. It opens by itself when the LG TV asks for text. Apps with their own on-screen keyboard (YouTube) do not accept typed text, so use **Search YouTube for this** instead.
- **Mic** button uses the phone's speech recognition and puts the words into the keyboard bar.
- **Shortcut buttons** are chosen in Settings from the apps installed on the TV (LG and Samsung have separate lists), plus website buttons that open in the TV browser. Version 1.4 turns the old Stremio website button into a button for the Stremio TV app (`io.strem.tv`), which plays full screen by itself; on the Xiaomi tab it still opens Stremio web. Tap a shortcut twice to open it: the first tap only marks it ("Tap again"), so a stray touch does nothing.
- **Volume / mute** always go to the TV, which forwards them to the soundbar over HDMI ARC.
- **Quick actions** (lightning button): sleep timer (15/30/60/90 min, then the TV turns off), and on LG only: brightness slider, picture mode, sound output, sound mode, volume slider, screen off with sound on.
- **Bulbs** (WiZ, the **Bulbs** tab next to the TV tabs): connect **Lighting manager** using its URL/token and **Load**. The always-on computer is the sole bulb controller; Android uses authenticated HTTP only, with no direct UDP fallback or phone lighting alarm. Set bulbs up in the WiZ app, then **Find new bulbs** → *Blink* → choose a room → *Add*. Discovery, identification, removal and control all go through the manager. Keep the wall switch on so bulbs can answer.
- **Manager timetable**: edit Night/Day times, home timezone and polling interval in Bulbs. **Enable manager timetable** controls automatic scheduling only; manual controls and status still use the manager when disabled. Defaults are Night **21:00–06:00**, **20%, 2700K**, and Regular **100%, 6500K**. Manual On uses the current time's preset; On/Off/Regular/Night create holds until the next boundary. **Follow timetable** clears holds sooner and leaves off bulbs off. Save changes only the timetable, never replaces the manager's bulb list or sends a light command. Status includes observation age, errors and hardware/firmware. This is **not native WiZ Rhythms**; see [setup/limitations](butler/README.md) and the [hardware investigation](docs/wiz-rhythms.md).
- **Sound** (LG + soundbar over HDMI eARC): sound output (TV + soundbar / soundbar only / TV speaker) and sound mode (AI Sound Pro, Standard, Cinema, Clear Voice, Sports, Music, Game, Bass Blast). With an LG soundbar the TV shares its sound mode with the bar, so these buttons change the soundbar's mode too. Rear-speaker level, woofer level and left/right balance live inside the soundbar and are not reachable through the TV; use the soundbar remote for those.
- **Lock-screen widget** "TV volume & arrows": Vol +/− and the four arrows, on the home screen or (Android 16 QPR2+, e.g. Pixel) the lock screen without unlocking. Settings → Display & touch → Lock screen → Widgets on lock screen, then swipe left on the lock screen and add **UniRemote**. See [lock-screen widget](docs/lockscreen-widget.md).
- **TV power** turns the TV off, or wakes it with Wake-on-LAN (LG: needs "Quick Start+"; Samsung: needs "Power On with Mobile" / network standby). On Samsung the power key is a toggle.

## Samsung notes
- Works with Tizen TVs from 2016 on. The app connects to `wss://<tv>:8002` and falls back to `ws://<tv>:8001` for older firmware.
- If you pressed *Deny* on the TV, press **Connect** again in Settings and choose *Allow*.
- Typing: open a text field on the TV first, then use the Keyboard button. Enter commits the text.
- App icons arrive from the TV after the first connection and are cached on the phone.

## Build
```
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
./gradlew assembleRelease
```
To release: GitHub → **Actions** → **Release** → **Run workflow**. It bumps the version, builds, signs and publishes; phones get the update on next launch. See the [release guide](docs/releases.md).
Protocol unit tests (compared against the official Python protobuf library): `./gradlew testReleaseUnitTest`

To review before publishing, build the separate **UniRemote Preview** app with
`./gradlew assembleDebug`. It installs beside the normal app without replacing it.
See [phone testing and emulator screenshots](docs/testing.md).

## Local Android development

Run `just emulator dev` to build and open Preview on the persistent, visible
Pixel 8a emulator; rerun to update it without losing settings. Stop it with
`just emulator stop`. See [setup and platform notes](docs/emulator.md).
To verify GUI changes against simulated bulbs (never real lights), run
`just mock-lights scenario --build`; see [mock lights e2e](docs/mock-e2e.md).
To verify the lock-screen widget on a disposable Android 16 emulator against a simulated LG TV, run
`just lockscreen-widget scenario --build`; see [lock-screen widget](docs/lockscreen-widget.md).
