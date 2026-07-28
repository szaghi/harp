"""Chaquopy bridge for the Shoot tab's exposure advisor.

Turns the device's measured camera capabilities plus the selected site and
target into a concrete recommendation and, just as importantly, into the
reasoning behind it. NightCap's "Aidie" assistant picks settings for you and
explains nothing; this deliberately does the inverse, because a user who
understands why 17 s at ISO 640 is right can adapt when conditions change.

Every number comes from :mod:`harp.exposure`, so the CLI, the test suite and
the app cannot drift apart.
"""

from __future__ import annotations

import json
from typing import Any

from harp.errors import HarpError
from harp.exposure import (
    SensorSpec,
    frames_for_integration,
    npf_max_seconds,
    recommend_iso,
    sky_limited_seconds,
)
from harp.sky import sky_brightness


def advise(
    focal_mm: float,
    f_number: float,
    pixel_pitch_um: float,
    iso_min: int,
    iso_max: int,
    max_analog_iso: int | None,
    max_exposure_s: float,
    *,
    tracked: bool = True,
    declination_deg: float = 0.0,
    bortle: int | None = None,
    sqm: float | None = None,
    integration_hours: float = 1.0,
    window_hours: float | None = None,
    bytes_per_frame: int = 20 * 1024 * 1024,
) -> dict[str, Any]:
    """Recommend exposure, ISO and frame count, with the reasoning.

    Parameters
    ----------
    focal_mm, f_number, pixel_pitch_um : float
        Lens and sensor geometry, read from Camera2 characteristics.
    iso_min, iso_max : int
        Settable sensitivity range.
    max_analog_iso : int or None
        Analog gain ceiling, when the sensor reports one.
    max_exposure_s : float
        Longest exposure the device actually delivers: the calibrated value
        when the extension probe passed, else the advertised maximum.
    tracked : bool, default True
        Whether the camera is on a driven mount. Off a tracker the NPF
        trailing limit applies; on one it does not.
    declination_deg : float
        Target declination, for the NPF limit.
    bortle, sqm : int or float or None
        Site sky quality. SQM wins when both are given.
    integration_hours : float
        Total light wanted.
    window_hours : float or None
        Remaining observable window for the target, from the planner.
    bytes_per_frame : int
        Storage per frame, for the estimate.

    Returns
    -------
    dict
        JSON-safe recommendation: ``exposure_s``, ``iso``, ``frames``,
        ``storage_bytes``, ``fits_window`` and a ``reasons`` list.
    """
    sensor = SensorSpec(
        focal_mm=focal_mm,
        f_number=f_number,
        pixel_pitch_um=pixel_pitch_um,
        iso_min=iso_min,
        iso_max=iso_max,
        max_analog_iso=max_analog_iso,
    )
    reasons: list[str] = []

    # 1. How long may one sub be? The hardware ceiling always applies; the NPF
    #    trailing limit bites only without a tracker.
    exposure_s = max_exposure_s
    reasons.append(f"Hardware allows up to {max_exposure_s:.1f} s per frame.")

    if tracked:
        reasons.append("On a tracker, so star trailing does not limit the sub length.")
    else:
        npf = npf_max_seconds(sensor, declination_deg)
        if npf < exposure_s:
            exposure_s = npf
            reasons.append(
                f"Untracked at declination {declination_deg:+.0f} deg, stars trail "
                f"beyond {npf:.1f} s (NPF rule), so that is the limit."
            )
        else:
            reasons.append(f"Untracked, NPF allows {npf:.1f} s - the hardware ceiling binds first.")

    # 2. Does the sky saturate before that? Rarely at phone exposures, but it
    #    is the real ceiling at a bright site.
    sky_mag = sky_brightness(bortle=bortle, sqm=sqm)
    iso: int | None = None
    if sky_mag is None:
        reasons.append(
            "No Bortle class or SQM set for this site, so ISO cannot be advised - "
            "set one on the site to get a recommendation."
        )
    else:
        sky_cap = sky_limited_seconds(sensor, sensor.usable_max_iso, sky_mag)
        if sky_cap is not None and sky_cap < exposure_s:
            exposure_s = sky_cap
            reasons.append(
                f"At SQM {sky_mag:.1f} the sky itself saturates the frame after "
                f"{sky_cap:.1f} s, shorter than the hardware limit."
            )
        iso = recommend_iso(sensor, exposure_s, sky_mag)
        if iso is not None:
            reasons.append(
                f"At SQM {sky_mag:.1f}, f/{f_number:.1f} and {exposure_s:.1f} s, "
                f"ISO {iso} puts the sky background in the useful band."
            )
            if max_analog_iso is not None and iso >= max_analog_iso:
                reasons.append(
                    f"That is the analog gain ceiling ({max_analog_iso}); above it "
                    "is digital gain, which adds noise without adding signal."
                )

    # 3. What does the requested integration cost? On a device capped at a few
    #    seconds this is the number that decides whether the night is feasible.
    plan = frames_for_integration(
        integration_hours,
        exposure_s,
        bytes_per_frame=bytes_per_frame,
        window_hours=window_hours,
    )
    reasons.append(
        f"{integration_hours:.1f} h of integration needs {plan.frames} frames, "
        f"about {plan.wall_clock_s / 3600.0:.1f} h elapsed and "
        f"{plan.bytes_estimate / 1024**3:.1f} GB."
    )
    if plan.fits_window is False:
        reasons.append(
            "That is longer than the target's remaining window - shorten the "
            "integration or pick a target that is up for longer."
        )

    return {
        "exposure_s": round(exposure_s, 2),
        "iso": iso,
        "frames": plan.frames,
        "integration_s": round(plan.integration_s, 1),
        "wall_clock_s": round(plan.wall_clock_s, 1),
        "storage_bytes": plan.bytes_estimate,
        "fits_window": plan.fits_window,
        "sky_mag": sky_mag,
        "reasons": reasons,
        "summary": plan.summary(),
    }


def advise_json(request: str) -> str:
    """JSON-in, JSON-out wrapper over :func:`advise` for the Kotlin frontend.

    Chaquopy cannot pass Python keyword arguments from a Kotlin map, so the app
    hands over one JSON object and receives one back -- the same contract
    ``planner_bridge.run_plan`` already uses.

    Errors are returned rather than raised: a Python exception crossing the JNI
    boundary surfaces on the Android side as a bare ``PyException`` carrying no
    useful message, which at a dark site tells the user nothing about what to
    fix. An ``error`` key at least names the failure.

    Parameters
    ----------
    request : str
        JSON object whose keys are :func:`advise` parameter names. Absent keys
        take that function's defaults; ``bortle`` and ``sqm`` may be null.

    Returns
    -------
    str
        JSON object: either :func:`advise`'s result or ``{"error": "..."}``.
    """
    try:
        req = json.loads(request)
        return json.dumps(
            advise(
                focal_mm=float(req["focal_mm"]),
                f_number=float(req["f_number"]),
                pixel_pitch_um=float(req["pixel_pitch_um"]),
                iso_min=int(req["iso_min"]),
                iso_max=int(req["iso_max"]),
                max_analog_iso=req.get("max_analog_iso"),
                max_exposure_s=float(req["max_exposure_s"]),
                tracked=bool(req.get("tracked", True)),
                declination_deg=float(req.get("declination_deg", 0.0)),
                bortle=req.get("bortle"),
                sqm=req.get("sqm"),
                integration_hours=float(req.get("integration_hours", 1.0)),
                window_hours=req.get("window_hours"),
            )
        )
    except (KeyError, TypeError, ValueError, HarpError) as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
