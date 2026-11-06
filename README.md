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
- **Quick actions** (lightning button): **Bulbs**, sleep timer (15/30/60/90 min, then the TV turns off), and on LG only: brightness slider, picture mode, sound output, sound mode, volume slider, screen off with sound on.
- **Bulbs** (WiZ, inside Quick actions): set a bulb up in the WiZ app first, then **Find new bulbs** → *Blink* to see which one it is → type the room → *Add*. Each room has an on/off button and two modes: *Regular* (100%, cool white 6500K) and *Night* (20%, warm 2700K). The bulbs are controlled directly over the Wi-Fi (UDP port 38899), not through the WiZ cloud. Keep the wall switch on, or the bulb cannot answer.
- **Night at 21:00** (on by default): every evening at 21:00 the bulbs that are on switch to Night; bulbs that are off stay off. The on/off button starts in Night between 21:00 and 06:00. Whatever you press after 21:00 stays until the next evening. The phone does this, so it has to be at home on the Wi-Fi at 21:00.
- **Optional laptop timetable**: edit Night/Day times (including minutes), home timezone and polling interval inside Bulbs. The local manager handles detected wall-switch On correction and manual overrides. It is portable to macOS, **not native WiZ Rhythms**, and off by default. Read the [actual-bulb investigation](docs/wiz-rhythms.md) and [setup/limitations](butler/README.md) before enabling it. Saved bulbs also display their module and firmware using read-only `getSystemConfig`.
- **Sound** (LG + soundbar over HDMI eARC): sound output (TV + soundbar / soundbar only / TV speaker) and sound mode (AI Sound Pro, Standard, Cinema, Clear Voice, Sports, Music, Game, Bass Blast). With an LG soundbar the TV shares its sound mode with the bar, so these buttons change the soundbar's mode too. Rear-speaker level, woofer level and left/right balance live inside the soundbar and are not reachable through the TV; use the soundbar remote for those.
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
