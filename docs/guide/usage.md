# Usage

## Plan a night

```bash
harp plan                                    # tonight, default site/optics from config
harp plan 2026-08-15                         # another night
harp plan --site balcony --optics newton800  # named config entries
harp list                                    # sites and optics in the config
```

On-the-fly site without a config:

```bash
harp plan 2026-08-15 \
    --hrz mountain.hrz --lat 46.50 --lon 11.35 --elev 1200 \
    --label "Mountain" --focal 530 --sensor 36x24 \
    --csv mountain.csv --png mountain.png
```

**Precedence**: CLI option > config value (site/optics/global) > built-in
default. Without a `.hrz` (neither CLI nor config), a flat 0-degree horizon
is assumed.

### All `plan` options

`harp plan --help` is authoritative; this is the same set, grouped by what it
does.

| Option | Effect |
| --- | --- |
| `--config` | Sites/optics file. Default: `sites.yaml`/`.yml`/`.json` in the cwd, then `~/.config/harp/`. |
| `--site`, `--optics` | Pick named entries from the config. |
| `--lat`, `--lon`, `--elev`, `--tz`, `--label` | Define a site inline; longitude is East-positive. |
| `--hrz` | Horizon file (true north). Without one, a flat 0° horizon. |
| `--focal`, `--sensor` | Rig. `--sensor` takes a preset name or `WxH` in mm. |
| `--catalogs` | Which pyongc catalogues: `M`, `NGC`, `IC` (default `M`). |
| `--targets` | Your own targets file, merged with priority over the catalogues. |
| `--mag-limit` | Magnitude cutoff for pyongc objects. |
| `--no-pyongc` | Curated nebulae only — skip Messier/NGC entirely. |
| `--sharpless` / `--no-sharpless` | Include the Sh2 H II regions and their measured sizes. On by default. |
| `--sharpless-min-diam` | Drop Sh2 regions smaller than this, arcmin (default 10). |
| `--solar-system` / `--no-solar-system` | Include the Moon and planets. On by default. |
| `--ss-moons` | Add the major moons — needs the JPL ephemeris, so this one is **online**. |
| `--moon-sep` | Minimum Moon separation to keep a target, degrees. |
| `--min-hours` | Minimum usable hours to keep a target. |
| `--filter` | Class tokens OR-ed (`nebula`, `galaxy`, `cluster`, `planetary`, `star`, `planet`, `moon`, `sun`, `other`), with `emission`/`non-emission` AND-ed on top. |
| `--sort` | `score` (default), `hours`, `alt`, or `name`. |
| `--top` | How many rows to show on screen. |
| `--csv`, `--png`, `--nina` | Write the table, the chart, and the N.I.N.A. import. |
| `--no-plot` | Skip drawing the chart entirely. |
| `--json` | Emit the whole plan as JSON on stdout instead of a table — the scripting surface. |
| `--link-site` | Provider for the `link` column: `simbad` (default), `wikipedia`, `astrobin`, `aladin`. |
| `--save-site`, `--default`, `--keep-hrz` | Save the inline site into the config (see below). |

::: tip Everything is offline except one flag
`--ss-moons` is the sole exception: it downloads a JPL ephemeris. Every other
option — catalogues, Sharpless, Solar System planets, ephemerides — works with
no network at all.
:::

## Saved sites (multiple observatories)

A *site* bundles a location and its horizon: label, lat/lon/elev, timezone,
and a `.hrz` mask. Manage them with `harp sites`; the default is used when
`--site` is omitted.

```bash
harp sites add balcony --lat 41.738 --lon 12.889 --elev 300 \
    --tz Europe/Rome --label "Castelli Balcony" --default
harp sites add mountain --lat 46.5 --lon 11.35 --elev 1200 --tz Europe/Rome
harp sites list                 # the default is marked with '*'
harp sites set-default mountain
harp sites remove mountain      # also deletes its .hrz (--keep-hrz to keep)
```

Build a horizon and store it into a site in one step:

```bash
harp horizon balcony_points.yaml --save-site balcony \
    --lat 41.738 --lon 12.889 --tz Europe/Rome --default
```

