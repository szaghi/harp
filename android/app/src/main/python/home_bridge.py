"""Home-dashboard bridge: tonight's headline numbers, JSON in/out.

Deliberately cheap. The Home tab shows the two facts checked before anything
else -- how much astronomical darkness there is, and what the Moon is doing --
so it must NOT pay for a catalogue load or a full ranked plan. Only the
darkness window and the Moon are computed; ranking is what the Plan tab is
for.

Same contract as the other bridges: everything crosses the Kotlin/Python
boundary as JSON strings (never Java collections).
"""

from __future__ import annotations

import json
import warnings


def tonight(request_json: str) -> str:
    """Summarise tonight's darkness window and Moon for the Home dashboard.

    Request keys: lat, lon, tz (required); elev (default 0); date
    (YYYY-MM-DD or "" for tonight).

    Returns ``{"error": ...}`` on any failure rather than raising, so a bad
    fix or a missing timezone degrades to a quiet dash in the UI instead of
    crashing the launcher screen.
    """
    try:
        req = json.loads(request_json)
        from astropy.utils import iers

        # Same hard offline guarantee as the planner, plus tolerance for a
        # bundled IERS table older than the requested date (see harp.polar).
        iers.conf.auto_download = False
        iers.conf.iers_degraded_accuracy = "warn"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import astropy.units as u
            import numpy as np
            from astroplan import Observer
            from astropy.coordinates import AltAz, get_body

            from harp.ephemeris import compute_night, fmt_hm
            from harp.planner import Site

            site = Site(
                label="phone",
                lat=float(req["lat"]),
                lon=float(req["lon"]),
                elev=float(req.get("elev") or 0.0),
                tz=req["tz"],
            )
            observer = Observer(location=site.location, timezone=site.tz)
            window = compute_night(observer, site.zoneinfo, req.get("date") or None, 10)

            # Moon altitude across the darkness grid. harp.ephemeris.moon_state
            # is not used here: it also computes a per-TARGET separation matrix,
            # and the Home tab has no targets to separate from.
            loc = site.location
            moon = get_body("moon", window.times, loc)
            alt = moon.transform_to(AltAz(obstime=window.times, location=loc)).alt.to_value(u.deg)
            up = alt > 0.0
            if up.any():
                idx = np.where(up)[0]
                moon_up = (
                    f"{fmt_hm(window.times[idx[0]], window.tz)}-"
                    f"{fmt_hm(window.times[idx[-1]], window.tz)}"
                )
            else:
                moon_up = "down all night"

            dark_hours = float((window.dawn - window.dusk).to_value("hour"))
            out = {
                "day": str(window.day),
                "dark_start": fmt_hm(window.dusk, window.tz),
                "dark_end": fmt_hm(window.dawn, window.tz),
                "dark_hours": round(dark_hours, 2),
                "moon_illum": round(float(observer.moon_illumination(window.dusk)), 3),
                "moon_up": moon_up,
            }
        return json.dumps(out)
    except Exception as e:  # surfaced as a dash in the UI, never a crash
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
