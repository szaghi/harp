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


def _catalog_list(cfg: dict, catalogs: str | None) -> list[str]:
    """Resolve the pyongc catalog selection (CLI > config > 'M')."""
    cat_val = pick(catalogs, "catalogs", cfg, "M")
    if isinstance(cat_val, str):
        return [c.strip().upper() for c in cat_val.split(",") if c.strip()]
    return [str(c).upper() for c in cat_val]


def _resolve_rig(cfg: dict, cfg_path, optics: str | None, focal: float | None, sensor: str | None):
    """Resolve the optical rig from CLI > config optics section > defaults."""
    from harp.optics import Rig, parse_sensor

    _, optics_cfg = resolve_section(cfg, "optics", optics, cfg_path)
    sensor_name, sw, sh = parse_sensor(pick(sensor, "sensor", optics_cfg, DEFAULTS.sensor))
    return Rig(
        focal_mm=pick(focal, "focal", optics_cfg, DEFAULTS.focal_mm),
        sensor_name=sensor_name,
        sensor_w_mm=sw,
        sensor_h_mm=sh,
        # Optional: only the sky-contrast term uses it, and None means
        # "assume the reference aperture", so old configs are unaffected.
        aperture_mm=pick(None, "aperture", optics_cfg, None),
    )


def _find_one_target(query: str, all_targets: list):
    """Resolve a query to exactly one target or exit with a helpful error."""
    from harp.catalog import find_targets

    matches = find_targets(query, all_targets)
    if not matches:
        raise _fail(ValueError(f"no target matches {query!r}"))
    if len(matches) > 1:
        typer.secho(f"ambiguous target {query!r}, matches:", err=True)
        for t in matches[:15]:
            typer.secho(f"  - {t.name}", err=True)
        raise typer.Exit(1)
    return matches[0]


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
    bortle: int | None = typer.Option(
        None,
        min=1,
        max=9,
        help="Bortle class 1-9 of the site's sky. Enables the light-pollution "
        "term in the score: faint low-surface-brightness targets sink in bright "
        "skies, narrowband ones far less. Omit to leave the ranking unchanged.",
    ),
    sqm: float | None = typer.Option(
        None,
        help="Measured sky brightness (mag/arcsec^2), e.g. 20.8. Overrides --bortle.",
    ),
    focal: float | None = typer.Option(None, help="Focal length (mm)."),
    sensor: str | None = typer.Option(None, help="A sensor preset or 'WxH' in mm, e.g. 23.5x15.7."),
    catalogs: str | None = typer.Option(
        None,
        help="Comma-separated pyongc catalogs to include: M, NGC, IC (default: M).",
    ),
    targets: str | None = typer.Option(
        None,
        help="User-defined targets file (YAML/JSON with a 'targets' list), "
        "merged with priority over the built-in catalogues.",
    ),
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
    sort: str = typer.Option(
        "score",
        help="Ranking: 'score' (desirability), 'hours' (historical order), "
        "'alt' (peak altitude), or 'name'.",
    ),
    target_filter: str | None = typer.Option(
        None,
        "--filter",
        help="Comma-separated target filter: class tokens (nebula, galaxy, "
        "cluster, planetary, star, planet, moon, sun, other) are OR-ed; "
        "emission/non-emission AND on top. E.g. 'galaxy,cluster' or 'planet'.",
    ),
    link_site: str | None = typer.Option(
        None,
        "--link-site",
        help="Provider for the CSV 'link' column: simbad (default), wikipedia "
        "(may 404 on faint objects), astrobin, aladin.",
    ),
    no_plot: bool = typer.Option(False, "--no-plot", help="Do not draw the chart."),
    no_pyongc: bool = typer.Option(
        False, "--no-pyongc", help="Curated nebulae only (no Messier/NGC from pyongc)."
    ),
    sharpless: bool = typer.Option(
        True,
        "--sharpless/--no-sharpless",
        help="Include the Sharpless (Sh2) H II regions and use their measured "
        "sizes to correct pyongc's under-sized emission nebulae. On by default.",
    ),
    sharpless_min_diam: float | None = typer.Option(
        None,
        "--sharpless-min-diam",
        help="Minimum Sharpless angular diameter to keep, arcmin (default 10).",
    ),
    solar_system: bool = typer.Option(
        True,
        "--solar-system/--no-solar-system",
        help="Include Solar System bodies (Moon + planets, offline). On by default.",
    ),
    ss_moons: bool = typer.Option(
        False,
        "--ss-moons",
        help="Also include major natural satellites (Titan, Galilean moons). "
        "Requires a JPL satellite ephemeris downloaded at run time (online).",
    ),
    csv: str | None = typer.Option(None, help="Output CSV file."),
    png: str | None = typer.Option(None, help="Output PNG chart file."),
    nina: str | None = typer.Option(
        None,
        help="Also export the ranked targets as a N.I.N.A.-importable CSV "
        "(Sequencer > import targets). Exports the same rows shown on screen.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit the plan as JSON on stdout (with chart curves) instead of the "
        "table; files are written only for explicitly given --csv/--png/--nina.",
    ),
) -> None:
    """Recommend deep-sky targets for one night from your observing site.

    A target counts as observable only when its altitude clears the site
    horizon in its own direction and the Moon is far enough away.
    """
    # Imports deferred: astropy/astroplan cost ~2 s, which would otherwise be
    # paid by --help and unrelated subcommands too.
    from harp.catalog import build_targets
    from harp.horizon import Horizon
    from harp.links import LINK_PROVIDERS
    from harp.planner import Site, plan_night
    from harp.report import plot_charts, print_notes, print_report, write_csv

    if sort not in ("score", "hours", "alt", "name"):
        raise _fail(ValueError(f"unknown sort {sort!r}: choose 'score', 'hours', 'alt', or 'name'"))
    try:
        cfg_path = find_config(config)
        cfg = load_config(cfg_path) if cfg_path else {}
        site_name, site_cfg = resolve_section(cfg, "sites", site, cfg_path)

        the_site = Site(
            label=pick(label, "label", site_cfg, site_name or DEFAULTS.site_label),
            lat=pick(lat, "lat", site_cfg, DEFAULTS.lat),
            lon=pick(lon, "lon", site_cfg, DEFAULTS.lon),
            elev=pick(elev, "elev", site_cfg, DEFAULTS.elev),
            tz=pick(tz, "tz", site_cfg, DEFAULTS.tz),
            # Light pollution, both optional. Declaring neither leaves the
            # sky-contrast term neutral, so the ranking is unchanged.
            bortle=pick(bortle, "bortle", site_cfg, None),
            sqm=pick(sqm, "sqm", site_cfg, None),
        )
        rig = _resolve_rig(cfg, cfg_path, optics, focal, sensor)

        link_provider = pick(link_site, "link_site", cfg, "simbad")
        if link_provider not in LINK_PROVIDERS:
            raise _fail(
                ValueError(
                    f"unknown link site {link_provider!r}: choose from {', '.join(LINK_PROVIDERS)}"
                )
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

        targets_val = pick(targets, "targets", cfg, None)
        targets_path = None
        if targets_val is not None:
            targets_path = Path(targets_val)
            # config-relative resolution, same rule as the .hrz path
            if targets is None and cfg_path and not targets_path.is_absolute():
                targets_path = cfg_path.parent / targets_path

        if ss_moons:
            from harp.solar_system import load_moon_ephemeris

            load_moon_ephemeris()
        target_list = build_targets(
            use_pyongc=not no_pyongc,
            use_sharpless=sharpless,
            use_solar_system=solar_system,
            ss_moons=ss_moons,
            pyongc_catalogs=_catalog_list(cfg, catalogs),
            mag_limit=pick(mag_limit, "mag_limit", cfg, DEFAULTS.mag_limit),
            sharpless_min_diam=pick(sharpless_min_diam, "sharpless_min_diam", cfg, 10.0),
            targets_file=targets_path,
        )
        filter_spec = pick(target_filter, "filter", cfg, None)
        if filter_spec:
            from harp.catalog import filter_targets

            target_list = filter_targets(target_list, filter_spec)
        the_plan = plan_night(
            site=the_site,
            rig=rig,
            horizon=horizon,
            targets=target_list,
            date=date,
            grid_min=DEFAULTS.grid_min,
            min_moon_sep=pick(moon_sep, "moon_sep", cfg, DEFAULTS.min_moon_sep),
            min_hours=pick(min_hours, "min_hours", cfg, DEFAULTS.min_hours),
            min_peak_alt=DEFAULTS.min_peak_alt,
            horizon_label=horizon_label,
            sort=sort,
        )
    except HarpError as e:
        raise _fail(e) from None

    top_n = pick(top, "top", cfg, DEFAULTS.top)
    if json_out:
        import json

        from harp.api import plan_to_dict

        if csv:
            write_csv(the_plan, csv, link_site=link_provider, quiet=True)
        if nina:
            from harp.nina import write_targets_csv

            write_targets_csv(the_plan, nina, top=top_n)
        if png and not no_plot:
            plot_charts(the_plan, png, n_plot=DEFAULTS.n_plot, quiet=True)
        print(json.dumps(plan_to_dict(the_plan, top=top_n, curves=True, link_site=link_provider)))
        return

    print_report(the_plan, top=top_n)
    write_csv(the_plan, csv or DEFAULTS.csv_file, link_site=link_provider)
    print_notes(the_plan, top=top_n)
    if nina:
        from harp.nina import write_targets_csv

        n = write_targets_csv(the_plan, nina, top=top_n)
        print(f"\nN.I.N.A. target list written: {nina} ({n} targets)")
    if not no_plot:
        plot_charts(the_plan, png or DEFAULTS.plot_file, n_plot=DEFAULTS.n_plot)


@app.command()
def mosaic(
    target: str = typer.Argument(
        ..., help="Target to frame: designation (M31, IC1396) or name substring."
    ),
    config: str | None = typer.Option(None, help="Sites/optics config file."),
    optics: str | None = typer.Option(None, help="Optical-setup name in the config."),
    focal: float | None = typer.Option(None, help="Focal length (mm)."),
    sensor: str | None = typer.Option(None, help="A sensor preset or 'WxH' in mm."),
    pa: float = typer.Option(
        0.0,
        help="Position angle of the object's major axis (deg, North through East); "
        "0 puts the major axis toward North.",
    ),
    catalogs: str | None = typer.Option(None, help="pyongc catalogs to search (default: M)."),
    targets: str | None = typer.Option(None, help="User-defined targets file to search too."),
    csv: str | None = typer.Option(None, help="Write the panel list to this CSV file."),
    nina: str | None = typer.Option(
        None,
        help="Write the panels as a N.I.N.A.-importable mosaic CSV "
        "(one sequencer target per panel, camera rotation = PA).",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit the panel list as JSON."),
) -> None:
    """Compute per-panel sky coordinates for a mosaic of TARGET with your rig."""
    import astropy.units as u

    from harp.catalog import build_targets
    from harp.mosaic import mosaic_panels

    try:
        cfg_path = find_config(config)
        cfg = load_config(cfg_path) if cfg_path else {}
        rig = _resolve_rig(cfg, cfg_path, optics, focal, sensor)
        all_targets = build_targets(
            pyongc_catalogs=_catalog_list(cfg, catalogs),
            targets_file=pick(targets, "targets", cfg, None),
        )
        t = _find_one_target(target, all_targets)

        if t.body is not None:
            raise _fail(
                ValueError(
                    f"{t.name} is a Solar System body (a moving point/disk): "
                    "mosaics are for fixed deep-sky objects only"
                )
            )
        dims = rig.grid_dims(t.maj_arcmin, t.min_arcmin)
        if dims is None:
            raise _fail(ValueError(f"{t.name}: no size in catalog, cannot plan a mosaic"))
        nx, ny = dims

        if json_out:
            import json

            from harp.api import panels_to_dict

            panels = mosaic_panels(t.coord, nx, ny, rig, pa_deg=pa)
            if nina:
                from harp.nina import write_mosaic_csv

                write_mosaic_csv(t.name, panels, pa, nina)
            print(json.dumps(panels_to_dict(t.name, panels, rig, pa)))
            return

        size = f"{t.maj_arcmin:.0f}' x {t.min_arcmin or t.maj_arcmin:.0f}'"
        print(f"Target: {t.name}  ({size})")
        print(
            f"Rig: {rig.focal_mm:.0f} mm + {rig.sensor_name}  ->  "
            f"panel FOV {rig.fov_long:.0f}' x {rig.fov_short:.0f}', "
            f"overlap {rig.overlap * 100:.0f}%"
        )
        if nx * ny == 1:
            print("Fits in a single frame — no mosaic needed. Center:")
        else:
            print(f"Grid: {nx} x {ny} panels, major axis at PA {pa:.0f} deg\n")

        panels = mosaic_panels(t.coord, nx, ny, rig, pa_deg=pa)
        rows = []
        for p in panels:
            ra_hms = p.coord.ra.to_string(unit=u.hourangle, sep="hms", precision=0, pad=True)
            dec_dms = p.coord.dec.to_string(sep="dms", precision=0, alwayssign=True, pad=True)
            rows.append((f"r{p.row}c{p.col}", ra_hms, dec_dms, p.coord.ra.deg, p.coord.dec.deg))

        print(f"{'panel':<7}{'RA (J2000)':<14}{'Dec (J2000)':<15}{'RA deg':>10}{'Dec deg':>10}")
        for name, ra_hms, dec_dms, ra_d, dec_d in rows:
            print(f"{name:<7}{ra_hms:<14}{dec_dms:<15}{ra_d:>10.4f}{dec_d:>10.4f}")

        if csv:
            import csv as csv_mod

            with Path(csv).open("w", newline="") as f:
                w = csv_mod.writer(f)
                w.writerow(["panel", "ra_hms", "dec_dms", "ra_deg", "dec_deg"])
                for name, ra_hms, dec_dms, ra_d, dec_d in rows:
                    w.writerow([name, ra_hms, dec_dms, f"{ra_d:.5f}", f"{dec_d:.5f}"])
            print(f"\nPanel list written: {csv}")
        if nina:
            from harp.nina import write_mosaic_csv

            n = write_mosaic_csv(t.name, panels, pa, nina)
            print(f"N.I.N.A. mosaic list written: {nina} ({n} panels)")
    except HarpError as e:
        raise _fail(e) from None


@app.command()
def info(
    target: str = typer.Argument(
        ..., help="Target to describe: designation (M31, IC1396) or name substring."
    ),
    config: str | None = typer.Option(None, help="Sites/optics config file."),
    optics: str | None = typer.Option(None, help="Optical-setup name in the config."),
    focal: float | None = typer.Option(None, help="Focal length (mm)."),
    sensor: str | None = typer.Option(None, help="A sensor preset or 'WxH' in mm."),
    catalogs: str | None = typer.Option(None, help="pyongc catalogs to search (default: M)."),
    targets: str | None = typer.Option(None, help="User-defined targets file to search too."),
    json_out: bool = typer.Option(False, "--json", help="Emit the details as JSON."),
) -> None:
    """Show what HARP knows about TARGET, plus informative web links."""
    import astropy.units as u

    from harp.catalog import build_targets, suggest_detail
    from harp.links import LINK_PROVIDERS, target_link

    try:
        cfg_path = find_config(config)
        cfg = load_config(cfg_path) if cfg_path else {}
        rig = _resolve_rig(cfg, cfg_path, optics, focal, sensor)
        all_targets = build_targets(
            pyongc_catalogs=_catalog_list(cfg, catalogs),
            targets_file=pick(targets, "targets", cfg, None),
        )
        t = _find_one_target(target, all_targets)

        if json_out:
            import json

            from harp.api import info_to_dict

            print(json.dumps(info_to_dict(t, rig)))
            return

        if t.body is not None:
            # Solar System body: no fixed coordinate or catalog size (both are
            # time-dependent and computed live by the planner).
            print(t.name)
            print(f"  classification: {t.classification}")
            print(f"  kind         : {t.kind}")
            print("  coordinates  : moving body — position computed per night")
            print("  size         : apparent disk varies with distance")
            print("  framing      : planetary (not a deep-sky framing target)")
            print("  links:")
            for provider in LINK_PROVIDERS:
                print(f"    {provider:<10}: {target_link(t, provider)}")
            return

        ra = t.coord.ra.to_string(unit=u.hourangle, sep="hms", precision=0, pad=True)
        dec = t.coord.dec.to_string(sep="dms", precision=0, alwayssign=True, pad=True)
        size = (
            f"{t.maj_arcmin:.0f}' x {(t.min_arcmin or t.maj_arcmin):.0f}'"
            if t.maj_arcmin
            else "unknown"
        )
        frame = rig.framing(t.maj_arcmin, t.min_arcmin)

        print(t.name)
        print(f"  designations : {', '.join(sorted(t.idents)) or '(none)'}")
        print(f"  classification: {t.classification}")
        print(f"  kind         : {t.kind}" + ("  [narrowband-friendly]" if t.narrowband else ""))
        print(f"  constellation: {t.const or '-'}")
        print(f"  coordinates  : {ra}  {dec}  (J2000)")
        print(f"  magnitude    : {t.mag if t.mag is not None else '-'}")
        print(f"  size         : {size}")
        print(f"  framing      : {frame}  ({rig.focal_mm:.0f} mm + {rig.sensor_name})")
        if frame.startswith("mosaic"):
            print(f"  detail       : {suggest_detail(t.name)}")
        print("  links:")
        for provider in LINK_PROVIDERS:
            print(f"    {provider:<10}: {target_link(t, provider)}")
    except HarpError as e:
        raise _fail(e) from None


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
    save_site: str | None = typer.Option(
        None,
        "--save-site",
        help="Also save the built horizon into a named site in the config "
        "(created or updated); site geo can be supplied with --lat/--lon/--tz.",
    ),
    config: str | None = typer.Option(
        None, help="Config file for --save-site (default: ~/.config/harp/sites.yaml)."
    ),
    lat: float | None = typer.Option(None, help="Site latitude for --save-site (deg)."),
    lon: float | None = typer.Option(None, help="Site longitude for --save-site (deg East)."),
    elev: float | None = typer.Option(None, help="Site elevation for --save-site (m)."),
    tz: str | None = typer.Option(None, help="Site IANA timezone for --save-site."),
    make_default: bool = typer.Option(
        False, "--default", help="With --save-site, also make it the default site."
    ),
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
        if save_site:
            _save_horizon_to_site(
                save_site, out.read_text(), config, lat, lon, elev, tz, make_default
            )
        print("Load it in N.I.N.A.: Options > General > Astrometry > Horizon.")
    except HarpError as e:
        raise _fail(e) from None


def _save_horizon_to_site(
    name: str,
    hrz_content: str,
    config: str | None,
    lat: float | None,
    lon: float | None,
    elev: float | None,
    tz: str | None,
    make_default: bool,
) -> None:
    """Persist a built horizon into a (new or existing) named site."""
    from harp.sites import SiteEntry, SitesConfig, slugify

    store = SitesConfig.load(config, create=True)
    slug = slugify(name)
    if slug in store.names():
        base = store.get(slug)
        entry = SiteEntry(
            name=slug,
            label=base.label,
            lat=pick(lat, "", {}, base.lat),
            lon=pick(lon, "", {}, base.lon),
            elev=pick(elev, "", {}, base.elev),
            tz=pick(tz, "", {}, base.tz),
        )
    else:
        if lat is None or lon is None:
            raise _fail(ValueError(f"new site '{slug}' needs --lat and --lon (and ideally --tz)"))
        entry = SiteEntry(name=slug, label=name, lat=lat, lon=lon, elev=elev or 0.0, tz=tz or "UTC")
    store.upsert(entry, hrz_content=hrz_content, make_default=make_default)
    store.save()
    tag = " (default)" if store.default_name() == slug else ""
    print(f"Saved horizon into site '{slug}'{tag} in {store.path}")


sites_app = typer.Typer(name="sites", help="Manage saved observing sites (multi-location).")
app.add_typer(sites_app)


@sites_app.command("list")
def sites_list(
    config: str | None = typer.Option(
        None, help="Config file (default: auto-detected, then ~/.config/harp/sites.yaml)."
    ),
) -> None:
    """List saved sites; the default is marked with '*'."""
    from harp.sites import SitesConfig, default_config_path

    try:
        # explicit path wins; else auto-detect a readable config; else the
        # user-level default (created empty on first write).
        cfg_path = Path(config) if config else (find_config(None) or default_config_path())
        store = SitesConfig.load(cfg_path, create=True)
    except HarpError as e:
        raise _fail(e) from None
    print(f"Config: {store.path}")
    names = store.names()
    if not names:
        print("(no sites defined — add one with 'harp sites add')")
        return
    default = store.default_name()
    for n in names:
        site = store.get(n)
        hp = store.hrz_path(site)
        has = "hrz" if hp and hp.exists() else "no-hrz"
        mark = "*" if n == default else " "
        print(
            f"{mark} {n:<16} {site.label:<24} {site.lat:8.3f},{site.lon:8.3f}  {site.tz}  [{has}]"
        )


@sites_app.command("add")
def sites_add(
    name: str = typer.Argument(..., help="Site name (slugified)."),
    lat: float = typer.Option(..., help="Latitude (deg)."),
    lon: float = typer.Option(..., help="Longitude (deg, East positive)."),
    elev: float = typer.Option(0.0, help="Elevation (m)."),
    tz: str = typer.Option("UTC", help="IANA timezone, e.g. Europe/Rome."),
    label: str | None = typer.Option(None, help="Human-readable label (default: the name)."),
    hrz: str | None = typer.Option(
        None, help="Existing .hrz file to copy into the site's config directory."
    ),
    config: str | None = typer.Option(
        None, help="Config file (default: ~/.config/harp/sites.yaml)."
    ),
    make_default: bool = typer.Option(False, "--default", help="Make this the default site."),
) -> None:
    """Add or update a saved site."""
    from harp.sites import SiteEntry, SitesConfig, slugify

    try:
        store = SitesConfig.load(config, create=True)
        slug = slugify(name)
        entry = SiteEntry(name=slug, label=label or name, lat=lat, lon=lon, elev=elev, tz=tz)
        content = Path(hrz).read_text() if hrz else None
        if hrz and not Path(hrz).exists():
            raise _fail(FileNotFoundError(f".hrz file not found: {hrz}"))
        store.upsert(entry, hrz_content=content, make_default=make_default)
        store.save()
    except HarpError as e:
        raise _fail(e) from None
    tag = " (default)" if store.default_name() == slug else ""
    print(f"Site '{slug}'{tag} saved in {store.path}")


@sites_app.command("remove")
def sites_remove(
    name: str = typer.Argument(..., help="Site name to remove."),
    config: str | None = typer.Option(
        None, help="Config file (default: ~/.config/harp/sites.yaml)."
    ),
    keep_hrz: bool = typer.Option(False, "--keep-hrz", help="Do not delete the site's .hrz file."),
) -> None:
    """Remove a saved site (and its .hrz unless --keep-hrz)."""
    from harp.sites import SitesConfig

    try:
        store = SitesConfig.load(config)
        store.remove(name, delete_hrz=not keep_hrz)
        store.save()
    except HarpError as e:
        raise _fail(e) from None
    print(f"Removed site '{name}'. Default is now: {store.default_name() or '(none)'}")


@sites_app.command("set-default")
def sites_set_default(
    name: str = typer.Argument(..., help="Site name to select as default."),
    config: str | None = typer.Option(
        None, help="Config file (default: ~/.config/harp/sites.yaml)."
    ),
) -> None:
    """Select the default site (used when --site is omitted)."""
    from harp.sites import SitesConfig

    try:
        store = SitesConfig.load(config)
        store.set_default(name)
        store.save()
    except HarpError as e:
        raise _fail(e) from None
    print(f"Default site is now '{name}'.")


# ---------------------------------------------------------------------------
# Observation log
# ---------------------------------------------------------------------------

log_app = typer.Typer(name="log", help="Record and review what you actually imaged.")
app.add_typer(log_app)


def _log_store(path: str | None):
    """Load the observation log, or exit with a helpful error."""
    from harp.log import ObservationLog

    try:
        return ObservationLog.load(path)
    except HarpError as e:
        raise _fail(e) from None


@log_app.command("add")
def log_add(
    target: str = typer.Argument(..., help="Target imaged, e.g. M42."),
    date: str | None = typer.Option(None, help="Session date YYYY-MM-DD (default: today)."),
    subs: int | None = typer.Option(None, help="Number of sub-exposures kept."),
    exposure: float | None = typer.Option(None, help="Length of one sub-exposure (s)."),
    filter_name: str | None = typer.Option(
        None, "--filter", help="Filter used, e.g. L-eXtreme, Ha, none."
    ),
    site: str | None = typer.Option(None, help="Site label."),
    rig: str | None = typer.Option(None, help="Optics label."),
    notes: str | None = typer.Option(None, help="Free-text notes."),
    interactive: bool = typer.Option(
        True,
        "--interactive/--no-interactive",
        help="Prompt for the fields left unset. Use --no-interactive in scripts.",
    ),
    path: str | None = typer.Option(
        None, help="Log file (default: ~/.config/harp/observations.yaml)."
    ),
) -> None:
    """Record one imaging session.

    Fully scriptable with flags; run it bare and it asks for the rest, which
    is the mode that actually gets used at the end of a session.
    """
    from harp.log import LogEntry, today_iso

    store = _log_store(path)
    date = date or today_iso()

    # Only prompt for what was not supplied, so a partially-flagged call does
    # not re-ask what the caller already answered.
    if interactive:
        if subs is None:
            subs = typer.prompt("Sub-exposures kept", default=0, type=int) or None
        if exposure is None:
            exposure = typer.prompt("Exposure per sub (s)", default=0.0, type=float) or None
        if filter_name is None:
            filter_name = typer.prompt("Filter", default="", show_default=False) or ""
        if notes is None:
            notes = typer.prompt("Notes", default="", show_default=False) or ""

    entry = LogEntry(
        target=target,
        date=date,
        subs=subs,
        exposure_s=exposure,
        filter_name=filter_name or "",
        site=site or "",
        rig=rig or "",
        notes=notes or "",
    )
    store.add(entry)
    try:
        store.save()
    except OSError as e:
        raise _fail(e) from None

    total = store.integration_for(target)
    from harp.log import fmt_integration

    print(f"Logged {entry.target} on {entry.date}: {entry.integration_label}")
    print(
        f"Total on {entry.target}: {fmt_integration(total)} over {len(store.for_target(target))} session(s)"
    )
    print(f"Log: {store.path}")


@log_app.command("list")
def log_list(
    path: str | None = typer.Option(
        None, help="Log file (default: ~/.config/harp/observations.yaml)."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Show per-target totals, most-imaged first."""
    store = _log_store(path)
    totals = store.totals()
    if as_json:
        import json

        from harp.api import API_VERSION

        print(
            json.dumps(
                {
                    "api_version": API_VERSION,
                    "log": str(store.path),
                    "targets": [
                        {
                            "target": t.target,
                            "sessions": t.sessions,
                            "integration_s": round(t.integration_s, 1),
                            "integration": t.integration_label,
                            "first_date": t.first_date,
                            "last_date": t.last_date,
                            "filters": t.filters,
                        }
                        for t in totals
                    ],
                },
                indent=2,
            )
        )
        return
    print(f"Log: {store.path}")
    if not totals:
        print("(nothing logged yet — record a session with 'harp log add TARGET')")
        return
    print(f"{'target':<24} {'total':>9} {'runs':>5}  {'first':<11}{'last':<11} filters")
    for t in totals:
        print(
            f"{t.target:<24} {t.integration_label:>9} {t.sessions:>5}  "
            f"{t.first_date:<11}{t.last_date:<11} {', '.join(t.filters)}"
        )


@log_app.command("show")
def log_show(
    target: str = typer.Argument(..., help="Target to show every session for."),
    path: str | None = typer.Option(
        None, help="Log file (default: ~/.config/harp/observations.yaml)."
    ),
) -> None:
    """List every recorded session on one target."""
    from harp.log import fmt_integration

    store = _log_store(path)
    entries = store.for_target(target)
    if not entries:
        print(f"No sessions logged for '{target}'.")
        return
    print(f"{'date':<12} {'integration':>12} {'subs':>5} {'exp(s)':>8}  filter")
    for e in entries:
        subs = "--" if e.subs is None else str(e.subs)
        exp = "--" if e.exposure_s is None else f"{e.exposure_s:g}"
        print(f"{e.date:<12} {e.integration_label:>12} {subs:>5} {exp:>8}  {e.filter_name}")
        if e.notes:
            print(f"{'':<12} note: {e.notes}")
    total = sum(e.integration_s for e in entries)
    print(f"\nTotal: {fmt_integration(total)} over {len(entries)} session(s)")
