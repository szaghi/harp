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

## Reading the output

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
