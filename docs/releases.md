# Releasing UniRemote

## What is checked in

The Gradle build and Android self-updater are checked in. There are currently
**no GitHub Actions workflows**: neither merging a PR nor creating a tag builds
or publishes an APK automatically. The existing process is manual.

## Manual Android release

1. Merge the desired changes. Increase both `versionCode` and `versionName` in
   `app/build.gradle.kts`; use the same version for the GitHub release tag.
2. On a machine with JDK 17 and the Android SDK, run:

   ```sh
   ./gradlew testReleaseUnitTest assembleRelease
   cp app/build/outputs/apk/release/app-release.apk UniRemote.apk
   ```

3. **Verify signing before publishing.** The build uses the private
   `keystore/uniremote.jks` if present, otherwise silently falls back to a debug
   key—even for `assembleRelease`. Updating an installed Android app requires
   the same signing certificate as that app. Do not publish a debug-signed APK
   as an update to a production-signed installation. The private keystore is
   deliberately excluded from git; it is not present on this development host.
4. Publish a normal GitHub Release with the APK asset. For example, after choosing
   and setting the next version (replace `X.Y`):

   ```sh
   gh release create vX.Y UniRemote.apk --repo dorinzrihen/Remote-control \
     --title "UniRemote X.Y" --notes "Release notes"
   ```

   Use the upstream repository: the installed app checks that specific repo,
   not a contributor's fork. This requires upstream release permissions.

## What the installed app does

`app/src/main/java/com/dorin/remote/net/Updater.kt` queries the upstream GitHub
`releases/latest` endpoint. The view model checks on launch/foreground return,
at most once every ten minutes. The updater compares the release tag (without
`v`) against installed `versionName` and selects an attached `.apk` asset.

If newer, it offers an update; after user confirmation it downloads the APK and
opens Android's package installer. Android still requires install permission,
confirmation and a compatible signing key. It is not a silent installation.

## Butler releases

The Python butler has no automated deployment or self-updater. Copy/update its
files on the laptop, install any declared dependencies, then restart the chosen
systemd/launchd service. The remote changes the running manager's settings; it
does not upgrade the manager's Python code. See [butler setup](../butler/README.md).
