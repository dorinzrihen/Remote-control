# UniRemote

One Android remote for an LG webOS TV, a Xiaomi Android TV streamer, and (through the TV over HDMI ARC) the LG soundbar.

## Install
Copy `UniRemote.apk` to the phone and open it (allow "install from unknown sources").

## First run
1. Put the phone on the same Wi-Fi as the TV and the Xiaomi.
2. Tap **Scan the network**, or type the IP addresses by hand.
3. **LG TV** → Connect → press *Yes* on the TV prompt (once).
4. **Xiaomi** → Pair → type the 6-character code the TV shows (once).
5. Pick which HDMI input the Xiaomi is on, so the app switches modes by itself.

## Using it
- **LG TV / Xiaomi** tabs choose where navigation goes. The Xiaomi tab also switches the TV input.
- **Touchpad**: on LG it moves the real cursor (tap = click, two fingers = scroll). On Xiaomi swipes become d-pad presses.
- **Keyboard** button opens the phone keyboard and types straight into the TV. It opens by itself when the LG TV asks for text. Apps with their own on-screen keyboard (YouTube) do not accept typed text, so use **Search YouTube for this** instead.
- **Mic** button uses the phone's speech recognition and puts the words into the keyboard bar.
- **Shortcut buttons** are chosen in Settings from the apps installed on the TV, plus website buttons (Stremio web by default).
- **Volume / mute** always go to the TV, which forwards them to the soundbar over HDMI ARC.
- **Quick actions** (lightning button): sleep timer (15/30/60/90 min, then the TV turns off), brightness slider, picture mode, screen off with sound on.
- **TV power** turns the TV off, or wakes it with Wake-on-LAN (needs "Quick Start+" enabled on the TV).

## Build
```
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
./gradlew assembleRelease
cp app/build/outputs/apk/release/app-release.apk UniRemote.apk
```
Protocol unit tests (compared against the official Python protobuf library): `./gradlew testReleaseUnitTest`
