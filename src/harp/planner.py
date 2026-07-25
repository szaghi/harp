"""Night planning: visibility through the site horizon, Moon impact, ranking."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import astropy.units as u
import numpy as np
from astroplan import Observer
from astropy.coordinates import EarthLocation

from harp.catalog import Target, suggest_detail
from harp.ephemeris import (
    MoonState,
    NightWindow,
    comet_altaz,
    comet_apparent_mag,
    compute_night,
    fmt_hm,
    moon_state,
    solar_altaz,
    solar_apparent_arcmin,
    target_altaz,
)
from harp.horizon import Horizon
from harp.optics import Rig
from harp.sky import contrast_score, sky_brightness

__all__ = [
    "NightPlan",
    "PlanRow",
    "Site",
    "desirability",
    "longest_window",
    "moon_impact",
    "moon_score",
    "plan_night",
]


@dataclass(frozen=True)
class Site:
    """Observing site: geographic position + label.

    Parameters
    ----------
    label : str
        Display name.
    lat, lon : float
        Latitude/longitude in degrees (longitude East positive).
    elev : float
        Elevation in meters.
    tz : str
        IANA timezone name, e.g. ``'Europe/Rome'``.
    bortle : int or None
        Bortle class 1-9 estimating the site's light pollution. Optional:
        without it (and without ``sqm``) the sky-contrast term stays neutral
        and the ranking is exactly what it was before that term existed.
    sqm : float or None
        Measured zenith sky brightness, mag/arcsec^2. Wins over ``bortle``
        when both are given, being a measurement rather than an estimate.
    """

    label: str
    lat: float
    lon: float
    elev: float
    tz: str
    bortle: int | None = None
    sqm: float | None = None

    @property
    def sky_mag(self) -> float | None:
        """Zenith sky brightness, mag/arcsec^2, or None if undeclared."""
        return sky_brightness(self.bortle, self.sqm)

    @property
    def location(self) -> EarthLocation:
        """The site as an astropy EarthLocation."""
        return EarthLocation(lat=self.lat * u.deg, lon=self.lon * u.deg, height=self.elev * u.m)

    @property
    def zoneinfo(self) -> ZoneInfo:
        """The site timezone as a ZoneInfo."""
        return ZoneInfo(self.tz)


@dataclass(frozen=True)
class PlanRow:
    """One ranked target in the night plan (one row of the report table)."""

    index: int  # position in the plan's target/ephemeris arrays
    name: str
    kind: str
    classification: str  # nature: nebula/galaxy/.../planet/moon/sun
    const: str
    mag: float | None
    hours: float  # total usable hours
    cont_hours: float  # longest continuous run
    window: str  # local HH:MM-HH:MM of the continuous run
    alt_max: float  # peak altitude within the usable window
    az_peak: float  # azimuth at the peak
    peak_time: str  # local HH:MM of the peak
    moon_sep: float  # minimum Moon separation within the window
    moon: str  # Moon-impact classification
    frame: str  # '1 frame' or 'mosaic NxM'
    detail: str  # single-frame suggestion for mosaic targets
    score: float  # composite desirability, 0-100 (see desirability())


@dataclass(frozen=True)
class NightPlan:
    """Complete result of a night's planning, ready for reporting."""

    site: Site
    rig: Rig
    horizon: Horizon
    horizon_label: str
    window: NightWindow
    targets: list[Target]
    alt: np.ndarray  # (n_targets, n_times) degrees
    az: np.ndarray  # (n_targets, n_times) degrees
    vis: np.ndarray  # (n_targets, n_times) bool: above horizon and Moon-clear
    moon: MoonState
    rows: list[PlanRow]  # ranked by usable hours, descending


def _solar_radius_map() -> dict[str, float]:
    """Map every known Solar System ``body`` name to its equatorial radius."""
    from harp.solar_system import SS_BODIES, SS_MOONS

    return {b.body: b.radius_km for b in (*SS_BODIES, *SS_MOONS)}


