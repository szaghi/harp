"""Polar alignment: refracted pole altitude and polar-scope reticle geometry.

Two stages of a polar alignment need two different kinds of number, and the
split is the whole point of this module.

COARSE (phone sensors). The mount is swung to the celestial pole using a
compass: azimuth 0 (north) or 180 (south), altitude ``|latitude|``. That is
pure geometry, needs no ephemeris, and the Android tab computes it locally.
Refraction is a 1-3 arcmin correction there -- an order of magnitude below the
1-2 deg a phone magnetometer can actually deliver -- so it is noise at this
stage and this module's refraction helper is NOT for the compass HUD.

FINE (polar scope). The user looks through the mount's polar scope and turns
the az/alt bolts until the pole star sits on its reticle mark. Here the
working scale is arcminutes and both corrections matter:

* The pole to aim at is the REFRACTED pole, which sits above the true pole by
  ``refracted_pole_altitude`` - ``|lat|`` (2.7' at lat 20, 0.5' at lat 65).
* Polaris is not at the pole. Its APPARENT (precessed) separation is what the
  reticle radius must reflect: 37.6' in 2026, against the 44.2' one would get
  from the J2000 catalogue position. Using the catalogue number places the
  mark ~7' wrong -- a gross error at this scale.

The reticle result is deliberately reported in astronomical truth (position
angle measured east of north) PLUS an explicit mount transform, rather than
baked into one vendor's convention. Polar-scope reticles are mirror-reversed
and vendors disagree on clock-face orientation; folding that into the physics
would make a silent 180-degree error indistinguishable from a correct answer.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import datetime

import astropy.units as u
import numpy as np
from astropy.coordinates import FK5, SkyCoord
from astropy.time import Time

from harp.errors import EphemerisError


def _allow_offline_iers() -> None:
    """Make sidereal-time work offline for dates past the bundled IERS table.

    Two settings, both needed and both idempotent:

    * ``auto_download = False`` -- never phone home for fresh Earth-orientation
      data (the same hard offline guarantee the planner sets).
    * ``iers_degraded_accuracy = 'warn'`` -- the default is ``'error'``, which
      makes ``Time.sidereal_time('apparent', ...)`` raise ``IERSRangeError``
      the moment the observation date falls outside the bundled IERS-B table.
      The Android build ships whatever table was current when it was packaged,
      so a plan a few months ahead trips this. Downgrading to a warning lets
      the computation proceed with degraded polar-motion/UT1 corrections --
      a sub-arcsecond error, utterly negligible against a 37.6' reticle, and
      the warning itself is swallowed by the callers' ``catch_warnings``.
    """
    from astropy.utils import iers

    iers.conf.auto_download = False
    iers.conf.iers_degraded_accuracy = "warn"


__all__ = [
    "MOUNTS",
    "Mount",
    "ReticleFix",
    "polaris_hour_angle",
    "polaris_pole_separation",
    "pole_star",
    "refracted_pole_altitude",
    "reticle_position",
]

# Pole stars, ICRS J2000. Polaris (alpha UMi) for the north; sigma Octantis
# for the south -- at magnitude 5.4 it is a far poorer target than Polaris,
# which is why southern polar scopes use a small asterism, but its position
# is what the reticle radius is built from.
_POLARIS = SkyCoord(ra=37.95456067 * u.deg, dec=89.26410897 * u.deg, frame="icrs")
_SIGMA_OCT = SkyCoord(ra=317.19536 * u.deg, dec=-88.9564 * u.deg, frame="icrs")


@dataclass(frozen=True)
class Mount:
    """Polar-scope reticle convention for one mount family.

    Parameters
    ----------
    label : str
        Display name.
    mirrored : bool
        Whether the polar scope presents a mirror-reversed field, i.e. the
        clock face runs anticlockwise as seen by the observer.
    rotation_deg : float
        Extra rotation of the reticle's ``0`` mark relative to the celestial
        meridian, degrees.
    verified : bool
        Whether this convention has been confirmed against real hardware.
        Unverified presets are shown to the user with a caveat -- an
        unverified reticle transform can be silently 180 degrees out.
    """

    label: str
    mirrored: bool
    rotation_deg: float
    verified: bool


# Only 'generic' and Sky-Watcher are marked verified. 'generic' is trivially
# correct because it applies no transform at all -- it reports the raw
# astronomical position angle. Sky-Watcher is the most common polar scope and
# its mirror-reversed clock face is well documented. The others are
# best-effort placeholders, flagged so the UI can caveat them rather than
# present a possibly-180-degrees-out answer as fact; set `verified=True` only
# after checking against the actual instrument.
MOUNTS: dict[str, Mount] = {
    "generic": Mount("Generic / raw angle", mirrored=False, rotation_deg=0.0, verified=True),
    "skywatcher": Mount("Sky-Watcher", mirrored=True, rotation_deg=0.0, verified=True),
    "ioptron": Mount("iOptron", mirrored=True, rotation_deg=0.0, verified=False),
    "celestron": Mount("Celestron", mirrored=True, rotation_deg=0.0, verified=False),
}


def pole_star(lat_deg: float) -> SkyCoord:
    """Return the pole star for the observer's hemisphere.

    Parameters
    ----------
    lat_deg : float
        Observer latitude in degrees, north positive.

    Returns
    -------
    astropy.coordinates.SkyCoord
        Polaris for ``lat_deg >= 0``, sigma Octantis otherwise (ICRS J2000).
    """
    return _POLARIS if lat_deg >= 0.0 else _SIGMA_OCT


def refracted_pole_altitude(
    lat_deg: float, *, pressure_hpa: float = 1010.0, temp_c: float = 10.0
) -> float:
    """Apparent altitude of the celestial pole, including refraction.

    The true pole sits at ``|lat|``; the atmosphere lifts its apparent
    position. Uses Bennett's formula with the standard pressure/temperature
    scaling. The correction is small but one-sided, so it biases every
    alignment the same way if ignored: +2.7' at latitude 20, +1.1' at 42,
    +0.8' at 52, +0.5' at 65.

    Parameters
    ----------
    lat_deg : float
        Observer latitude in degrees, north positive. Only ``|lat|`` is used.
    pressure_hpa : float
        Station pressure in hectopascals. Pass ``0`` to disable refraction
        (a vacuum), which returns ``|lat|`` exactly.
    temp_c : float
        Air temperature in degrees Celsius.

    Returns
    -------
    float
        Apparent pole altitude in degrees.

    Raises
    ------
    EphemerisError
        If ``|lat_deg|`` exceeds 90.
    """
    if abs(lat_deg) > 90.0:
        raise EphemerisError(f"latitude out of range: {lat_deg}")
    h = abs(lat_deg)
    if pressure_hpa <= 0.0:
        return h
    # Bennett 1982: R in arcmin for h in degrees, at 1010 hPa / 10 C.
    r_arcmin = 1.0 / np.tan(np.radians(h + 7.31 / (h + 4.4)))
    # Standard density scaling for non-standard conditions.
    r_arcmin *= (pressure_hpa / 1010.0) * (283.0 / (273.0 + temp_c))
    return float(h + r_arcmin / 60.0)


def _apparent(star: SkyCoord, when_utc: datetime) -> SkyCoord:
    """Precess a J2000 catalogue position to the equinox of date."""
    _allow_offline_iers()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return star.transform_to(FK5(equinox=Time(when_utc)))


def polaris_pole_separation(when_utc: datetime, *, lat_deg: float = 45.0) -> float:
    """Apparent separation of the pole star from the celestial pole, arcmin.

    Precession is the whole story here: Polaris was 44.2' from the pole at
    J2000 and is 37.6' in 2026, closing to a minimum near 2100. The reticle
    radius must use the apparent value, not the catalogue one.

    Parameters
    ----------
    when_utc : datetime.datetime
        Instant of observation (UTC).
    lat_deg : float
        Observer latitude, used only to pick the hemisphere's pole star.

    Returns
    -------
    float
        Separation in arcminutes.
    """
    star = _apparent(pole_star(lat_deg), when_utc)
    # Angular distance from the pole of date = 90 - |dec|.
    return float((90.0 - abs(star.dec.deg)) * 60.0)


def polaris_hour_angle(when_utc: datetime, lon_deg: float, *, lat_deg: float = 45.0) -> float:
    """Local hour angle of the pole star, degrees in ``[0, 360)``.

    The hour angle is what drives the reticle clock face: it is the angle,
    measured westward along the equator, between the observer's meridian and
    the star's. It advances a full turn per sidereal day, so the reticle mark
    moves visibly over a session.

    Parameters
    ----------
    when_utc : datetime.datetime
        Instant of observation (UTC).
    lon_deg : float
        Observer longitude in degrees, EAST positive (HARP's convention).
    lat_deg : float
        Observer latitude, used only to pick the hemisphere's pole star.

    Returns
    -------
    float
        Local hour angle in degrees, ``[0, 360)``.
    """
    _allow_offline_iers()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t = Time(when_utc)
        # Apparent sidereal time at Greenwich, shifted east to the observer.
        lst = t.sidereal_time("apparent", longitude=lon_deg * u.deg).deg
    ra = _apparent(pole_star(lat_deg), when_utc).ra.deg
    return float((lst - ra) % 360.0)


@dataclass(frozen=True)
class ReticleFix:
    """Where to place the pole star on a polar-scope reticle.

    Parameters
    ----------
    hour_angle_deg : float
        Local hour angle of the pole star, degrees.
    separation_arcmin : float
        Apparent pole-star-to-pole separation (the reticle radius).
    position_angle_deg : float
        Astronomical truth: position angle of the star around the pole as
        seen by the observer, measured east of north in the horizontal
        frame, degrees in ``[0, 360)``. Independent of any mount convention.
        Equals ``-hour_angle_deg`` (mod 360); verified against astropy's
        ``position_angle`` in the ``AltAz`` frame to 0.01 deg over a full
        sidereal turn.
    reticle_angle_deg : float
        ``position_angle_deg`` after the mount's mirror/rotation transform --
        the angle to actually draw, clockwise from the reticle's ``0`` mark.
    clock : str
        ``reticle_angle_deg`` rendered as an ``HH:MM`` clock position, the
        form polar-scope reticles are labelled in.
    pole_altitude_deg : float
        Refracted pole altitude to set on the altitude bolt.
    mount : Mount
        The convention applied.
    """

    hour_angle_deg: float
    separation_arcmin: float
    position_angle_deg: float
    reticle_angle_deg: float
    clock: str
    pole_altitude_deg: float
    mount: Mount


def _clock_string(angle_deg: float) -> str:
    """Render an angle as an ``HH:MM`` clock position (12 h = 360 deg)."""
    minutes = round(angle_deg / 360.0 * 720.0) % 720
    hh, mm = divmod(minutes, 60)
    return f"{12 if hh == 0 else hh:02d}:{mm:02d}"


def reticle_position(
    when_utc: datetime,
    lat_deg: float,
    lon_deg: float,
    *,
    mount: str = "generic",
    pressure_hpa: float = 1010.0,
    temp_c: float = 10.0,
) -> ReticleFix:
    """Full polar-scope solution for one instant and site.

    Parameters
    ----------
    when_utc : datetime.datetime
        Instant of observation (UTC).
    lat_deg, lon_deg : float
        Observer latitude and longitude in degrees (longitude EAST positive).
    mount : str
        Key into :data:`MOUNTS` selecting the reticle convention.
    pressure_hpa, temp_c : float
        Atmospheric conditions for the refraction correction.

    Returns
    -------
    ReticleFix
        Reticle radius, angle, clock position and refracted pole altitude.

    Raises
    ------
    EphemerisError
        If ``mount`` is not a known convention, or the latitude is invalid.
    """
    try:
        conv = MOUNTS[mount]
    except KeyError:
        raise EphemerisError(
            f"unknown mount convention {mount!r}; expected one of {sorted(MOUNTS)}"
        ) from None

    ha = polaris_hour_angle(when_utc, lon_deg, lat_deg=lat_deg)
    sep = polaris_pole_separation(when_utc, lat_deg=lat_deg)

    # Position angle of the star around the pole, east of north, in the
    # observer's horizontal frame -- the angle that actually rotates on the
    # reticle over the night. At hour angle 0 the star is at UPPER
    # culmination, on the meridian ABOVE the pole, i.e. position angle 0;
    # increasing hour angle carries it westward, which is decreasing position
    # angle east of north. Hence PA = -HA. Verified against astropy's
    # AltAz-frame position_angle to 0.01 deg across a full sidereal turn.
    #
    # Note this is NOT the equatorial-frame position angle, which is a
    # constant (a function of the star's RA alone) and useless as a reticle
    # angle. Do not "simplify" this to an equatorial PA.
    #
    # In the southern hemisphere the observer faces the south pole, which
    # reverses the apparent sense of rotation, giving PA = +HA.
    pa = (-ha) % 360.0 if lat_deg >= 0.0 else ha % 360.0

    # Mount transform: a mirror-reversed field flips the sense of the angle,
    # then the reticle's own zero mark is rotated into place.
    angle = ((-pa if conv.mirrored else pa) + conv.rotation_deg) % 360.0

    return ReticleFix(
        hour_angle_deg=ha,
        separation_arcmin=sep,
        position_angle_deg=pa,
        reticle_angle_deg=angle,
        clock=_clock_string(angle),
        pole_altitude_deg=refracted_pole_altitude(
            lat_deg, pressure_hpa=pressure_hpa, temp_c=temp_c
        ),
        mount=conv,
    )
