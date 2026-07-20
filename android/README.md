# HARP Droid — Android frontend (experimental)

A FOSS Android app on top of the shared `src/harp` Python core, embedded via
[Chaquopy](https://chaquo.com/chaquopy/) (MIT). Same repo, same core: the app
consumes `../../src` directly, so it can never drift from the CLI.

## Status

- **Phase 1 — spike**: the *Spike* tab computes tonight's astronomical
  darkness on-device. First device run (2026-07-19) confirmed the stack:
  Chaquopy's wheel repo provides astropy/pyerfa for arm64, imports work.
  Two packaging quirks surfaced and are fixed: astropy's PLY-generated
  unit parser needs the package extracted to real files
  (`extractPackages`), and Chaquopy's wheel index shadows PyPI for names
  it carries — its astroplan is a stale <=0.7, so astroplan 0.10.1 is
  committed as a local pure-Python wheel in `app/wheels/` and installed
  by path. Rule of thumb: pin or vendor every dependency Chaquopy's repo
  might shadow.
- **Phase 2 — horizon wizard** (minimal): live true-north azimuth/altitude
  from the rotation-vector sensor, WMM declination applied automatically
  from the GPS fix (no NOAA lookup, ever), compass-calibration status,
  tap-to-record vertices, polar preview, `.hrz` export via the share sheet.
- **Phase 2b — camera reticle** (0.1.5, field-validated): live rear-camera
  aiming surface with an AR graticule (5-deg az/alt lines from the true
  lens FOV, roll-compensated, red horizon line), tap-anywhere capture,
  optional false-color contrast mode.
- **Phase 3 — planner tab** (0.2.0): `harp plan` on-device over
  `harp.api` — GPS site, the wizard's captured horizon picked up
  automatically, desirability-ranked rows, tap a target for its SIMBAD
  page. Default catalog Messier+curated; NGC/IC behind a "deep" switch.
- **Phase 4 — saved sites** (0.3.0): multiple observatories persisted in a
  durable store under the app's `filesDir` (`sites.yaml` + one `.hrz` per
  site) through the shared `harp.sites` core — the **same** layout and
  format as the CLI's `~/.config/harp/`. The wizard's **Save as site**
  button writes the built horizon plus the current GPS fix as a named site;
  the Plan tab has a site picker whose selection is persisted and which
  supplies the stored lat/lon and `.hrz` to the planner (GPS is now only the
  fallback when no site is saved). This replaces the old behaviour where the
  single horizon lived in `cacheDir` and was lost to cache eviction / "Clear
  cache". Bridges: `sites_bridge.py` (store CRUD), `planner_bridge.py`,
  `wizard.py`.

## Building — two paths

### Path A: GitHub CI (zero local setup)

CI builds a debug APK on every push touching `android/**` or `src/**`
(and on `workflow_dispatch`): grab the `harp-debug-apk` artifact from the
Actions run and sideload it. Best for occasional builds; latency is a full
CI round-trip per iteration.

### Path B: local build (fast bugfix loop)

One-time headless toolchain setup — no Android Studio needed (WSL2/Linux):

```bash
# JDK (a full JDK, not a JRE: javac is required)
sudo apt install openjdk-21-jdk-headless

# Android command-line tools + SDK 35
mkdir -p ~/android-sdk/cmdline-tools && cd ~/android-sdk/cmdline-tools
curl -LO https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
unzip commandlinetools-linux-*.zip && rm commandlinetools-linux-*.zip
mv cmdline-tools latest
yes | latest/bin/sdkmanager --licenses
latest/bin/sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"

# Gradle 8.13
mkdir -p ~/opt && cd ~/opt
curl -LO https://services.gradle.org/distributions/gradle-8.13-bin.zip
unzip gradle-8.13-bin.zip && rm gradle-8.13-bin.zip
ln -s ~/opt/gradle-8.13/bin/gradle ~/.local/bin/gradle

# point the project at the SDK (file is gitignored)
echo "sdk.dir=$HOME/android-sdk" > android/local.properties
```

Then, from the repo root:

```bash
gradle -p android :app:assembleDebug
# -> android/app/build/outputs/apk/debug/app-debug.apk
```

The first build is slow (Chaquopy downloads the Android wheels for the
astro stack); incremental rebuilds take seconds to a minute. Python 3.12
must be on PATH (Chaquopy's `buildPython`; adjust
`chaquopy.defaultConfig.version` in `app/build.gradle.kts` if yours
differs). If a build fails immediately after a toolchain change, stop the
cached daemon first: `gradle --stop`.

### Getting the APK onto the phone

Quick (no setup): serve it and download from the phone browser:

```bash
cd android/app/build/outputs/apk/debug && python3 -m http.server 8000
# phone browser -> http://<host-ip>:8000/app-debug.apk
```

Proper (one-time pairing, then one command per iteration) — wireless adb:
on the phone, Developer options > Wireless debugging > Pair device, then:

```bash
~/android-sdk/platform-tools/adb pair <ip>:<pairing-port>
~/android-sdk/platform-tools/adb connect <ip>:<port>
~/android-sdk/platform-tools/adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

With adb connected, live Python tracebacks beat screenshots:

```bash
~/android-sdk/platform-tools/adb logcat -s python.stderr AndroidRuntime
```

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

## Capture procedure (field-tested)

- **Hold the phone where the telescope objective will be** — at tripod
  height, at the scope's position. From eye level near a parapet you
  measure the railing (20-30 deg), not the skyline the scope actually
  sees (first field test: +20 deg systematic offset from exactly this).
- Aim at every vertex where the obstruction profile changes slope and
  tap **Add vertex**.
- **Blocked sectors (walls/buildings)**: at the last visible-sky azimuth
  add a normal vertex, turn ~1 deg into the wall and tap **Wall 90°**;
  same in mirror at the other edge. Without the 90-deg edges the export
  interpolates phantom sky across the wall — the first field test showed
  a planner happily scheduling M16 through solid masonry.

## Distribution intent

GitHub Releases APK + IzzyOnDroid (accepts prebuilt APKs from FOSS repos).
Mainline F-Droid would require from-source builds of the Python wheels —
parked until the app earns it.
