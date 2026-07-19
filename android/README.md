# HARP Droid — Android frontend (experimental)

A FOSS Android app on top of the shared `src/harp` Python core, embedded via
[Chaquopy](https://chaquo.com/chaquopy/) (MIT). Same repo, same core: the app
consumes `../../src` directly, so it can never drift from the CLI.

## Status

- **Phase 1 — spike**: the *Spike* tab computes tonight's astronomical
  darkness on-device. If that button works, the whole stack (numpy, astropy
  + pyerfa, astroplan, harp) is proven on Android. **Whether Chaquopy's
  wheel repository provides astropy/pyerfa for arm64 is exactly what the
  first build verifies** — if `gradle assembleDebug` fails in the pip step,
  that is the spike's (negative) result, and we build the wheel ourselves.
- **Phase 2 — horizon wizard** (minimal): live true-north azimuth/altitude
  from the rotation-vector sensor, WMM declination applied automatically
  from the GPS fix (no NOAA lookup, ever), compass-calibration status,
  tap-to-record vertices, polar preview, `.hrz` export via the share sheet.
- Phase 2b (camera AR overlay) and phase 3 (planner UI over `harp.api`)
  are not started.

## Building

CI builds a debug APK on every push touching `android/**` or `src/**` —
grab the `harp-debug-apk` artifact from the Actions run and sideload it.

Locally: open the `android/` folder in Android Studio (Ladybug or newer),
or with SDK + Gradle installed:

```bash
gradle -p android :app:assembleDebug
```

Requirements: JDK 17, Android SDK 35, Python 3.12 on the build machine
(Chaquopy's `buildPython`; adjust `chaquopy.defaultConfig.version` in
`app/build.gradle.kts` if yours differs).

## First-device checklist

1. *Spike* tab → "Run astropy spike" → expect versions + tonight's
   dusk/dawn and the on-device compute time.
2. *Horizon wizard* tab → grant location → verify **Alt reads ~0 pointing
   at the horizon and ~+90 at the zenith** (if inverted, the sign of one
   axis in `HorizonViewModel.onSensorChanged` needs flipping — it is
   flagged in the code).
3. Check the declination shown matches your site (~+4° in central Italy).
4. Walk the skyline, add vertices at every profile change, export, and
   diff the shared `.hrz` against your hand-made `balcony.hrz`.

## Distribution intent

GitHub Releases APK + IzzyOnDroid (accepts prebuilt APKs from FOSS repos).
Mainline F-Droid would require from-source builds of the Python wheels —
parked until the app earns it.