Sites live in `sites.yaml` (default `~/.config/harp/sites.yaml`, or any
`--config` path), each `.hrz` written beside it. This is the **same** store
and file layout the Android app uses — copy the app's exported config
directory to `~/.config/harp/` and every saved observatory works from the
CLI unchanged. Removing the default site repoints it to another site
automatically.

## Choosing the catalogs

```bash
harp plan --catalogs M              # Messier only (default)
harp plan --catalogs M,NGC,IC       # full OpenNGC, filtered by --mag-limit
harp plan --catalogs NGC --mag-limit 10
```

The offline OpenNGC database holds ~14k NGC/IC objects; `--mag-limit`
(default 11.0) applies to these. Emission nebulae with **no** magnitude
(most H II regions) are kept regardless of the cut — surface brightness,
not magnitude, is what matters for them. The config key `catalogs` (string
or list) sets a default.

## Emission nebulae (Sharpless)

The Sharpless (Sh2) catalogue of 313 H II regions ships with HARP and is on
by default. It does two jobs:

```bash
harp plan                            # Sharpless included (default)
harp plan --no-sharpless             # OpenNGC + curated only
harp plan --sharpless-min-diam 60    # only the largest H II regions
```

1. **Coverage** — it adds the large emission nebulae OpenNGC lacks (OpenNGC
   is NGC/IC only and carries no Sharpless designations).
2. **Accurate sizes** — OpenNGC's nebula dimensions come from the LBN
   bright-plate table and often under-report the imageable H-alpha extent
   (the Heart shows 60' in OpenNGC vs ~150' in reality). Via a vendored
   Sh2↔NGC/IC/M concordance, HARP adopts the Sharpless-measured extent for
   the matching OpenNGC object, so framing and the field-of-view score use
   the real size. The override is guarded (emission types only, at most a 4x
   enlargement) so an embedded cluster or planetary never inherits a whole
   region's diameter.

Everything is on disk — the catalogue and the concordance are vendored, no
network at run time. (They are regenerated from VizieR/SIMBAD only by the
maintainer, via `tools/build_*.py`.)

## Solar System targets

The Moon and the eight planets are planned alongside deep-sky objects, on
by default:

```bash
harp plan                              # planets + Moon included
harp plan --no-solar-system            # deep-sky only
harp plan --filter planet              # planets only
harp plan --filter moon                # just the Moon
```

Unlike fixed deep-sky objects, Solar System bodies **move**: their position
and apparent disk size are recomputed for every time step of the night from
astropy's built-in ephemeris — no download, fully offline. They are ranked
on visibility (hours above your horizon, peak altitude) like any other
target, but the Moon-impact and mosaic-framing columns do not apply and show
`n/a` / `planetary`. They are excluded from N.I.N.A. exports (N.I.N.A. tracks
them from its own ephemeris; a static J2000 coordinate would be wrong).

Natural satellites (Titan, the Galilean moons) are **not** in the built-in
ephemeris and are off by default:

```bash
harp plan --ss-moons                   # + major moons (online, downloads a kernel)
```

`--ss-moons` fetches a JPL satellite ephemeris at run time — the only part of
HARP that touches the network — and is intended for completeness, not
imaging: on a deep-sky rig these moons are unresolvable points inside the
parent planet's glare.

## Your own targets

```bash
harp plan --targets my_targets.yaml
```

A user targets file merges **with priority over the built-in catalogues** —
an entry sharing a designation (M/NGC/IC/Sh2) with a known object replaces
it, so it also serves to override coordinates or sizes. Config key:
`targets` (path, resolved relative to the config file).

```yaml
targets:
  - name: "Sh2-240 Spaghetti West"   # designations in the name are used
    ra:   "05h37m00s"                #   for cross-source deduplication
    dec:  "+27d40m00s"               # sexagesimal or decimal degrees
    maj:  100                        # arcmin (optional, enables framing)
    min:  80
    const: Tau                       # optional
    kind: SNR                        # optional
    narrowband: true                 # optional: relaxes Moon impact
```