def _angular_sep(
    alt1: np.ndarray, az1: np.ndarray, alt2: np.ndarray, az2: np.ndarray
) -> np.ndarray:
    """Great-circle separation between two alt-az tracks, in degrees.

    Used for the Moon separation of comets, whose position moves per grid
    sample and so has no single :class:`~astropy.coordinates.SkyCoord`. The
    Moon track ``(alt1, az1)`` is ``(n_times,)``; the comet tracks
    ``(alt2, az2)`` are ``(n_comets, n_times)``; the result broadcasts to
    ``(n_comets, n_times)``.
    """
    a1 = np.radians(alt1)
    a2 = np.radians(alt2)
    daz = np.radians(az2 - az1)
    cos_sep = np.sin(a1) * np.sin(a2) + np.cos(a1) * np.cos(a2) * np.cos(daz)
    return np.degrees(np.arccos(np.clip(cos_sep, -1.0, 1.0)))


def longest_window(mask: np.ndarray) -> tuple[int, int, int]:
    """Longest run of True in a boolean mask.

    Returns
    -------
    (int, int, int)
        ``(n_samples, i_start, i_end)``; start/end are -1 when no run exists.
    """
    best = cur = 0
    bs = be = -1
    s = 0
    for j, m in enumerate(mask):
        if m:
            if cur == 0:
                s = j
            cur += 1
            if cur > best:
                best, bs, be = cur, s, j
        else:
            cur = 0
    return best, bs, be


def moon_impact(narrowband: bool, sep_min: float, moon_up_frac: float, illumination: float) -> str:
    """Classify the Moon's impact on imaging a target.

    Parameters
    ----------
    narrowband : bool
        Halpha emission target imaged in narrowband (tolerates the Moon).
    sep_min : float
        Minimum Moon separation in the usable window, degrees.
    moon_up_frac : float
        Fraction of the usable window with the Moon above the horizon.
    illumination : float
        Moon illuminated fraction, 0..1.

    Returns
    -------
    str
        ``'none'`` (Moon down), ``'ok(NB)'``/``'close'`` (narrowband), or
        ``'low'``/``'med'``/``'high'`` (broadband impact).
    """
    if moon_up_frac == 0:
        return "none"
    if narrowband:
        return "close" if sep_min < 20 else "ok(NB)"
    if illumination < 0.30 and sep_min > 60:
        return "low"
    if sep_min < 40 or illumination > 0.70:
        return "high"
    return "med"


def moon_score(narrowband: bool, sep_min: float, moon_up_frac: float, illumination: float) -> float:
    """Continuous Moon-impact factor for scoring, in [0.2, 1.0].

    The companion of :func:`moon_impact`: that returns a coarse verdict
    *string* for display, this returns the smooth factor the score uses.
    Splitting them fixes the ranking cliff where the old bucket factors
    (broadband ``med`` = 0.5 vs narrowband ``ok(NB)`` = 0.9) sorted *every*
    galaxy/cluster below *every* narrowband nebula on any moonlit night,
    regardless of how bright, high, or Moon-distant the broadband target was.

    The penalty is graded by the actual geometry:

    - **Moon down** (``moon_up_frac == 0``): 1.0, no penalty.
    - **Narrowband**: near-immune; only a close bright Moon scatters into a
      3 nm passband. Ranges ~0.85 (Moon <20 deg) to 1.0.
    - **Broadband**: penalty scales with how much the Moon actually pollutes
      the sky — its illuminated fraction and how much of the window it is up —
      and is relieved by separation. A dim, distant, briefly-up Moon costs
      little (~0.8); a full, close, all-night Moon costs a lot (~0.25). So a
      bright high galaxy with the Moon low and far now competes with a
      narrowband target instead of being quarantined beneath it.

    Parameters
    ----------
    narrowband : bool
        Halpha target imaged in narrowband (tolerates the Moon).
    sep_min : float
        Minimum Moon separation across the usable window, degrees.
    moon_up_frac : float
        Fraction of the usable window with the Moon above the horizon, 0..1.
    illumination : float
        Moon illuminated fraction, 0..1.

    Returns
    -------
    float
        Scoring factor in [0.2, 1.0]; higher is better.
    """
    if moon_up_frac <= 0.0:
        return 1.0
    if narrowband:
        # a 3 nm passband rejects almost all moonlight; only a close bright
        # Moon leaks measurable scatter.
        return 0.85 if sep_min < 20.0 else 1.0
    # broadband: brightness in the sky ~ illumination * time-up, relieved by
    # angular distance. sep_factor: 0 at the scope, 1 by ~90 deg away.
    sky = illumination * moon_up_frac
    sep_factor = min(max(sep_min, 0.0) / 90.0, 1.0)
    penalty = sky * (1.0 - 0.7 * sep_factor)  # 0 (benign) .. ~1 (worst)
    return max(0.2, 1.0 - 0.8 * penalty)


