"""Ephemerides: darkness window, target alt-az grids, Moon state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as ddate
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

import astropy.units as u
import numpy as np
from astroplan import FixedTarget, Observer
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.time import Time

from harp.catalog import Target
from harp.errors import EphemerisError

__all__ = [
    "MoonState",
    "NightWindow",
    "compute_night",
    "fmt_hm",
    "moon_state",
    "solar_altaz",
    "solar_apparent_arcmin",
    "target_altaz",
]


def fmt_hm(t: Time, tz: ZoneInfo) -> str:
    """Format an astropy time as local ``HH:MM``."""
    return t.to_datetime(timezone=tz).strftime("%H:%M")


@dataclass(frozen=True)
class NightWindow:
    """Astronomical-darkness window sampled on a regular time grid.

    Parameters
    ----------
    day : datetime.date
        Calendar day the night STARTS on (anchored at local noon).
    dusk, dawn : astropy.time.Time
        Astronomical twilight boundaries.
    times : astropy.time.Time
        Sampling grid from dusk to dawn.
    tz : zoneinfo.ZoneInfo
        Site timezone, for display.
    grid_min : int
        Grid step in minutes.
    """

    day: ddate
    dusk: Time
    dawn: Time
    times: Time
    tz: ZoneInfo
    grid_min: int

    @property
    def dt_hours(self) -> float:
        """Grid step in hours."""
        return self.grid_min / 60.0


def compute_night(observer: Observer, tz: ZoneInfo, date: str | None, grid_min: int) -> NightWindow:
    """Compute the astronomical-darkness window for a night.

    Anchored at local noon of ``date``: the window is the night STARTING on
    that day. Run after midnight, it plans the FOLLOWING evening — pass the
    previous day's date for the night in progress.

    Parameters
    ----------
    observer : astroplan.Observer
        The observing site.
    tz : zoneinfo.ZoneInfo
        Site timezone.
    date : str or None
        ``YYYY-MM-DD``; None means today.
    grid_min : int
        Time-grid resolution in minutes.

    Raises
    ------
    EphemerisError
        If the date is malformed or astronomical darkness never occurs
        (e.g. high-latitude summer).
    """
    if date is None:
        day = datetime.now(tz).date()
    else:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError as e:
            raise EphemerisError(f"bad date {date!r}: expected YYYY-MM-DD") from e

    ref = Time(datetime.combine(day, dtime(12, 0), tzinfo=tz))
    dusk = observer.twilight_evening_astronomical(ref, which="next")
    dawn = observer.twilight_morning_astronomical(dusk, which="next")
    if dusk.masked or dawn.masked or not np.isfinite((dawn - dusk).jd):
        raise EphemerisError(f"no astronomical darkness on {day} at this site")

    n = int((dawn - dusk).to_value(u.min) // grid_min) + 1
    times = dusk + np.arange(n) * (grid_min * u.min)
    return NightWindow(day=day, dusk=dusk, dawn=dawn, times=times, tz=tz, grid_min=grid_min)


def target_altaz(
    observer: Observer, window: NightWindow, targets: list[Target]
) -> tuple[np.ndarray, np.ndarray]:
    """Altitude/azimuth of every target on the night grid.

    Returns
    -------
    (numpy.ndarray, numpy.ndarray)
        ``alt`` and ``az`` in degrees, shape ``(n_targets, n_times)``.
    """
    fixed = [FixedTarget(coord=t.coord, name=t.name) for t in targets]
    aa = observer.altaz(window.times, fixed, grid_times_targets=True)
    return aa.alt.to_value(u.deg), aa.az.to_value(u.deg)


def solar_altaz(
    location: EarthLocation, window: NightWindow, bodies: list[str]
) -> tuple[np.ndarray, np.ndarray]:
    """Altitude/azimuth of Solar System bodies on the night grid.

    Unlike :func:`target_altaz`, position is recomputed per grid sample from
    ``get_body`` — these bodies move relative to the fixed sky.

    Parameters
    ----------
    location : astropy.coordinates.EarthLocation
        Observing site.
    window : NightWindow
        The night grid.
    bodies : list of str
        ``get_body`` names, e.g. ``['moon', 'mars']``.

    Returns
    -------
    (numpy.ndarray, numpy.ndarray)
        ``alt`` and ``az`` in degrees, shape ``(len(bodies), n_times)``.
        Empty ``(0, n_times)`` arrays when ``bodies`` is empty.
    """
    n_t = len(window.times)
    if not bodies:
        return np.empty((0, n_t)), np.empty((0, n_t))
    frame = AltAz(obstime=window.times, location=location)
    alt = np.empty((len(bodies), n_t))
    az = np.empty((len(bodies), n_t))
    for i, name in enumerate(bodies):
        aa = get_body(name, window.times, location).transform_to(frame)
        alt[i] = aa.alt.to_value(u.deg)
        az[i] = aa.az.to_value(u.deg)
    return alt, az


def solar_apparent_arcmin(
    location: EarthLocation, window: NightWindow, body: str, radius_km: float
) -> float:
    """Median apparent disk diameter of a Solar System body over the night.

    The disk is distance- (hence time-) dependent; the median over the grid
    is a stable single value for framing and reporting.

    Parameters
    ----------
    location : astropy.coordinates.EarthLocation
        Observing site (topocentric distance).
    window : NightWindow
        The night grid.
    body : str
        ``get_body`` name.
    radius_km : float
        Equatorial radius of the body.

    Returns
    -------
    float
        Median apparent diameter in arcminutes.
    """
    dist_km = get_body(body, window.times, location).distance.to_value(u.km)
    diam_deg = np.degrees(2.0 * np.arctan(radius_km / dist_km))
    return float(np.median(diam_deg) * 60.0)


@dataclass(frozen=True)
class MoonState:
    """Moon ephemerides over the night grid.

    Parameters
    ----------
    alt : numpy.ndarray
        Moon altitude in degrees per grid sample.
    sep : numpy.ndarray
        Moon separation in degrees, shape ``(n_targets, n_times)``.
    illumination : float
        Illuminated fraction at dusk, 0..1.
    up_str : str
        Human-readable above-horizon interval.
    """

    alt: np.ndarray
    sep: np.ndarray
    illumination: float
    up_str: str

    @property
    def up(self) -> np.ndarray:
        """Boolean mask: Moon above the geometric horizon."""
        return self.alt > 0.0


def moon_state(
    location: EarthLocation,
    observer: Observer,
    window: NightWindow,
    coords: list[SkyCoord],
) -> MoonState:
    """Compute Moon altitude, per-target separation, and illumination."""
    moon = get_body("moon", window.times, location)
    alt = moon.transform_to(AltAz(obstime=window.times, location=location)).alt.to_value(u.deg)
    sep = np.array([moon.separation(c).to_value(u.deg) for c in coords])
    illumination = float(observer.moon_illumination(window.dusk))

    up = alt > 0.0
    if up.any():
        idx = np.where(up)[0]
        up_str = (
            f"{fmt_hm(window.times[idx[0]], window.tz)}-"
            f"{fmt_hm(window.times[idx[-1]], window.tz)} (max {alt.max():.0f} deg)"
        )
    else:
        up_str = "below horizon all night"
    return MoonState(alt=alt, sep=sep, illumination=illumination, up_str=up_str)
