"""Planner bridge: run a full night plan on-device, JSON in/out.

Same contract as the CLI ``--json``: everything crosses the Kotlin/Python
bridge as JSON strings (never Java collections).
"""

from __future__ import annotations

import json
import time
import warnings
from pathlib import Path


def run_plan(request_json: str) -> str:
    """Plan one night; returns the harp.api plan dict (or {"error": ...}).

    Request keys: lat, lon, elev, tz (required); date (YYYY-MM-DD or ""),
    hrz_path (path or ""), focal_mm, sensor ('WxH' or preset), deep (bool),
    mag_limit, top, sharpless (bool, default true), sharpless_min_diam
    (arcmin, default 10), solar_system (bool, default true), ss_moons (bool,
    default false — needs the JPL ephemeris, online).
    """
    t0 = time.perf_counter()
    try:
        req = json.loads(request_json)
        from astropy.utils import iers

        iers.conf.auto_download = False

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from harp.api import (
                Horizon,
                Rig,
                Site,
                build_targets,
                parse_sensor,
                plan_night,
                plan_to_dict,
            )

            site = Site(
                label="phone",
                lat=float(req["lat"]),
                lon=float(req["lon"]),
                elev=float(req.get("elev") or 0.0),
                tz=req["tz"],
            )
            sensor_name, sw, sh = parse_sensor(str(req.get("sensor") or "23.5x15.7"))
            rig = Rig(
                focal_mm=float(req.get("focal_mm") or 800.0),
                sensor_name=sensor_name,
                sensor_w_mm=sw,
                sensor_h_mm=sh,
                overlap=float(req.get("overlap") or 0.15),
            )
            hrz_path = req.get("hrz_path") or ""
            if hrz_path and Path(hrz_path).exists():
                horizon = Horizon.from_hrz(hrz_path)
                horizon_label = "wizard capture"
            else:
                horizon = Horizon.flat(0.0)
                horizon_label = "flat 0 deg (no wizard capture yet)"

            catalogs = [
                c.strip().upper()
                for c in str(req.get("catalogs") or "M").split(",")
                if c.strip()
            ]
            # Solar System bodies (Moon + planets) are on by default, matching
            # the CLI; the app may turn them off or opt into satellites, which
            # need the JPL ephemeris loaded first (online).
            use_solar_system = bool(req.get("solar_system", True))
            ss_moons = bool(req.get("ss_moons") or False)
            if ss_moons:
                from harp.solar_system import load_moon_ephemeris

                load_moon_ephemeris()
            targets = build_targets(
                pyongc_catalogs=catalogs,
                mag_limit=float(req.get("mag_limit") or 11.0),
                use_sharpless=bool(req.get("sharpless", True)),
                sharpless_min_diam=float(req.get("sharpless_min_diam") or 10.0),
                use_solar_system=use_solar_system,
                ss_moons=ss_moons,
            )
            plan = plan_night(
                site=site,
                rig=rig,
                horizon=horizon,
                targets=targets,
                date=(req.get("date") or None),
                grid_min=int(req.get("grid_min") or 10),
                min_moon_sep=float(req.get("moon_sep") or 30.0),
                min_hours=float(req.get("min_hours") or 1.0),
                min_peak_alt=float(req.get("min_peak_alt") or 20.0),
                sort=str(req.get("sort") or "score"),
                horizon_label=horizon_label,
            )
        out = plan_to_dict(
            plan,
            top=int(req.get("top") or 30),
            link_site=str(req.get("link_site") or "simbad"),
        )
        out["elapsed_s"] = round(time.perf_counter() - t0, 1)
        out["n_targets"] = len(targets)
        return json.dumps(out)
    except Exception as e:  # surfaced in the UI, never a crash
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