Duplicates across sources are detected by shared catalog designation
(OpenNGC cross-ids: M42 == NGC1976), with a tight 2-arcmin positional
fallback — close neighbours like M43 stay distinct.

## Filtering and ordering

```bash
harp plan --filter galaxy,cluster        # galaxies OR clusters
harp plan --filter emission,nebula       # emission nebulae only
harp plan --filter non-emission          # broadband program (galaxy season)
harp plan --sort alt                     # rank by peak altitude
harp plan --sort name                    # alphabetical
```

Class tokens (`nebula`, `galaxy`, `cluster`, `planetary`, `star`, `planet`,
`moon`, `sun`, `other`) are OR-ed together; `emission`/`non-emission` AND on
top of them. Note the distinction between `planetary` (planetary *nebula*)
and `planet` (a Solar System planet). Config keys: `filter`, `sort`. Sorting
accepts `score` (default), `hours` (historical order), `alt`, `name`.

## Mosaic panel coordinates

When the plan says `mosaic NxM`, get the actual per-panel centers:

```bash
harp mosaic IC1396                        # rig from config (default optics)
harp mosaic "North America" --pa 30       # major axis at position angle 30 deg
harp mosaic M31 --csv m31_panels.csv
```

Panels are laid out in the tangent plane with your rig's overlap, rotated by
`--pa` (position angle of the object's major axis, North through East,
default 0 = North), and projected back to the sphere — correct at any
declination. Output: `r1c1 ...` rows with RA/Dec in both sexagesimal and
decimal degrees, ready for N.I.N.A. sequence targets.

## N.I.N.A. integration

HARP and N.I.N.A. share two interfaces:

1. **The horizon**: the same `.hrz` file drives HARP's visibility and
   N.I.N.A.'s horizon display (Options > General > Astrometry > Horizon).
2. **Targets**: `--nina FILE` exports CSVs that N.I.N.A.'s sequencer
   imports directly (Sequence > import targets, Telescopius format):

```bash
harp plan --nina tonight.csv          # ranked targets (the rows shown on screen)
harp mosaic IC1396 --pa 30 --nina panels.csv   # one sequencer target per panel,
                                               # camera rotation = position angle
```

The export format is pinned to N.I.N.A.'s actual importer source, not to
documentation: coordinate strings match its digits-only parser, and the
observing-list flavor deliberately emits only the `(J2000)` coordinate
headers — N.I.N.A. has a known importer bug that reads a bare
`Right Ascension` column for the declination too, which these files
therefore never contain.

Solar System bodies have no fixed J2000 coordinate, so they are exported as
a **dusk snapshot**: the position at that night's dusk, with the familiar
name marked `<body> (<date> dusk)` to flag it as a single-instant
placeholder. N.I.N.A. re-slews to the live position from its own ephemeris —
the snapshot only keeps the body present in the imported list.

## Target details

```bash
harp info M27
harp info "Elephant Trunk" --catalogs M,NGC,IC
```

Prints everything HARP knows offline — designations, classification, type
(with the narrowband verdict), coordinates, magnitude, size, framing for
your rig with the mosaic detail suggestion — plus the informative links for
all four providers. For a Solar System body (`harp info Mars`) the output
notes that the position and apparent disk are computed per night rather than
fixed, and the links are name-based.

## Reading the output

- **score** — composite desirability, 0-100: weighted geometric mean of the
  continuous window (weight 3, saturates at 3 h), total hours (1, saturates
  at 5 h), peak altitude (2, as sin(alt) — the inverse-airmass proxy), the
  Moon verdict (2), and how well the object fills your field of view (1).
  Geometric, so one hopeless factor sinks the score instead of averaging
  away. Default ranking; `--sort hours` restores the historical
  hours-above-horizon order.
- **hrs** — total hours above your horizon during astronomical darkness.
- **cont / window** — longest **continuous** run and its interval: how long
  you can integrate before the object enters a blocked sector. Size exposures
  and mosaic panels on this number.
- **kind** — the catalog type; its nature (`nebula`, `galaxy`, `cluster`,
  `planetary`, `star`, `planet`, `moon`, `sun`) is the **classification**,
  filterable with `--filter` and carried in the CSV/JSON.
