"""Polar-alignment bridge: reticle geometry on-device, JSON in/out.

Same contract as the other bridges: everything crosses the Kotlin/Python
boundary as JSON strings (never Java collections).

Only the FINE stage needs Python. The coarse stage (pole azimuth 0/180,
altitude |lat|) is pure geometry that ``CompassViewModel`` already computes
locally from the GPS fix, so the alignment tab stays fully usable when this
call has not run yet -- the refracted altitude and the reticle simply refine
what the compass already shows.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime


def _default(value: object, fallback: float) -> object:
    """Coalesce only None/missing, so a legitimate 0 survives (`or` would not)."""
    return fallback if value is None else value


def run_polar(request_json: str) -> str:
    """Compute the alignment payload; returns the harp.api dict.

    Request keys: lat, lon (required, degrees, longitude EAST positive);
    when_utc (ISO-8601, default now); mount (default 'generic');
    pressure_hpa (default 1010); temp_c (default 10).

    Returns ``{"error": ...}`` on any failure rather than raising, so a bad
    fix or an unknown mount surfaces in the UI instead of crashing the app.
    """
    try:
        req = json.loads(request_json)
        from astropy.utils import iers

        # Same hard offline guarantee as the planner: never phone home for
        # fresh Earth-orientation data. The bundled IERS-B table is far more
        # than enough for arcminute reticle geometry.
        iers.conf.auto_download = False

        raw_when = str(req.get("when_utc") or "")
        if raw_when:
            when = datetime.fromisoformat(raw_when.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
        else:
            when = datetime.now(UTC)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from harp.api import polar_align_to_dict

            out = polar_align_to_dict(
                when,
                float(req["lat"]),
                float(req["lon"]),
                mount=str(req.get("mount") or "generic"),
                # `or` would turn a deliberate 0 (vacuum -> refraction off) into
                # the default, so coalesce only genuine None/missing.
                pressure_hpa=float(_default(req.get("pressure_hpa"), 1010.0)),
                temp_c=float(_default(req.get("temp_c"), 10.0)),
            )
        out["when_utc"] = when.isoformat()
        return json.dumps(out)
    except Exception as e:  # surfaced in the UI, never a crash
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def list_mounts() -> str:
    """Return the known polar-scope reticle conventions as JSON."""
    try:
        from harp.api import mounts_to_dict

        return json.dumps(mounts_to_dict())
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