def _fov_match(maj_arcmin: float | None, fov_long: float) -> float:
    """How well the object size suits the field of view, in (0, 1].

    Peaks when the major axis spans 20-100% of the long FOV side; tiny
    specks and many-panel mosaics score progressively lower. Unknown size
    is neutral (0.6) — no reward, no punishment.
    """
    if maj_arcmin is None:
        return 0.6
    r = maj_arcmin / fov_long
    if r < 0.05:
        return 0.3
    if r < 0.2:
        return 0.3 + 0.7 * (r - 0.05) / 0.15
    if r <= 1.0:
        return 1.0
    return max(0.2, 1.0 / r)


def _prominence(mag: float | None, maj_arcmin: float | None) -> float:
    """Intrinsic prominence of a target, in [0.35, 1.0].

    A brightness/interest term added so observability alone cannot let the
    (moon-immune, high, all-night) Sharpless H II regions sweep the ranking
    and bury bright Messier/NGC objects on moonlit nights. It is deliberately
    floored well above zero: prominence *ranks*, it must not annihilate an
    otherwise-observable target (the composite score is a geometric mean, so
    a near-zero factor would drop the object off the list entirely).

    Two regimes:

    - **Magnitude known** (Messier, most NGC/IC): brighter scores higher.
      ``mag <= 6`` saturates at 1.0; it tapers to the floor by ``mag ~ 13``.
    - **Magnitude absent** (Sharpless and other magnitude-less emission,
      ``mag is None``): a neutral-low baseline modulated by angular size, so
      the big showpiece regions (Heart, Soul, ...) stay competitive while the
      obscure small H II regions settle below the bright classics.

    Parameters
    ----------
    mag : float or None
        Integrated visual magnitude, or None when the catalogue has none.
    maj_arcmin : float or None
        Major-axis angular size, arcmin; used only in the magnitude-less case.

    Returns
    -------
    float
        Prominence factor in [0.35, 1.0].
    """
    floor = 0.35
    if mag is not None:
        # mag 6 -> 1.0, mag 13 -> ~floor; linear in between.
        return max(floor, min(1.0, 1.0 - (mag - 6.0) / 7.0))
    # magnitude-less: baseline lifted by size (arcmin). 15' -> ~0.45,
    # 90'+ -> ~0.75; the big Sharpless showpieces stay ahead of the small ones.
    if maj_arcmin is None:
        return 0.5
    return max(floor, min(0.75, 0.40 + 0.35 * min(maj_arcmin / 90.0, 1.0)))


