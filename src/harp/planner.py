"""Night planning: visibility through the site horizon, Moon impact, ranking."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import astropy.units as u
import numpy as np
from astroplan import Observer
from astropy.coordinates import EarthLocation

from harp.catalog import Target, suggest_detail
from harp.ephemeris import MoonState, NightWindow, compute_night, fmt_hm, moon_state, target_altaz
from harp.horizon import Horizon
from harp.optics import Rig

__all__ = ["NightPlan", "PlanRow", "Site", "longest_window", "moon_impact", "plan_night"]


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
    """

    label: str
    lat: float
    lon: float
    elev: float
    tz: str

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
    horizon_label: str = "",
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
    horizon_label : str
        Horizon description for the report header (e.g. the .hrz filename).

    Returns
    -------
    NightPlan
        Ranked rows plus the full ephemeris arrays for charting.
    """
    # astropy/astroplan warn on IERS staleness and non-strict twilight
    # convergence; neither affects minute-level planning.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        observer = Observer(location=site.location, timezone=site.tz)
        window = compute_night(observer, site.zoneinfo, date, grid_min)
        alt, az = target_altaz(observer, window, targets)
        moon = moon_state(site.location, observer, window, [t.coord for t in targets])

    above = alt > horizon.altitude(az)
    vis = above & (moon.sep > min_moon_sep)
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
        sep_min = float(moon.sep[i][win].min())
        up_frac = float(moon.up[win].mean()) if win.any() else 0.0
        cw, cs, ce = longest_window(win)
        win_str = (
            f"{fmt_hm(window.times[cs], window.tz)}-{fmt_hm(window.times[ce], window.tz)}"
            if cw > 0
            else "--"
        )
        frame = rig.framing(t.maj_arcmin, t.min_arcmin)
        rows.append(
            PlanRow(
                index=i,
                name=t.name,
                kind=t.kind,
                const=t.const,
                mag=t.mag,
                hours=round(float(hours[i]), 1),
                cont_hours=round(cw * window.dt_hours, 1),
                window=win_str,
                alt_max=round(peak_alt),
                az_peak=round(float(az[i, peak_i[i]])),
                peak_time=fmt_hm(window.times[peak_i[i]], window.tz),
                moon_sep=round(sep_min),
                moon=moon_impact(t.narrowband, sep_min, up_frac, moon.illumination),
                frame=frame,
                detail=suggest_detail(t.name) if frame.startswith("mosaic") else "",
            )
        )
    rows.sort(key=lambda r: r.hours, reverse=True)

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