- **altMx / az** — peak altitude and the azimuth at that moment.
- **moonSep** — minimum Moon separation during the usable window
  (`0` for Solar System bodies, where it does not apply).
- **Moon** — impact: `none` (Moon down), `ok(NB)` (negligible in narrowband),
  `low`/`med`/`high` (broadband impact from phase + separation), or `n/a` for
  Solar System bodies (not degraded by moonlight the way faint deep-sky
  nebulosity is). For catalog objects, narrowband is derived from the type:
  planetaries, supernova remnants, and HII regions get the relaxed verdict;
  galaxies, clusters, and reflection nebulae keep the broadband penalty.
- **frame** — `1 frame` or `mosaic NxM` for your rig (15% overlap), or
  `planetary` for a Solar System body (mosaic framing does not apply).
- **detail** — for mosaic targets, an interesting crop that fits one frame.
- **link** (CSV only) — an informative web page per target, built offline
  from the designation. Provider via `--link-site` (or config `link_site`):
  `simbad` (default — type, distance, magnitudes, bibliography; resolves
  essentially every designation), `wikipedia` (best prose and images, but
  faint objects 404), `astrobin` (community image search), `aladin` (survey
  imagery by coordinates). Custom targets without a designation always get
  an Aladin coordinate link — a working link beats a guessed 404.

The chart shows per target: altitude (blue), Moon (orange), the grey
obstruction band, and the usable window in green.

## Build a horizon file

Measure `(azimuth, altitude)` vertices where the obstruction profile changes
(wall corners, ridge top, roof edges) with an app showing both angles, put
them in a points file, then:

```bash
harp horizon balcony_points.yaml -o balcony.hrz --preview preview.png
```

Points file:

```yaml
declination: 4.10    # magnetic declination, deg East (NOAA WMM); 0 if app reads true north
blocked_alt: 90.0
points:
  - [107.0,  7.0]    # [magnetic azimuth, altitude]
  - [108.0, 90.0]    # blocked sector edges at 90
  - [335.0, 90.0]
  - [336.0,  6.0]
```

The magnetic-to-true correction is applied HERE, once: every `.hrz` is in
true north. The same file loads in N.I.N.A. (Options > General > Astrometry >
Horizon) and works for `harp plan`.

## Config file

`sites.yaml` (or `.yml`/`.json`) collects sites and optical setups; searched
in the current directory, then `~/.config/harp/`:

```yaml
default_site:   balcony
default_optics: newton800

mag_limit: 11.0     # global filters (optional)
moon_sep:  30.0
min_hours: 1.0
top:       40

sites:
  balcony:
    label: "Castelli Balcony"
    hrz:   balcony.hrz    # relative paths resolve against this file
    lat:   41.738026
    lon:   12.889862      # East positive
    elev:  300
    tz:    Europe/Rome

optics:
  newton800:
    focal:  800
    sensor: "23.5x15.7"   # or a preset name
```

## Polar alignment

The Android companion's *Compass* tab is built for one workflow: **rough-align
the mount during twilight, while Polaris is still invisible**, closely enough
that Polaris lands in the polar scope when it rises — then refine with
**N.I.N.A. TPPA**. That is the whole scope. It does not attempt the arcminute
job, because a phone compass cannot do it and TPPA already does it well.

Two stages, kept apart because they are used differently: stage 1 is the
free-standing compass (phone in hand, find the pole by eye), stage 2 is the
assistant (phone fixed to the mount, turn the bolts).

### Stage 1 — Coarse (phone sensors)

A live true-north compass rose with the celestial pole marked, driving a
"turn N° left/right, tilt N° up/down" delta. The pole needs no ephemeris: it
sits due north (or south) at an altitude equal to your latitude.

**This stage is worth ±1–2° at best**, and only after a good figure-8
calibration — that is the phone magnetometer's floor, and no amount of sensor
fusion moves it. Apps advertising ±0.1° from a phone compass are quoting a
filter's internal repeatability, not absolute pointing truth: a Kalman filter
suppresses noise, it does not remove the hard/soft-iron bias that dominates
here. The stage is honest about this on screen, and degrades its claim when
the magnetometer reports poor calibration.

