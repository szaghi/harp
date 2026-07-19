"""Phase-1 spike: prove the astropy stack runs on-device.

Called from Kotlin via Chaquopy. If this module imports and
:func:`twilight_summary` returns, the whole plan is confirmed: numpy,
astropy (with its pyerfa C extension), astroplan, and the shared
``harp`` core all work on Android.
"""

from __future__ import annotations

import time
import warnings


def stack_versions() -> str:
    """Report the versions of the on-device astro stack."""
    import astroplan
    import astropy
    import numpy

    import harp

    return (
        f"harp {harp.__version__} | numpy {numpy.__version__} | "
        f"astropy {astropy.__version__} | astroplan {astroplan.__version__}"
    )


def twilight_summary(lat: float, lon: float, elev_m: float, tz_name: str) -> str:
    """Compute tonight's astronomical darkness at the given position."""
    t0 = time.perf_counter()
    # bundled IERS-B is plenty for minute-level planning; never download
    from astropy.utils import iers

    iers.conf.auto_download = False

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from astroplan import Observer

        from harp.ephemeris import compute_night, fmt_hm
        from harp.planner import Site

        site = Site(label="phone", lat=lat, lon=lon, elev=elev_m, tz=tz_name)
        observer = Observer(location=site.location, timezone=site.tz)
        window = compute_night(observer, site.zoneinfo, None, 10)

    dt = time.perf_counter() - t0
    return (
        f"{stack_versions()}\n"
        f"Night of {window.day}: astronomical darkness "
        f"{fmt_hm(window.dusk, window.tz)} -> {fmt_hm(window.dawn, window.tz)} "
        f"local ({len(window.times)} grid samples)\n"
        f"computed on-device in {dt:.1f} s"
    )
