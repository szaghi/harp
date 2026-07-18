"""HARP command-line interface.

Entry point is :data:`app`, exposed as the ``harp`` console script.

Configuration precedence (strongest first): CLI option > config file entry
(site/optics/global) > built-in default.
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from harp import __version__
from harp.config import DEFAULTS, find_config, load_config, pick, resolve_section
from harp.errors import HarpError

log = logging.getLogger(__name__)

app = typer.Typer(
    name="harp",
    help="HARP - Horizon-Aware Recommender and Planner for deep-sky astrophotography.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        print(f"harp {__version__}")
        raise typer.Exit(0)


def _fail(err: Exception) -> typer.Exit:
    typer.secho(f"error: {err}", fg=typer.colors.RED, err=True)
    return typer.Exit(1)


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """HARP - plan tonight's deep-sky imaging session."""


@app.command()
def plan(
    date: str | None = typer.Argument(None, help="Night to plan, YYYY-MM-DD (default: today)."),
    config: str | None = typer.Option(
        None,
        help="Sites/optics config (YAML or JSON). Default: sites.yaml/.yml/.json "
        "in the cwd, then ~/.config/harp/.",
    ),
    site: str | None = typer.Option(None, help="Site name defined in the config."),
    optics: str | None = typer.Option(None, help="Optical-setup name in the config."),
    hrz: str | None = typer.Option(
        None, help="Horizon file .hrz (true north). Without one, a flat 0 deg horizon is used."
    ),
    lat: float | None = typer.Option(None, help="Latitude (deg)."),
    lon: float | None = typer.Option(None, help="Longitude (deg, East positive)."),
    elev: float | None = typer.Option(None, help="Elevation (m)."),
    tz: str | None = typer.Option(None, help="IANA timezone, e.g. Europe/Rome."),
    label: str | None = typer.Option(None, help="Site label."),
    focal: float | None = typer.Option(None, help="Focal length (mm)."),
    sensor: str | None = typer.Option(None, help="A sensor preset or 'WxH' in mm, e.g. 23.5x15.7."),
    mag_limit: float | None = typer.Option(
        None, "--mag-limit", help="Magnitude limit for pyongc objects."
    ),
    moon_sep: float | None = typer.Option(
        None, "--moon-sep", help="Minimum Moon separation (deg)."
    ),
    min_hours: float | None = typer.Option(
        None, "--min-hours", help="Minimum usable hours to keep a target."
    ),
    top: int | None = typer.Option(None, help="Rows shown on screen."),
    no_plot: bool = typer.Option(False, "--no-plot", help="Do not draw the chart."),
    no_pyongc: bool = typer.Option(
        False, "--no-pyongc", help="Curated nebulae only (no Messier/NGC from pyongc)."
    ),
    csv: str | None = typer.Option(None, help="Output CSV file."),
    png: str | None = typer.Option(None, help="Output PNG chart file."),
) -> None:
    """Recommend deep-sky targets for one night from your observing site.

    A target counts as observable only when its altitude clears the site
    horizon in its own direction and the Moon is far enough away.
    """
    # Imports deferred: astropy/astroplan cost ~2 s, which would otherwise be
    # paid by --help and unrelated subcommands too.
    from harp.catalog import build_targets
    from harp.horizon import Horizon
    from harp.optics import Rig, parse_sensor
    from harp.planner import Site, plan_night
    from harp.report import plot_charts, print_notes, print_report, write_csv

    try:
        cfg_path = find_config(config)
        cfg = load_config(cfg_path) if cfg_path else {}
        site_name, site_cfg = resolve_section(cfg, "sites", site, cfg_path)
        _, optics_cfg = resolve_section(cfg, "optics", optics, cfg_path)

        the_site = Site(
            label=pick(label, "label", site_cfg, site_name or DEFAULTS.site_label),
            lat=pick(lat, "lat", site_cfg, DEFAULTS.lat),
            lon=pick(lon, "lon", site_cfg, DEFAULTS.lon),
            elev=pick(elev, "elev", site_cfg, DEFAULTS.elev),
            tz=pick(tz, "tz", site_cfg, DEFAULTS.tz),
        )
        sensor_name, sw, sh = parse_sensor(pick(sensor, "sensor", optics_cfg, DEFAULTS.sensor))
        rig = Rig(
            focal_mm=pick(focal, "focal", optics_cfg, DEFAULTS.focal_mm),
            sensor_name=sensor_name,
            sensor_w_mm=sw,
            sensor_h_mm=sh,
        )

        hrz_val = pick(hrz, "hrz", site_cfg, None)
        if hrz_val is None:
            horizon, horizon_label = Horizon.flat(0.0), "flat 0 deg (no .hrz given)"
        else:
            hrz_path = Path(hrz_val)
            # config-relative resolution: a config can live anywhere
            if hrz is None and cfg_path and not hrz_path.is_absolute():
                hrz_path = cfg_path.parent / hrz_path
            horizon, horizon_label = Horizon.from_hrz(hrz_path), str(hrz_path)

        targets = build_targets(
            use_pyongc=not no_pyongc,
            mag_limit=pick(mag_limit, "mag_limit", cfg, DEFAULTS.mag_limit),
        )
        the_plan = plan_night(
            site=the_site,
            rig=rig,
            horizon=horizon,
            targets=targets,
            date=date,
            grid_min=DEFAULTS.grid_min,
            min_moon_sep=pick(moon_sep, "moon_sep", cfg, DEFAULTS.min_moon_sep),
            min_hours=pick(min_hours, "min_hours", cfg, DEFAULTS.min_hours),
            min_peak_alt=DEFAULTS.min_peak_alt,
            horizon_label=horizon_label,
        )
    except HarpError as e:
        raise _fail(e) from None

    top_n = pick(top, "top", cfg, DEFAULTS.top)
    print_report(the_plan, top=top_n)
    write_csv(the_plan, csv or DEFAULTS.csv_file)
    print_notes(the_plan, top=top_n)
    if not no_plot:
        plot_charts(the_plan, png or DEFAULTS.plot_file, n_plot=DEFAULTS.n_plot)