That is still enough to put the pole inside a polar scope's field, which is
all stage 1 is for.

A **gyro hold** button latches the heading while the phone is calibrated and
clear of the mount, then propagates it on the gyroscope alone as you walk the
phone in — so the mount's steel cannot pull the reading. It preserves a good
heading; it cannot rescue a bad one.

### Stage 2 — Align (assistant)

The phone is fixed to the mount, and the app reads its **live attitude** to
give azimuth/altitude corrections that drive the mount's polar axis onto the
pole — the numbers go to zero as you turn the two adjustment bolts. The pole
altitude it targets includes **atmospheric refraction** (the apparent pole
sits above the true one by +2.7′ at latitude 20°, +1.1′ at 42°, +0.8′ at 52°
and +0.5′ at 65° — small but one-sided) computed by the astronomical core; the
pole azimuth is pure geometry (due north, or south below the equator).

A **bullseye** shows the same information visually: the centre is the pole, the
dot is where your polar axis points now, and you drive the dot to the centre.
The inner ring is a typical polar-scope field (~5°) — once the dot is inside
it, Polaris will appear in the polar scope when it rises. Right/left on the
bullseye is azimuth, up/down is altitude, matching the two bolts.

There is deliberately **no capture or calibration step**. A reference taken
against a star you cannot see yet is impossible, and one taken against nothing
is meaningless, so the correction is always absolute: the computed pole minus
where the phone points now.

Tell the app how the phone sits on the mount — this is a sensor-frame choice,
not a calibration:

- **Flat on tube** — the phone lies on the tube (or any flat face) with its
  long edge along the polar axis.
- **Back camera** — the phone is clamped so its back camera looks down the
  polar axis.

::: tip Why the phone compass is good enough here
The correction is only as good as the phone magnetometer — **±1–2°** after a
good figure-8 calibration, and *not trustworthy at all* when the calibration
state is poor (the assistant says so on screen). But a polar scope's field is
5–8°, so ±1–2° reliably puts Polaris in the eyepiece — which is the entire job
of this stage. The arcminute work belongs to **N.I.N.A. TPPA** once Polaris is
visible. Any app claiming ±0.1° from a phone compass is quoting a filter's
internal repeatability, not absolute pointing accuracy.
:::

From Python, the underlying pole geometry (refracted altitude, and the
polar-scope reticle position, for other frontends) is available offline:

```python
from datetime import UTC, datetime

from harp.api import polar_align_to_dict

polar_align_to_dict(datetime.now(UTC), 41.9, 12.5, mount="skywatcher")
```

## Light pollution and target contrast

HARP models your horizon honestly. Tell it about the sky *above* that horizon
and it will also stop recommending targets your site cannot realistically
reach.

```bash
harp plan --bortle 6           # estimate your sky, 1 (pristine) .. 9 (inner city)
harp plan --sqm 19.5           # or a measured value, mag/arcsec2 — wins over --bortle
```

Or per site in the config, so you never retype it:

```yaml
sites:
  balcony:
    lat: 41.738
    lon: 12.890
    tz:  Europe/Rome
    bortle: 6

optics:
  newton800:
    focal: 800
    sensor: "23.5x15.7"
    aperture: 200          # mm, optional
```

### Why surface brightness, not magnitude

What decides whether a deep-sky object is imageable from a bright site is
**contrast** — its surface brightness against the sky background — not its
catalogue magnitude. A compact planetary nebula packs its light into a few
square arcseconds and cuts straight through city glow; a large face-on galaxy
spreads the *same* total flux over hundreds of times the area and drowns in it.

That is why **M57** (mag 8.8, but 17.8 mag/arcsec²) is a classic city target
while **M101** (mag 7.9 — brighter! — but 23.8 mag/arcsec²) is the textbook
light-pollution casualty. Ranking on magnitude alone gets this exactly
backwards.

Two corrections make the model right for *imaging* rather than visual use:

