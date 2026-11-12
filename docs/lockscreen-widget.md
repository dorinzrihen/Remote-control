# Lock-screen TV widget

One widget, **TV volume & arrows**, with six buttons: **Vol +**, **Vol −**, **Up**, **Down**,
**Left** and **Right**. Nothing else. It works on the home screen and, on Android 16 QPR2 or
newer, on the lock screen **without unlocking the phone**.

## Put it on the lock screen (Pixel, Android 16 QPR2+)

1. Set up the TV in UniRemote once, as usual (pairing needs the app).
2. Settings → **Display & touch** → **Lock screen** → turn on **Widgets on lock screen**.
3. Lock the phone and **swipe left** on the lock screen to open the widget page.
4. Long-press (or tap **Add widgets**) → unlock once → **Add widget** → search **UniRemote** →
   **TV volume & arrows** → **Add** → **Done**.

From then on, swipe left on the lock screen and tap the buttons. The phone stays locked.

The top line (for example `LG TV · Volume 14`) is read-only. Tapping it does nothing, because
opening the app would need an unlock.

## How it works

- Every button is a **broadcast** `PendingIntent` to `widget/TvWidgetProvider`, never an activity.
  On the lock-screen hub, SystemUI fires broadcasts straight away. Only activity launches, or a
  broadcast that then opens an activity, ask for the PIN. So the receiver never starts an activity.
- The receiver keeps itself alive with `goAsync()` (a foreground broadcast, so it gets 10 s). It
  sends the key through the app's existing clients and routing in `TvControl` and `TvKeys`.
  No protocol code is duplicated.
- **There is no service and no notification.** Each tap is a few hundred milliseconds of work inside
  the broadcast.
- **Routing:**
  - Volume goes to "the TV": LG, or Samsung when only a Samsung is set up. The TV forwards it to the
    soundbar over HDMI ARC.
  - The arrows go to the same TV. The exception follows the remote screen's rule: while the LG TV
    shows the Xiaomi's HDMI input, the arrows go to the Xiaomi.
  - With only a Xiaomi set up, everything goes to the Xiaomi.
- **Reconnecting:** Android blocks network access for cached background apps. The app's idle
  connection therefore dies a few seconds after a tap. When a tap finds the device disconnected, it
  dials again right away instead of waiting for the client's retry back-off. A connection that still
  looks alive after 20 s of quiet is checked with one quick request (LG). The first tap after a pause
  takes about 0.5–1 s; taps right after it are immediate. Taps are sent one at a time, in order.
- When the app process starts, it redraws the widget. Since Android 15, force-stopping an app also
  cancels its widget's `PendingIntent`s, so this re-creates them.

Code: `app/src/main/java/com/dorin/remote/widget/` (`TvWidget.kt`, plus `WidgetLogic.kt` with the
unit-tested decisions), `res/layout/widget_tv.xml`, `res/xml/widget_tv_info.xml`.

## Test it on the Android 16 emulator (mock TV, never a real TV)

```sh
python3 tools/lockscreen_widget_demo.py scenario --build   # or: just lockscreen-widget scenario --build
python3 tools/lockscreen_widget_demo.py down
```

`scenario` does the following:

1. Creates the disposable AVD **`uniremote-android16`** if it is missing, using the Pixel 8a profile
   and `system-images;android-36.1;google_apis;x86_64`.
2. Boots it headless on `emulator-5584`.
3. Switches on the lock-screen hub.
4. Starts `tools/mock_tv.py` on `127.0.0.1:3000`. The app reaches it as `10.0.2.2`.
5. Installs Preview pointed at the mock and sets the PIN `1234`.
6. Adds the widget to the hub.
7. Locks the phone and taps all six buttons with the app process cold. It checks every command in
   the mock TV's log and checks that the phone is still locked (`dumpsys trust`).
8. Waits 25 s with the screen off and taps again.

Screenshots, an MP4, a GIF (if `ffmpeg` is on `PATH` or in `FFMPEG`) and `index.html` go to
`~/uniremote-lockscreen-widget-demo/`. Interactive commands: `up`, `add-widget`, `press up left …`,
`tv`, `tree`, `shot NAME`. `--wipe` factory-resets only this AVD.

The image is not downloaded automatically. Install it once (about 2 GB):
`sdkmanager "system-images;android-36.1;google_apis;x86_64"`.

### Emulator quirks the harness handles

- **SurfaceFlinger crash loop:** older `avdmanager` versions write `target=android-0` for "36.1"
  images. The emulator then misconfigures graphics, and SurfaceFlinger keeps crashing
  (`Assertion failed: !rcEnc->featureInfo()->hasReadColorBufferDma`). The harness writes
  `target=android-36.1` into the AVD's `.ini`.
- **The hub is off in the emulator image:** the SystemUI code is present (aconfig `communal_hub` and
  `glanceable_hub_v2` are on), but Pixel's device overlay that enables it is missing. With `adb root`,
  the harness turns it on with runtime overlays (`cmd overlay fabricate`):
  - `android:bool/config_glanceableHubEnabled`
  - SystemUI's `config_communalServiceEnabled`
  - SystemUI's `config_swipeToOpenGlanceableHub`

  It also sets `settings put secure glanceable_hub_enabled 1` and restarts SystemUI. The emulator's
  Settings app has no **Widgets on lock screen** switch.
- **Overlays come back disabled:** the overlays survive a reboot, but return disabled, so `up`
  re-enables them each time.
- **Port range:** adb only auto-discovers emulators on console ports 5554–5584, so the AVD uses 5584.
  The mock-lights AVD keeps 5580.
- **First unlock after a reboot:** with a PIN set, app data stays encrypted until the first unlock
  after boot, as on a phone. Setup unlocks once; the test then locks the phone again.

## Not verified yet (needs a real Pixel 8a)

The emulator run only proves the following: the Android 16 QPR2 lock-screen hub accepts the
widget, and taps on it reach a simulated LG TV while the phone is PIN-locked. It does not cover:

- the real Settings switch and the swipe on a Pixel;
- a real LG, Samsung or Xiaomi;
- Wi-Fi and battery behaviour, including Doze with the screen off for a long time;
- latency on the home network.
