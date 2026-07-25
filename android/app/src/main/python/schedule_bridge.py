"""Multi-night scheduling bridge for the Android app, JSON in/out.

Answers "when should I shoot this target?" over the shared
:mod:`harp.schedule` core, so the app and the ``harp when`` CLI rank nights
identically -- same desirability score, same tie-breaks.

COST. This is by far the most expensive call the app makes: it plans one night
per day in the window, and Chaquopy runs several times slower than desktop
CPython. A 30-night sweep that takes ~2 s on a laptop can take 10-20 s on a
phone. Two consequences shaped this module:

* The default window is deliberately SHORT (14 nights). The caller may ask for
  more, but the common question -- "when in the next fortnight?" -- should not
  cost a minute.
* The target is resolved and filtered BEFORE the sweep, never after. Planning
  the whole catalogue once per night would multiply the cost by the catalogue
  size; that is the difference between an interactive feature and an unusable
  one.

The caller is expected to run this off the UI thread and show progress.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

#: Nights to score when the caller does not say. Half the CLI's 30, because a
#: phone is slower and the fortnight ahead is the question actually asked.
DEFAULT_DAYS = 14

#: Hard ceiling, so a typo in the request cannot start a multi-minute sweep
#: the user has no way to cancel.
MAX_DAYS = 90


def run_when(request_json: str) -> str:
    """Rank the coming nights for one target.

    Request keys: target (required), lat, lon, tz (required); elev, hrz_path,
    focal_mm, sensor, catalogs, start (YYYY-MM-DD), days, top, bortle, sqm.

    Returns the :func:`harp.api.schedule_to_dict` payload with the nights
    already ranked best-first, or ``{"error": ...}``. Never raises: a bad
    target or a missing fix must surface in the UI, not crash the app.
    """
    try:
        req = json.loads(request_json)
        target_query = str(req.get("target") or "").strip()
        if not target_query:
            return json.dumps({"error": "no target given"})

        from astropy.utils import iers

        # Same hard offline guarantee as the planner, plus tolerance for a
        # bundled IERS table older than the requested night (see harp.polar).
        iers.conf.auto_download = False
        iers.conf.iers_degraded_accuracy = "warn"

        days = int(req.get("days") or DEFAULT_DAYS)
        days = max(1, min(days, MAX_DAYS))

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from harp.api import (
                Horizon,
                Rig,
                Site,
                best_nights,
                build_targets,
                find_targets,
                parse_sensor,
                schedule_to_dict,
                score_nights,
            )

            site = Site(
                label=str(req.get("label") or "phone"),
                lat=float(req["lat"]),
                lon=float(req["lon"]),
                elev=float(req.get("elev") or 0.0),
                tz=req["tz"],
                bortle=req.get("bortle"),
                sqm=req.get("sqm"),
            )
            sensor_name, sw, sh = parse_sensor(str(req.get("sensor") or "23.5x15.7"))
            rig = Rig(
                focal_mm=float(req.get("focal_mm") or 800.0),
                sensor_name=sensor_name,
                sensor_w_mm=sw,
                sensor_h_mm=sh,
            )
            hrz_path = req.get("hrz_path") or ""
            horizon = (
                Horizon.from_hrz(hrz_path)
                if hrz_path and Path(hrz_path).exists()
                else Horizon.flat(0.0)
            )

            catalogs = [
                c.strip().upper() for c in str(req.get("catalogs") or "M").split(",") if c.strip()
            ]
            # mag_limit is deliberately wide open: the user named this target,
            # so hiding it behind a brightness cut would be perverse. Solar
            # System bodies are excluded -- "which night suits Jupiter" is not
            # a question this command answers well, since a planet's
            # observability changes on a different timescale.
            catalogue = build_targets(
                pyongc_catalogs=catalogs,
                mag_limit=99.0,
                use_solar_system=False,
            )
            matches = find_targets(target_query, catalogue)
            if not matches:
                return json.dumps({"error": f"no target matches {target_query!r}"})
            target = matches[0]

            nights = score_nights(
                site=site,
                rig=rig,
                horizon=horizon,
                target=target,
                start=(req.get("start") or None),
                days=days,
            )

        top = req.get("top")
        ranked = best_nights(nights, int(top) if top else None)
        out = schedule_to_dict(target.name, site.label, ranked)
        # The caller needs to distinguish "all bad nights" from "never rises",
        # and computing it here keeps that judgement in one place.
        out["any_usable"] = any(n.usable for n in nights)
        out["days_scored"] = len(nights)
        return json.dumps(out)
    except Exception as e:  # surfaced in the UI, never a crash
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
