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
(default 11.0) applies to these, never to the curated nebulae. The config
key `catalogs` (string or list) sets a default.

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

Class tokens (`nebula`, `galaxy`, `cluster`, `planetary`, `star`, `other`)
are OR-ed together; `emission`/`non-emission` AND on top of them. Config
keys: `filter`, `sort`. Sorting accepts `score` (default), `hours`
(historical order), `alt`, `name`.

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

## Target details

```bash
harp info M27
harp info "Elephant Trunk" --catalogs M,NGC,IC
```

Prints everything HARP knows offline — designations, type (with the
narrowband verdict), coordinates, magnitude, size, framing for your rig
with the mosaic detail suggestion — plus the informative links for all
four providers.

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
- **altMx / az** — peak altitude and the azimuth at that moment.
- **moonSep** — minimum Moon separation during the usable window.
- **Moon** — impact: `none` (Moon down), `ok(NB)` (negligible in narrowband),
  `low`/`med`/`high` (broadband impact from phase + separation). For catalog
  objects, narrowband is derived from the type: planetaries, supernova
  remnants, and HII regions get the relaxed verdict; galaxies, clusters, and
  reflection nebulae keep the broadband penalty.
- **frame** — `1 frame` or `mosaic NxM` for your rig (15% overlap).
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

## Notes and limits

- Run after midnight, `harp plan` targets the night STARTING on that calendar
  date (the following evening); pass the previous day's date for the night in
  progress.
- pyongc objects are filtered by V magnitude; large emission nebulae often
  have none, which is why the curated internal catalogue exists (and is never
  magnitude-filtered).
- Weather (seeing/clouds) is out of scope: check Astrospheric / Clear Outside
  / Meteoblue before the session.
