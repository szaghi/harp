"""Exposure planning for camera-on-tracker sessions.

Answers the three questions an astrophotographer actually asks at the start of
a night: how long may a single sub be, what ISO puts the sky background in a
useful place, and how many frames does the integration I want cost me in time
and storage.

Deliberately free of any Android dependency, so the CLI, the test suite and
the app share one definition of the physics. Every function returns ``None``
rather than a guess when its inputs are underdetermined -- the same neutrality
rule :mod:`harp.sky` follows, and for the same reason: a fabricated number is
worse than an absent one when the user is deciding how to spend a clear night.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from harp.errors import HarpError

__all__ = [
    "ExposureError",
    "ExposurePlan",
    "SensorSpec",
    "frames_for_integration",
    "npf_max_seconds",
    "recommend_iso",
    "sky_limited_seconds",
]

#: Sky-background target as a fraction of the range, and the working band.
#:
#: A sub wants the background high enough to swamp read noise but low enough
#: to leave headroom for stars. Roughly a fifth to a third is the conventional
#: band; the midpoint is what the ISO recommendation aims for.
SKY_TARGET_FRACTION = 0.25
SKY_TARGET_MIN = 0.15
SKY_TARGET_MAX = 0.33

#: Reference point the sky model is anchored to.
#:
#: At SQM 21.0 (a good rural site), f/2.0 and ISO 800, a 15 s sub lands near
#: the target fraction on a small-pixel phone sensor. Everything else scales
#: from here by sky brightness, aperture and sensitivity. A calibration
#: anchor, not a physical constant: it exists so the advisor can give a
#: concrete number instead of a shrug.
#:
#: The anchor is deliberately set for *small pixels and a short well*, not for
#: a DSLR. Anchoring at a DSLR-like 60 s makes every phone-length sub demand a
#: four-figure ISO, which pins the recommendation at the analog ceiling for
#: the entire usable exposure range and renders the advisor useless. With this
#: anchor a 17 s sub asks for ISO ~640 and an 8.3 s sub ~1300, which is the
#: behaviour the ceiling is meant to bound rather than swallow.
_REF_SQM = 21.0
_REF_FNUM = 2.0
_REF_ISO = 800.0
_REF_SECONDS = 15.0

#: Smallest ``cos(dec)`` the NPF rule will divide by, about 89.4 degrees.
_POLE_COS_FLOOR = 0.01


class ExposureError(HarpError):
    """Raised when exposure inputs are physically impossible."""


@dataclass(frozen=True)
class SensorSpec:
    """The camera-side inputs the exposure model needs.

    Distinct from :class:`harp.optics.Rig`, which describes a telescope-plus-
    camera pair in terms of framing geometry. This is the photometric view of
    the same hardware: what the lens gathers, and how finely the sensor
    samples it.

    Parameters
    ----------
    focal_mm : float
        Effective focal length in mm.
    f_number : float
        Focal ratio. Governs light per unit sensor area, so it drives both the
        trailing limit and the sky-background rate.
    pixel_pitch_um : float
        Physical pixel size in micrometres. Finer pixels show trailing sooner,
        which is why the NPF rule beats the older "500 rule" on phones.
    iso_min, iso_max : int
        Settable sensitivity range.
    max_analog_iso : int or None
        Highest ISO reached by analog gain. Above it the sensor multiplies
        after the ADC, amplifying noise and signal alike while spending
        highlight headroom, so recommendations never exceed it when known.
    """

    focal_mm: float
    f_number: float
    pixel_pitch_um: float
    iso_min: int = 50
    iso_max: int = 3200
    max_analog_iso: int | None = None

    def __post_init__(self) -> None:
        if self.focal_mm <= 0:
            raise ExposureError(f"focal length must be positive, got {self.focal_mm}")
        if self.f_number <= 0:
            raise ExposureError(f"f-number must be positive, got {self.f_number}")
        if self.pixel_pitch_um <= 0:
            raise ExposureError(f"pixel pitch must be positive, got {self.pixel_pitch_um}")
        if self.iso_max < self.iso_min:
            raise ExposureError(f"iso_max {self.iso_max} below iso_min {self.iso_min}")

    @property
    def usable_max_iso(self) -> int:
        """Highest ISO worth using: the analog ceiling when the sensor reports one."""
        if self.max_analog_iso is None:
            return self.iso_max
        return min(self.iso_max, self.max_analog_iso)


def npf_max_seconds(sensor: SensorSpec, declination_deg: float = 0.0) -> float:
    """Longest untracked exposure keeping stars point-like, in seconds.

    Implements the NPF rule::

        t = (35 N + 30 p) / (f cos d)

    with ``N`` the f-number, ``p`` the pixel pitch in micrometres, ``f`` the
    focal length in mm and ``d`` the declination. It supersedes the "500 rule"
    by accounting for aperture and pixel pitch, which matters enormously at
    phone pixel scales where the older rule is optimistic by a factor of two
    or more.

    Trailing follows the component of diurnal motion across the frame, which
    falls off as ``cos d``: a target near the pole barely moves, so the limit
    grows steeply as ``d`` approaches +/-90 degrees.

    Parameters
    ----------
    sensor : SensorSpec
        Camera optics and sampling.
    declination_deg : float, default 0.0
        Target declination in degrees; the default is the worst case.

    Returns
    -------
    float
        Maximum exposure in seconds, finite even at the pole.

    Notes
    -----
    On a driven mount this limit does not apply -- tracking removes the
    diurnal motion the rule describes. Use :func:`sky_limited_seconds` there.
    """
    cos_d = math.cos(math.radians(declination_deg))
    # Guard the pole: cos(90) is 0 and would divide by zero. The floor sits at
    # about 89.4 degrees, past any practical target, and keeps this finite.
    cos_d = max(abs(cos_d), _POLE_COS_FLOOR)
    return (35.0 * sensor.f_number + 30.0 * sensor.pixel_pitch_um) / (sensor.focal_mm * cos_d)


def sky_limited_seconds(
    sensor: SensorSpec,
    iso: int,
    sky_mag: float | None,
    *,
    target_fraction: float = SKY_TARGET_FRACTION,
) -> float | None:
    """Exposure that fills ``target_fraction`` of the range with sky, in seconds.

    On a tracker the limit is no longer star trailing but the sky itself:
    expose long enough and light pollution alone saturates the frame, taking
    the stars with it. This is the ceiling that replaces
    :func:`npf_max_seconds` once the mount is driven.

    Scales the reference point by the three things that change the background
    rate: sky brightness (a magnitude scale, so ``10 ** 0.4`` per magnitude),
    aperture (light per unit area goes as ``N ** -2``) and sensitivity
    (linear in ISO).

    Parameters
    ----------
    sensor : SensorSpec
        Camera optics.
    iso : int
        Sensitivity the frame will be shot at.
    sky_mag : float or None
        Zenith sky brightness in mag/arcsec^2, from
        :func:`harp.sky.sky_brightness`. ``None`` when the site declares
        neither Bortle class nor SQM.
    target_fraction : float, optional
        Fraction of the range the background should reach.

    Returns
    -------
    float or None
        Seconds, or ``None`` when ``sky_mag`` is unknown -- in which case the
        caller falls back on the hardware limit rather than inventing one.
    """
    if sky_mag is None:
        return None
    if iso <= 0:
        raise ExposureError(f"iso must be positive, got {iso}")
    if target_fraction <= 0:
        raise ExposureError(f"target fraction must be positive, got {target_fraction}")

    # Darker sky (larger magnitude) means a slower background rate, so the
    # usable exposure grows by 10**0.4 per magnitude.
    sky_factor = 10.0 ** (0.4 * (sky_mag - _REF_SQM))
    # Light per unit sensor area scales as the inverse square of the f-number.
    aperture_factor = (sensor.f_number / _REF_FNUM) ** 2
    iso_factor = _REF_ISO / float(iso)
    scale = target_fraction / SKY_TARGET_FRACTION
    return _REF_SECONDS * sky_factor * aperture_factor * iso_factor * scale


def recommend_iso(
    sensor: SensorSpec,
    exposure_s: float,
    sky_mag: float | None,
) -> int | None:
    """ISO putting the sky background near the target fraction.

    The inverse of :func:`sky_limited_seconds`: given the exposure the
    hardware can actually deliver -- often a fixed ceiling on a phone -- solve
    for the sensitivity that lands the background in the working band.

    Clamped to the sensor's usable range, which stops at the analog ceiling
    when one is reported: digital gain above it adds no information, only
    noise and lost headroom.

    Parameters
    ----------
    sensor : SensorSpec
        Camera optics and sensitivity limits.
    exposure_s : float
        The sub length actually being used, seconds.
    sky_mag : float or None
        Zenith sky brightness, mag/arcsec^2.

    Returns
    -------
    int or None
        Recommended ISO, or ``None`` when the sky is unknown.
    """
    if sky_mag is None:
        return None
    if exposure_s <= 0:
        raise ExposureError(f"exposure must be positive, got {exposure_s}")

    sky_factor = 10.0 ** (0.4 * (sky_mag - _REF_SQM))
    aperture_factor = (sensor.f_number / _REF_FNUM) ** 2
    ideal = _REF_ISO * sky_factor * aperture_factor * (_REF_SECONDS / exposure_s)
    return round(max(sensor.iso_min, min(sensor.usable_max_iso, ideal)))


@dataclass(frozen=True)
class ExposurePlan:
    """What a requested integration costs in frames, time and storage.

    The advisor's highest-value output on a device with a short exposure
    ceiling: when a sub is capped at 8-17 seconds, an hour of integration is
    hundreds of frames, and the numbers that decide whether the night is
    feasible are the storage and the wall clock, not the physics.

    Parameters
    ----------
    frames : int
        Sub-exposures needed to reach the requested integration.
    exposure_s : float
        Length of each sub, seconds.
    integration_s : float
        Light actually collected, ``frames * exposure_s``.
    wall_clock_s : float
        Elapsed time including per-frame write overhead.
    bytes_estimate : int
        Storage the frames will occupy.
    fits_window : bool or None
        Whether the run fits the target's remaining observable window;
        ``None`` when no window was supplied.
    """

    frames: int
    exposure_s: float
    integration_s: float
    wall_clock_s: float
    bytes_estimate: int
    fits_window: bool | None = None

    def summary(self) -> str:
        """One line a user can act on, for the app's estimate row."""
        hours = self.integration_s / 3600.0
        gib = self.bytes_estimate / (1024.0**3)
        text = (
            f"{self.frames} x {self.exposure_s:.1f} s = {hours:.1f} h "
            f"integration, {gib:.1f} GB, {self.wall_clock_s / 3600.0:.1f} h elapsed"
        )
        if self.fits_window is False:
            text += " - LONGER THAN THE REMAINING WINDOW"
        return text