def desirability(
    hours: float,
    cont_hours: float,
    alt_max: float,
    moon_factor: float,
    maj_arcmin: float | None,
    fov_long: float,
    mag: float | None = None,
    contrast: float = 1.0,
) -> float:
    """Composite 0-100 desirability score for one target on one night.

    Weighted geometric mean of seven terms, so a near-zero factor (no
    continuous window, hopeless Moon) sinks the score instead of being
    averaged away:

    - continuous window (weight 3): ``min(cont_hours/3, 1)`` — the longest
      uninterrupted run is what sizes an imaging session; saturates at 3 h;
    - total hours (weight 1): ``min(hours/5, 1)``;
    - peak altitude (weight 2): ``sin(alt_max)`` — the inverse-airmass proxy;
    - Moon (weight 2): ``moon_factor`` in [0.2, 1.0] from :func:`moon_score` —
      graded by illumination, up-fraction and separation, NOT a broadband /
      narrowband step, so a bright high galaxy with the Moon low and far is
      no longer quarantined below every narrowband nebula;
    - FOV match (weight 1): see :func:`_fov_match`;
    - prominence (weight 2): see :func:`_prominence` — a brightness/interest
      term so pure observability cannot let the moon-immune Sharpless regions
      bury bright classics on moonlit nights;
    - sky contrast (weight 2): see :func:`harp.sky.contrast_score` — the
      target's surface brightness against the site's light pollution. It is
      exactly ``1.0`` (neutral) unless the site declares a Bortle class or an
      SQM reading, so a config that says nothing about its sky ranks precisely
      as it did before this term existed.
    """
    terms = [
        (3.0, min(cont_hours / 3.0, 1.0)),
        (1.0, min(hours / 5.0, 1.0)),
        (2.0, math.sin(math.radians(max(alt_max, 0.0)))),
        (2.0, moon_factor),
        (1.0, _fov_match(maj_arcmin, fov_long)),
        (2.0, _prominence(mag, maj_arcmin)),
        (2.0, contrast),
    ]
    num = sum(w * math.log(max(t, 1e-3)) for w, t in terms)
    den = sum(w for w, _ in terms)
    return 100.0 * math.exp(num / den)