- **Narrowband targets barely care.** A dual-band filter rejects most
  broadband light pollution, so emission nebulae stay viable downtown — which
  is precisely why imagers shoot them from cities. HARP already knows which
  targets are emission sources, and applies this automatically.
- **Aperture helps, gently.** More signal per unit time, but an imager can
  also just integrate longer, so aperture is a mild nudge rather than a
  dominant term.

::: tip It is off until you ask for it
Declare neither `bortle` nor `sqm` and the contrast term is exactly neutral —
your rankings are identical to what they were before this feature existed.
Targets with no catalogue magnitude (most Sharpless regions) are also left
neutral rather than penalised for missing data.
:::

A target is never *removed* by this term, only ranked lower: the score is a
geometric mean with a floor, so a hopeless-from-here object sinks but still
appears. If your sky improves — or you drive somewhere darker — change one
number and the ranking follows.

## Scripting: JSON and the Python API

Three commands emit machine-readable output — `harp plan --json`,
`harp info --json`, `harp mosaic --json`. Every payload carries an
`api_version` field so a consumer can detect a breaking change:

```bash
harp plan 2026-08-15 --json | jq '.rows[0] | {name, score, window}'
```

For anything beyond the CLI, import `harp.api`. It is the **supported**
surface — everything else in the package is internal and may change without
notice:

```python
from harp.api import Horizon, Rig, Site, build_targets, plan_night, plan_to_dict

site = Site(label="Balcony", lat=41.9, lon=12.5, elev=100, tz="Europe/Rome")
rig = Rig(focal_mm=800, sensor_name="APS-C", sensor_w_mm=23.5, sensor_h_mm=15.7)
plan = plan_night(
    site=site,
    rig=rig,
    horizon=Horizon.from_hrz("balcony.hrz"),
    targets=build_targets(pyongc_catalogs=["M"]),
    date="2026-08-15",
)
print(plan_to_dict(plan)["rows"][0]["name"])
```

What the surface offers, by area:

| Area | Entry points |
| --- | --- |
| Planning | `plan_night`, `desirability`, `NightPlan`, `PlanRow`, `Site` |
| Targets | `build_targets`, `find_targets`, `filter_targets`, `user_targets`, `kind_class`, `FILTER_TOKENS`, `Target` |
| Optics & mosaics | `Rig`, `parse_sensor`, `mosaic_panels`, `Panel` |
| Horizon | `Horizon`, `build_profile`, `validate_profile`, `write_hrz` |
| Saved sites | `SitesConfig`, `SiteEntry`, `default_config_path`, `slugify` |
| Polar alignment | `polar_align_to_dict`, `reticle_position`, `MOUNTS`, `Mount`, `ReticleFix` |
| JSON converters | `plan_to_dict`, `target_to_dict`, `info_to_dict`, `panels_to_dict`, `site_to_dict`, `mounts_to_dict` |
| Links | `target_link` |

::: info API stability
Breaking changes to `harp.api` bump `API_VERSION` (currently **4**) and the
package minor version. The Android app is built on this same surface, which is
what keeps it from drifting away from the CLI.
:::

## Notes and limits

- Run after midnight, `harp plan` targets the night STARTING on that calendar
  date (the following evening); pass the previous day's date for the night in
  progress.
- OpenNGC objects are filtered by V magnitude, but emission nebulae with no
  magnitude are kept anyway (ranked by size/surface brightness). The Sharpless
  catalogue supplies the emission nebulae OpenNGC lacks and corrects its
  under-sized ones; a small built-in rescue list covers the handful neither
  database can place.
- Solar System bodies carry no magnitude (phase-dependent); their apparent
  disk is derived live from the body's distance at each time step. HARP ranks
  them on visibility only — it flags *when* a planet is up, not lucky-imaging
  suitability, which is a different technique from deep-sky work. Satellites
  (`--ss-moons`) are for completeness: on a deep-sky rig they are unresolvable
  points inside the parent planet's glare.
- Weather (seeing/clouds) is out of scope: check Astrospheric / Clear Outside
  / Meteoblue before the session.