def frames_for_integration(
    integration_hours: float,
    exposure_s: float,
    *,
    write_overhead_s: float = 2.0,
    bytes_per_frame: int = 20 * 1024 * 1024,
    window_hours: float | None = None,
) -> ExposurePlan:
    """Turn a desired integration into frames, elapsed time and storage.

    Parameters
    ----------
    integration_hours : float
        Total light wanted, hours.
    exposure_s : float
        Length of one sub, seconds.
    write_overhead_s : float, optional
        Per-frame cost of saving the file. A full-resolution DNG is not
        instant, and across hundreds of frames this is the whole difference
        between integration time and wall-clock time.
    bytes_per_frame : int, optional
        Storage per frame; the default suits a ~12 MP DNG.
    window_hours : float or None, optional
        Remaining observable window for the target, from the planner. When
        given, the result records whether the run actually fits.

    Returns
    -------
    ExposurePlan
        Frames, elapsed time, storage, and the window verdict.

    Raises
    ------
    ExposureError
        If the integration or exposure is not positive.
    """
    if integration_hours <= 0:
        raise ExposureError(f"integration must be positive, got {integration_hours}")
    if exposure_s <= 0:
        raise ExposureError(f"exposure must be positive, got {exposure_s}")

    integration_s = integration_hours * 3600.0
    # Round up: asking for two hours and getting one-and-three-quarters
    # because the division did not come out even is not what the user meant.
    frames = max(1, math.ceil(integration_s / exposure_s))
    achieved_s = frames * exposure_s
    wall_clock_s = frames * (exposure_s + write_overhead_s)
    fits = None if window_hours is None else wall_clock_s <= window_hours * 3600.0
    return ExposurePlan(
        frames=frames,
        exposure_s=exposure_s,
        integration_s=achieved_s,
        wall_clock_s=wall_clock_s,
        bytes_estimate=frames * bytes_per_frame,
        fits_window=fits,
    )
