"""Sharpless (Sh2) catalogue of H II regions — offline emission-nebula source.

The Sharpless catalogue (Sharpless 1959, VizieR VII/20) lists 313 H II
regions complete north of Dec -27 deg. These are exactly the large emission
nebulae a deep-sky planner is for, and the ones OpenNGC/pyongc cannot
supply: OpenNGC is NGC/IC only and carries no Sharpless designations, and
H II regions have no integrated magnitude (surface brightness, not
magnitude, is what matters), so a magnitude-filtered catalogue drops them.

The data ships as a small SQLite file (``data/sharpless.db``) vendored from
VizieR VII/20 — a fixed, public-domain, 1959 catalogue that never changes —
built once by ``tools/build_sharpless.py``. No hand-maintained target list,
no network at run time. Coordinates are the VizieR-computed J2000 positions
(precessed from the catalogue's native 1900 equinox).

Every object is emission by construction, so ``narrowband=True``; there is
no magnitude, so these bypass the magnitude cut entirely. Size comes from
the catalogue's maximum-diameter column, feeding the framing and FOV logic.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from importlib.resources import as_file, files

from astropy.coordinates import SkyCoord

from harp.catalog import Target
from harp.errors import CatalogError

log = logging.getLogger(__name__)

__all__ = ["sh2_concordance", "sharpless_sizes", "sharpless_targets"]

_DB_RESOURCE = "data/sharpless.db"
_CONCORD_RESOURCE = "data/sh2_concordance.json"


def sharpless_targets(min_diam_arcmin: float = 10.0) -> list[Target]:
    """Load Sharpless H II regions from the vendored offline catalogue.

    Parameters
    ----------
    min_diam_arcmin : float
        Keep only objects at least this large (maximum angular diameter,
        arcmin). The default of 10' drops the many tiny/compact H II regions
        that are not deep-sky imaging targets; pass 0 to keep all 313.

    Returns
    -------
    list of harp.catalog.Target
        Emission nebulae with ``classification='nebula'``, ``narrowband=True``,
        ``mag=None`` and size from the catalogue diameter. Named ``Sh2-N``.

    Raises
    ------
    CatalogError
        If the vendored database is missing or unreadable.
    """
    try:
        resource = files("harp").joinpath(_DB_RESOURCE)
        with as_file(resource) as db_path:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "SELECT sh2, ra_deg, dec_deg, diam_arcmin, bright "
                    "FROM sharpless WHERE diam_arcmin >= ? ORDER BY sh2",
                    (min_diam_arcmin,),
                ).fetchall()
            finally:
                con.close()
    except (OSError, sqlite3.Error, ModuleNotFoundError) as e:
        raise CatalogError(f"cannot read the Sharpless catalogue ({_DB_RESOURCE}): {e}") from e

    out: list[Target] = []
    for sh2, ra_deg, dec_deg, diam, _bright in rows:
        name = f"Sh2-{sh2}"
        out.append(
            Target(
                name=name,
                kind="HII Ionized region",
                const="",
                mag=None,
                maj_arcmin=float(diam) if diam else None,
                min_arcmin=None,
                narrowband=True,
                coord=SkyCoord(ra_deg, dec_deg, unit="deg", frame="icrs"),
                idents=frozenset({f"SH2-{sh2}"}),
                classification="nebula",
            )
        )
    return out


def sharpless_sizes() -> dict[str, float]:
    """Map ``SH2-N`` identifier -> maximum angular diameter (arcmin), all 313.

    Used as the extent-measured size authority: pyongc/OpenNGC nebula sizes
    come from the LBN bright-plate table and often under-report the imageable
    H-alpha extent by 2-12x, while the Sharpless diameter measures the region.
    """
    return {
        sorted(t.idents)[0]: t.maj_arcmin
        for t in sharpless_targets(min_diam_arcmin=0.0)
        if t.maj_arcmin
    }


def sh2_concordance() -> dict[str, list[str]]:
    """NGC/IC/M cross-identifiers per Sharpless number, from the vendored map.

    Keys are Sharpless numbers as strings, values are normalized designations
    (``'IC1805'``). Empty dict if the concordance file is absent (the size
    override then simply does not apply).
    """
    try:
        resource = files("harp").joinpath(_CONCORD_RESOURCE)
        return json.loads(resource.read_text())
    except (OSError, ValueError, ModuleNotFoundError):
        log.debug("Sh2 concordance unavailable; skipping size override")
        return {}
