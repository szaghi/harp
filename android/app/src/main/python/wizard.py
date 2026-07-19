"""Horizon-wizard bridge: measured true-azimuth vertices -> .hrz content.

The app applies the WMM declination on-device (Android GeomagneticField),
so the vertices arriving here are already in TRUE azimuth: declination 0.
"""

from __future__ import annotations

import json


def make_hrz(points: list, blocked_alt: float = 90.0) -> str:
    """Build a .hrz from ``[[true_az, alt], ...]``; returns JSON for Kotlin.

    Returns
    -------
    str
        JSON object: ``{"hrz": <file content>, "problems": [<warnings>]}``.
    """
    from harp.horizon import build_profile, validate_profile

    vertices = [(float(az), float(alt)) for az, alt in points]
    profile = build_profile(vertices, declination=0.0, blocked_alt=blocked_alt)
    problems = validate_profile(profile)
    lines = ["# Az Alt  (HARP wizard horizon - true north, degrees)"]
    lines += [f"{a:.1f} {h:.1f}" for a, h in profile]
    return json.dumps({"hrz": "\n".join(lines) + "\n", "problems": problems})
