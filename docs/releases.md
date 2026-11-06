# Releasing UniRemote

## Release with one click

GitHub → **Actions** → **Release** → **Run workflow**. All fields are optional:

- **notes**: what changed, shown in the app's update dialog. Empty uses the
  list of commits since the last release.
- **version**: e.g. `2.0`. Empty bumps the minor number (1.6 → 1.7).
- **dry run**: build and check everything, publish nothing.

`.github/workflows/release.yml` then takes `main`, raises `versionCode` and
`versionName` in `app/build.gradle.kts`, runs the unit tests, builds the
release APK and checks it is signed with the UniRemote key. Only then does it
commit "Version 1.7" to `main`, tag it `v1.7` and create the GitHub Release
"UniRemote 1.7" with `UniRemote.apk` attached.

It stops without changing anything if there are no new commits since the last
release, the version already exists, the tests fail, or the APK is not signed
with the release key.

## Who can release

Anyone with write access to `dorinzrihen/Remote-control` can run the workflow.
Pull requests from forks cannot run it and never see the signing key.

The signing key `keystore/uniremote.jks` is not in git. The workflow gets it
from the `ANDROID_KEYSTORE_BASE64` secret in the `release` environment, which
only `main` can use.

## Manual release

On a machine with JDK 17, the Android SDK and `keystore/uniremote.jks`:

```sh
./gradlew testReleaseUnitTest assembleRelease
cp app/build/outputs/apk/release/app-release.apk UniRemote.apk
gh release create vX.Y UniRemote.apk --repo dorinzrihen/Remote-control \
  --title "UniRemote X.Y" --notes "Release notes"
```

Without the keystore the build silently falls back to a debug key, even for
`assembleRelease`. Installed phones refuse an update signed with a different
key, so check with `apksigner verify --print-certs` that the SHA-256 digest is
`eee4fda2f81c27135c2df40ea57f2e656bd377798ebc509e1e815a14059587ca`.

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
