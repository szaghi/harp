# Android app (experimental)

A FOSS Android frontend to the same HARP core, living in the repo's
[`android/`](https://github.com/szaghi/harp/tree/main/android) directory.
The app embeds `src/harp` directly via [Chaquopy](https://chaquo.com/chaquopy/)
(MIT), so app and CLI can never drift apart.

Everything runs **offline**: the catalogues, the ephemerides and the
astronomical core are all on the phone. No account, no network, no telemetry.

## The five tabs

- **Home** — the landing dashboard, laid out as a mini solar system: tonight's
  darkness window and Moon state on the Sun, and the other tabs as planets
  carrying their own status (site name, target count, current alignment error).
  Tap a planet to jump there.
- **Horizon** — the reason the app exists. Live true-north azimuth/altitude
  from the fused rotation-vector sensor, magnetic declination applied
  on-device (built-in World Magnetic Model — no NOAA lookup),
  compass-calibration status, tap-to-record skyline vertices, polar preview,
  and `.hrz` export via the share sheet — ready for N.I.N.A. and `harp plan`.
- **Plan** — the full planner on-device: the same ranking the CLI produces,
  with client-side filter chips by target class and emission type. Results are
  computed from the selected saved site and its captured horizon.
- **Align** — polar alignment in two stages: a live compass rose for finding
  the pole by eye, then an assistant that reads the phone's attitude while it
  is fixed to the mount and gives azimuth/altitude bolt corrections with a
  bullseye. Built for twilight, before Polaris is visible; see
  [Polar alignment](/guide/usage#polar-alignment) for the workflow and its
  honest accuracy limits.
- **Settings** — rig (focal length, sensor), planning thresholds, catalogue
  selection, Sharpless options, refraction pressure/temperature, link
  provider, and appearance.

## Saved sites

Sites live in the app's private storage in exactly the CLI's layout —
`sites.yaml` plus one `.hrz` per site — so the whole directory can be copied
to a desktop `~/.config/harp/` and used with `harp --site`. Capturing a
horizon in the wizard saves it straight into the selected site.

## Appearance

Seven indoor themes (Tokyo Night, Catppuccin Mocha, Nord, One Dark, Dracula,
Gruvbox Dark, Solarized Dark) plus a **red night-vision mode** that collapses
the whole scheme to red on black for use at the telescope. The night-vision
toggle sits in the top bar, reachable from every tab without going into
Settings.

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

::: warning After editing the shared `src/` Python, add `--rerun-tasks`
```bash
gradle -p android :app:assembleDebug --rerun-tasks
```
The app embeds `src/harp` via Chaquopy from *outside* the Gradle module, so a
plain `assembleDebug` can report the Python merge `UP-TO-DATE` and bundle the
**previous** bytecode — the APK then runs stale planner/catalog code. Kotlin-only
changes do not need it. Full explanation and a verify-the-bundle one-liner are in
[`android/README.md`](https://github.com/szaghi/harp/blob/main/android/README.md).
:::

First build is slow (Chaquopy fetches the Android wheels of the astro
stack); later builds take seconds to a minute. The full setup commands,
phone-transfer options (HTTP serve or wireless adb), and the on-device
debugging tip (`adb logcat -s python.stderr`) are in
[`android/README.md`](https://github.com/szaghi/harp/blob/main/android/README.md),
together with the first-device test checklist.