def plan_night(
    site: Site,
    rig: Rig,
    horizon: Horizon,
    targets: list[Target],
    date: str | None = None,
    grid_min: int = 5,
    min_moon_sep: float = 30.0,
    min_hours: float = 1.0,
    min_peak_alt: float = 20.0,
    comet_mag_limit: float | None = None,
    horizon_label: str = "",
    sort: str = "score",
) -> NightPlan:
    """Plan one night: rank targets observable through the site horizon.

    A target counts as observable at a grid sample only when its altitude
    clears the horizon mask AT ITS OWN AZIMUTH and the Moon is farther than
    ``min_moon_sep``.

    Parameters
    ----------
    site : Site
        Observing site.
    rig : Rig
        Telescope + camera, for mosaic framing.
    horizon : Horizon
        Azimuth-dependent obstruction mask (true north).
    targets : list of Target
        Candidate objects.
    date : str or None
        Night to plan, ``YYYY-MM-DD``; None = tonight.
    grid_min : int
        Time-grid resolution in minutes.
    min_moon_sep : float
        Drop grid samples with the Moon closer than this (degrees).
    min_hours : float
        Keep targets with at least this many usable hours.
    min_peak_alt : float
        Keep targets peaking at least this high (degrees).
    comet_mag_limit : float or None
        Drop comets whose PREDICTED apparent magnitude for the night is fainter
        than this. Applies only to comets (their brightness is distance- and
        time-dependent, so it can only be judged after propagation); ``None``
        keeps every comet. A comet with an unpredictable brightness (no ``H``)
        is always kept -- unknown is not the same as faint.
    horizon_label : str
        Horizon description for the report header (e.g. the .hrz filename).
    sort : str
        Row ranking: ``'score'`` (composite desirability, default),
        ``'hours'`` (total usable hours, the historical order),
        ``'alt'`` (peak altitude), or ``'name'`` (alphabetical).

    Returns
    -------
    NightPlan
        Ranked rows plus the full ephemeris arrays for charting.
    """
    # Hard offline guarantee: never let astropy phone home for fresh IERS
    # Earth-orientation data. The bundled IERS-B table is ample for
    # minute-level planning, and this keeps the CLI as network-free as the
    # Android bridge (which sets the same flag).
    from astropy.utils import iers

    iers.conf.auto_download = False
    # astropy/astroplan warn on IERS staleness and non-strict twilight
    # convergence; neither affects minute-level planning.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        observer = Observer(location=site.location, timezone=site.tz)
        window = compute_night(observer, site.zoneinfo, date, grid_min)
        # Split fixed deep-sky objects (a single ICRS coord) from Solar System
        # bodies (no fixed coord — position recomputed per grid sample). The
        # two ephemeris paths are stitched back into the original target order
        # so all downstream indexing (rows, curves, charts) is unaffected.
        # Three position paths, each a different ephemeris: fixed deep-sky
        # objects (one ICRS coord), Solar System bodies (get_body by name),
        # and comets (two-body Kepler propagation from orbital elements). A
        # comet carries no fixed coord AND no body name, so it must be split
        # out before the fixed path, which would dereference a None coord.
        is_solar = np.array([t.body is not None for t in targets])
        is_comet = np.array([t.elements is not None for t in targets])
        is_fixed = ~is_solar & ~is_comet
        n_t = len(window.times)
        alt = np.empty((len(targets), n_t))
        az = np.empty((len(targets), n_t))
        fixed = [t for t, f in zip(targets, is_fixed, strict=True) if f]
        solar = [t for t in targets if t.body is not None]
        comets = [t for t in targets if t.elements is not None]
        if fixed:
            f_alt, f_az = target_altaz(observer, window, fixed)
            alt[is_fixed], az[is_fixed] = f_alt, f_az
        if solar:
            s_alt, s_az = solar_altaz(site.location, window, [t.body for t in solar])
            alt[is_solar], az[is_solar] = s_alt, s_az
        if comets:
            c_alt, c_az = comet_altaz(site.location, window, [t.elements for t in comets])
            alt[is_comet], az[is_comet] = c_alt, c_az
        # Moon separation is meaningful for fixed objects AND comets (both are
        # faint sources competing with moonlight), but not for Solar System
        # bodies (bright disks, and the Moon's separation to itself is 0). SS
        # bodies get a placeholder (large) separation so the min-sep filter
        # never drops them. The Moon's own alt-az track is shared by all.
        moon = moon_state(
            site.location, observer, window, [t.coord for t in fixed] if fixed else []
        )
        # Comet Moon separation from the already-computed alt-az tracks: the
        # comet has no fixed coord, so its separation varies per grid sample.
        # Angular separation on the sphere between the Moon and each comet.
        comet_sep = (
            _angular_sep(moon.alt, moon.az, alt[is_comet], az[is_comet])
            if comets
            else np.empty((0, n_t))
        )

    solar_radii = _solar_radius_map()
    # Full-length arrays in original order: fixed rows use real Moon
    # separation; comet rows use their per-sample separation; SS rows use +inf
    # so the min-sep cut is a no-op for them.
    sep = np.full((len(targets), n_t), np.inf)
    if fixed:
        sep[is_fixed] = moon.sep
    if comets:
        sep[is_comet] = comet_sep
    moon_up = moon.up  # (n_times,) shared across targets

    above = alt > horizon.altitude(az)
    vis = above & (sep > min_moon_sep)
    hours = vis.sum(axis=1) * window.dt_hours
    peak_i = np.array(
        [
            np.where(vis[i], alt[i], -90).argmax() if vis[i].any() else -1
            for i in range(len(targets))
        ]
    )

    rows: list[PlanRow] = []
    for i, t in enumerate(targets):
        win = vis[i]
        peak_alt = float(np.where(win, alt[i], -90).max()) if win.any() else -90.0
        if hours[i] < min_hours or peak_alt < min_peak_alt:
            continue
        up_frac = float(moon_up[win].mean()) if win.any() else 0.0
        cw, cs, ce = longest_window(win)
        win_str = (
            f"{fmt_hm(window.times[cs], window.tz)}-{fmt_hm(window.times[ce], window.tz)}"
            if cw > 0
            else "--"
        )
        cont_h = round(cw * window.dt_hours, 1)
        # Magnitude used for ranking and the table. For most targets it is the
        # catalogue value; a comet overrides it with the magnitude PREDICTED
        # for tonight (H is an absolute magnitude, meaningless as-is against
        # apparent deep-sky magnitudes).
        mag_use = t.mag
        if t.body is not None:
            # Solar System body: live apparent disk, no mosaic/Moon-impact
            # logic. The disk size flows into the FOV score so a tiny planet
            # disk scores realistically for a deep-sky rig. Moon separation is
            # not meaningful here (the Moon is itself one of these targets), so
            # it is reported as 0 and the verdict carries the 'n/a' meaning.
            maj = solar_apparent_arcmin(site.location, window, t.body, solar_radii[t.body])
            frame = "planetary"
            moon_verdict = "n/a"
            moon_factor = 1.0  # Moon impact undefined for a Solar System body
            sep_disp = 0.0
        elif t.elements is not None:
            # Comet: a moving, diffuse source. Unlike a planet it IS hurt by
            # moonlight, so it gets a real Moon separation and impact verdict
            # (treated as broadband -- a comet's coma is continuum, not a
            # narrowband line). It has no meaningful apparent disk to frame, so
            # the FOV term stays neutral (maj=None) and the frame is 'comet'.
            # Its brightness is the standard comet law evaluated for tonight,
            # so a close faint comet correctly outranks a distant bright one.
            maj = None
            frame = "comet"
            mag_use = comet_apparent_mag(site.location, window, t.elements)
            # Prune a comet predicted too faint to image tonight. A comet with
            # no predictable brightness (mag_use is None) is kept: unknown is
            # not faint.
            if comet_mag_limit is not None and mag_use is not None and mag_use > comet_mag_limit:
                continue
            sep_min = float(sep[i][win].min()) if win.any() else 180.0
            sep_disp = sep_min
            moon_verdict = moon_impact(False, sep_min, up_frac, moon.illumination)
            moon_factor = moon_score(False, sep_min, up_frac, moon.illumination)
        else:
            maj = t.maj_arcmin
            frame = rig.framing(t.maj_arcmin, t.min_arcmin)
            sep_min = float(sep[i][win].min())
            sep_disp = sep_min
            moon_verdict = moon_impact(t.narrowband, sep_min, up_frac, moon.illumination)
            moon_factor = moon_score(t.narrowband, sep_min, up_frac, moon.illumination)
        rows.append(
            PlanRow(
                index=i,
                name=t.name,
                kind=t.kind,
                classification=t.classification,
                const=t.const,
                mag=round(mag_use, 1) if mag_use is not None else None,
                hours=round(float(hours[i]), 1),
                cont_hours=cont_h,
                window=win_str,
                alt_max=round(peak_alt),
                az_peak=round(float(az[i, peak_i[i]])),
                peak_time=fmt_hm(window.times[peak_i[i]], window.tz),
                moon_sep=round(sep_disp),
                moon=moon_verdict,
                frame=frame,
                detail=suggest_detail(t.name) if frame.startswith("mosaic") else "",
                score=round(
                    desirability(
                        hours=float(hours[i]),
                        cont_hours=cont_h,
                        alt_max=peak_alt,
                        moon_factor=moon_factor,
                        maj_arcmin=maj,
                        fov_long=rig.fov_long,
                        mag=mag_use,
                        # Solar System bodies and comets are exempt: a planet
                        # is a bright disk, and a comet's surface brightness is
                        # unknown and highly variable (outgassing), with no
                        # reliable size -- applying the sky-contrast model to
                        # either would be false precision, so it stays neutral.
                        contrast=1.0
                        if (t.body is not None or t.elements is not None)
                        else contrast_score(
                            t.mag,
                            t.maj_arcmin,
                            t.min_arcmin,
                            site.sky_mag,
                            narrowband=t.narrowband,
                            aperture_mm=rig.aperture_mm,
                        ),
                    ),
                    1,
                ),
            )
        )
    keys = {
        "score": lambda r: r.score,
        "hours": lambda r: r.hours,
        "alt": lambda r: r.alt_max,
        "name": lambda r: r.name.lower(),
    }
    rows.sort(key=keys.get(sort, keys["score"]), reverse=sort != "name")

    return NightPlan(
        site=site,
        rig=rig,
        horizon=horizon,
        horizon_label=horizon_label,
        window=window,
        targets=targets,
        alt=alt,
        az=az,
        vis=vis,
        moon=moon,
        rows=rows,
    )
