<img src="../assets/harp-icon.svg" alt="HARP" width="96" height="96" align="right">

# HARP Droid — Android frontend (experimental)

A FOSS Android app on top of the shared `src/harp` Python core, embedded via
[Chaquopy](https://chaquo.com/chaquopy/) (MIT). Same repo, same core: the app
consumes `../../src` directly, so it can never drift from the CLI.

## Launcher icon

The app icon is an **adaptive icon**, composed by the launcher from two vector
layers and then masked to whatever shape the OEM uses (circle, squircle,
teardrop):

| File | Layer |
| --- | --- |
| `app/src/main/res/drawable/ic_launcher_background.xml` | night-sky gradient + RA/Dec grid |
| `app/src/main/res/drawable/ic_launcher_foreground.xml` | targets, transit arcs, ground, telescope |
| `app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml` | adaptive-icon descriptor |
| `app/src/main/res/mipmap-anydpi-v26/ic_launcher_round.xml` | round variant (same layers) |

No PNGs at any density — one vector serves every screen. Two constraints worth
knowing before editing them:

- **Safe zone.** The launcher scales the foreground 1.5x about the centre, so
  only the middle 72x72 of the 108x108 canvas is guaranteed visible. The
  artwork is authored in the full 108 space and wrapped in a single group that
  maps it onto 18..90, which keeps the coordinates identical to the design
  source while guaranteeing nothing is cropped.
- **Colour hierarchy.** Ground `#04070E` < tube `#151C2E` < mount `#2A3348` <
  counterweight `#3A4560`. An earlier revision drew the mount in the ground's
  exact colour and the entire mount became invisible; do not collapse these.

[`../assets/harp-icon.svg`](../assets/harp-icon.svg) is the same artwork as a
plain SVG, used by the root README and the docs site. Change one, change the
other.

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
  page. Default catalog Messier + Sharpless H II regions; NGC/IC behind a
  "deep" switch.
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
- **Core capability — Solar System + classification** (`harp.api`
  `API_VERSION` 3): the shared core now ranks the Moon and the eight planets
  alongside deep-sky objects (offline, on by default) and tags every target
  with a `classification` (`nebula`/`galaxy`/.../`planet`/`moon`/`sun`).
  Plan-row and target JSON gained `classification` and `body` fields
  (additively — no existing field removed), and `ra_deg`/`dec_deg` are
  `null` for moving bodies. A future planner-tab iteration can group or
  filter by nature and badge Solar System rows; no app change is required to
  keep working against the new surface.
- **Phase 5 — polar-alignment compass** (Compass tab): a live true-north
  compass rose (magnetic->true via the on-device WMM, same as the horizon
  wizard) with the visible celestial pole marked on it and a plain-language
  "turn N° left/right, tilt N° up/down" delta to drive an EQ mount's polar
  axis onto the pole. The pole is a pure function of latitude (az 0/180,
  alt = |latitude|) so nothing calls the Python core; Polaris is drawn
  coincident with the north pole (its ~0.7° offset is inside the
  magnetometer's own error). Rough mechanical alignment to get the pole into
  a finder — not a substitute for drift or plate-solve. A **gyro hold**
  ("INS") button latches the fused heading while the phone is calibrated and
  clear of the mount, then propagates it on the gyro alone (world-frame
  integration, exact at any tilt) so the mount's steel no longer pulls the
  reading as you walk the phone in onto the polar axis — the alignment
  workflow real observers use. The lock is manual, calibration-gated,
  visibly indicated, and auto-releases after 30 s; it is hidden on devices
  with no gyroscope. Pure Kotlin (`CompassViewModel` / `CompassScreen`), no
  bridge, no `harp.api` change.
- **Phase 6 — polar-alignment assistant** (`harp.api` `API_VERSION` 4): the
  Compass tab splits into **1 · Coarse (sensors)** — the rose above, unchanged
  — and **2 · Align (assistant)**, which reads the phone's live attitude and
  gives azimuth/altitude corrections that drive the mount's polar axis onto the
  refracted pole (the numbers go to zero as you turn the two bolts). This is
  the AstroLock-style flow: the phone is the instrument measuring the axis, not
  a lookup table. Scoped to ONE job — **rough-align in twilight before Polaris
  is visible**, then hand off to N.I.N.A. TPPA. That rules out any capture or
  calibration step (a reference against an invisible star is impossible), so
  the correction is always absolute: computed pole minus current pointing. A
  **bullseye** draws the error with the polar-scope field (~5°) as its inner
  ring, so "close enough that Polaris will show in the eyepiece" is visible at
  a glance. A **mounting toggle** selects the sensor frame — *Flat on tube*
  (long edge along the axis; verified to need no axis remap) or *Back camera*
  (the `(AXIS_X, AXIS_Z)` remap).

  Only the pole altitude needs the Python core (`polar_bridge.run_polar` →
  `harp.polar`): it applies **atmospheric refraction** (+2.7′ at latitude 20°,
  +0.5′ at 65° above bare `|lat|`). The azimuth (0 N / 180 S) and all live
  deltas are sensor-side. The stage states its real uncertainty (±1–2°
  calibrated, "not trustworthy" when uncalibrated) rather than implying the
  sub-degree precision competing apps advertise. `harp.polar` still provides
  the full polar-scope reticle geometry (precession-correct separation, hour
  angle, per-mount `MOUNTS` transform) as a library surface for other
  frontends, though the app no longer draws a reticle clock.
- **Core capability — Sharpless emission nebulae**: the shared core ships the
  313 Sharpless (Sh2) H II regions and their measured sizes, correcting
  OpenNGC's under-sized nebulae via a vendored Sh2↔NGC/IC/M concordance
  (offline). The `planner_bridge` request accepts `sharpless` (bool) and
  `sharpless_min_diam` (arcmin); the Plan tab drives them from a Settings
  toggle, matching the CLI's `--sharpless` / `--sharpless-min-diam`.

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

> [!IMPORTANT]
> **After editing anything under the shared `../../src` Python core, build with
> `--rerun-tasks`:**
>
> ```bash
> gradle -p android :app:assembleDebug --rerun-tasks
> ```
>
> The app embeds `src/harp` via Chaquopy's `srcDir("../../src")`, a directory
> *outside* the Gradle module. Gradle's incremental up-to-date check does not
> reliably detect edits there, so a plain `assembleDebug` reports
> `mergeDebugPythonSources UP-TO-DATE` and silently bundles the **previous**
> `.pyc` — the APK then runs stale planner/catalog code while your `src/`
> shows the fix. `--rerun-tasks` forces the merge to re-embed the current
> sources. Kotlin-only changes (`.kt`) build correctly without it. To verify a
> build picked up a source change, grep the bundled bytecode for a symbol you
> just added:
>
> ```bash
> unzip -p android/app/build/outputs/apk/debug/app-debug.apk \
>   assets/chaquopy/app.imy | grep -a <new_symbol> \
>   && echo "fresh" || echo "STALE — rebuild with --rerun-tasks"
> ```

The first build is slow (Chaquopy downloads the Android wheels for the
astro stack); incremental rebuilds take seconds to a minute (but see the
shared-Python caveat above). Python 3.12
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
5. *Compass* tab → stage **1 · Coarse**: needs a **magnetometer**; the gyro
   hold additionally needs a **gyroscope** and hides itself without one.
   Calibrate with a figure-8 and check the stated uncertainty changes with
   the calibration state.
6. *Compass* tab → stage **2 · Align**: needs a GPS fix (pole altitude =
   latitude). Pick the mounting that matches your holder, then confirm the
   bullseye dot moves the RIGHT way — swing the mount east and the dot must
   move left (the pole is now to the west), raise the altitude bolt and the dot
   must move down. A dot that runs the wrong way means the mounting toggle is
   set to the other geometry. The shown pole altitude should sit ~1′ **above**
   your bare latitude (refraction).

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