@app.command(name="list")
def list_config(
    config: str | None = typer.Option(
        None, help="Sites/optics config file (YAML or JSON); default: auto-detected."
    ),
) -> None:
    """List the sites and optical setups defined in the config."""
    try:
        cfg_path = find_config(config)
        cfg = load_config(cfg_path) if cfg_path else {}
    except HarpError as e:
        raise _fail(e) from None
    print(f"Config: {cfg_path or '(none)'}")
    print("Sites  :", ", ".join(cfg.get("sites") or {}) or "(none)")
    print("Optics :", ", ".join(cfg.get("optics") or {}) or "(none)")


@app.command()
def horizon(
    points_file: str = typer.Argument(
        ...,
        help="YAML/JSON file with the measured vertices: "
        "{declination: DEG_EAST, blocked_alt: 90.0, points: [[az_mag, alt], ...]}.",
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output .hrz file (default: <points-file>.hrz)."
    ),
    declination: float | None = typer.Option(
        None,
        help="Magnetic declination (deg, East positive); overrides the points file. "
        "Use 0 if the measurements are already in true azimuth.",
    ),
    preview: str | None = typer.Option(None, help="Also save a polar preview PNG to this path."),
) -> None:
    """Build a N.I.N.A.-compatible .hrz horizon file from measured vertices.

    Measure (azimuth, altitude) at every vertex where the obstruction profile
    changes; the magnetic-to-true correction is applied here, once, so the
    .hrz is in true north.
    """
    from harp.config import load_config
    from harp.horizon import build_profile, preview_profile, validate_profile, write_hrz

    try:
        src = Path(points_file)
        if not src.exists():
            raise _fail(FileNotFoundError(f"points file not found: {src}"))
        data = load_config(src)
        points = [(float(az), float(alt)) for az, alt in data.get("points", [])]
        if not points:
            raise _fail(ValueError(f"no 'points' list in {src}"))
        decl = declination if declination is not None else float(data.get("declination", 0.0))
        blocked = float(data.get("blocked_alt", 90.0))

        profile = build_profile(points, decl, blocked)
        for problem in validate_profile(profile):
            typer.secho(f"warning: {problem}", fg=typer.colors.YELLOW, err=True)

        out = Path(output) if output else src.with_suffix(".hrz")
        write_hrz(profile, out)
        print(f"Horizon file written: {out}  ({len(profile)} points, declination {decl:+.2f} deg)")
        if preview:
            preview_profile(profile, preview)
            print(f"Preview saved: {preview}")
        print("Load it in N.I.N.A.: Options > General > Astrometry > Horizon.")
    except HarpError as e:
        raise _fail(e) from None
