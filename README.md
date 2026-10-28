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
- **Shortcut buttons** are chosen in Settings from the apps installed on the TV (LG and Samsung have separate lists), plus website buttons (Stremio web by default) that open in the TV browser.
- **Volume / mute** always go to the TV, which forwards them to the soundbar over HDMI ARC.
- **Quick actions** (lightning button): sleep timer (15/30/60/90 min, then the TV turns off), and on LG only: scenes, brightness slider, picture mode, sound output, sound mode, volume slider, screen off with sound on.
- **Scenes** (LG): one tap sets picture mode, sound mode, sound output and volume together. Defaults: *Regular* (Standard picture, Standard sound, TV + soundbar), *Movie* (Cinema picture, Cinema sound, soundbar only), *Outside* (Clear Voice, TV + soundbar, volume unchanged). Hold a scene to overwrite it with whatever the TV is doing right now.
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
cp app/build/outputs/apk/release/app-release.apk UniRemote.apk
gh release create v1.4 UniRemote.apk --title "UniRemote 1.4" --notes "what changed"
```
Bump `versionCode` / `versionName` in `app/build.gradle.kts` before each release; the in-app updater compares `versionName` with the release tag.
Protocol unit tests (compared against the official Python protobuf library): `./gradlew testReleaseUnitTest`
