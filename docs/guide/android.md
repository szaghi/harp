# Android app (experimental)

A FOSS Android frontend to the same HARP core, living in the repo's
[`android/`](https://github.com/szaghi/harp/tree/main/android) directory.
The app embeds `src/harp` directly via [Chaquopy](https://chaquo.com/chaquopy/)
(MIT), so app and CLI can never drift apart.

Current features:

- **Spike screen** — proves the on-device astro stack (numpy, astropy,
  astroplan, harp) by computing tonight's darkness window on the phone.
- **Horizon wizard** — the reason the app exists: live true-north
  azimuth/altitude from the fused rotation-vector sensor, magnetic
  declination applied automatically on-device (built-in World Magnetic
  Model — no NOAA lookup), compass-calibration status, tap-to-record
  skyline vertices, polar preview, and `.hrz` export via the share sheet —
  ready for N.I.N.A. and `harp plan`.

## Getting the app

There is no store listing yet: build a debug APK yourself, one of two ways.

### Path A — GitHub CI (zero setup)

Every push touching `android/**` or `src/**` builds a debug APK in the
`Android` workflow; download the `harp-debug-apk` artifact from the Actions
run and sideload it. Convenient, but each iteration costs a CI round-trip.

### Path B — local build (fast iteration)

A one-time headless toolchain (JDK 21, Android SDK 35 command-line tools,
Gradle 8.13 — no Android Studio required), then:

```bash
gradle -p android :app:assembleDebug
# -> android/app/build/outputs/apk/debug/app-debug.apk
```

First build is slow (Chaquopy fetches the Android wheels of the astro
stack); later builds take seconds to a minute. The full setup commands,
phone-transfer options (HTTP serve or wireless adb), and the on-device
debugging tip (`adb logcat -s python.stderr`) are in
[`android/README.md`](https://github.com/szaghi/harp/blob/main/android/README.md),
together with the first-device test checklist.
