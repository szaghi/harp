"""Build src/harp/data/sh2_concordance.json from SIMBAD (build-time only).

Resolves each Sharpless (Sh2-N) object to its NGC/IC/Messier cross-identifiers
via SIMBAD, so the catalogue merge can override pyongc's (LBN-derived, often
too small) size with the Sharpless extent and attach the right identity.

Needs network + astroquery; the shipped package needs neither — the resulting
JSON is committed and read offline. Throttled to be polite to SIMBAD.

    python -m pip install astroquery
    python tools/build_sh2_concordance.py
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "harp" / "data" / "sh2_concordance.json"
_DESIG = re.compile(r"^(NGC|IC|M)\s*0*(\d+)\s*$")


def _crossids(simbad, sh2: int) -> list[str]:
    """NGC/IC/M designations SIMBAD lists for Sh2-N (empty if none/unknown)."""
    for _ in range(3):
        try:
            table = simbad.query_objectids(f"Sh2-{sh2}")
        except Exception:
            time.sleep(2.0)
            continue
        if table is None:
            return []
        out: set[str] = set()
        for row in table:
            ident = str(row["id"]).strip()
            m = _DESIG.match(ident)
            if m:
                out.add(f"{m.group(1)}{m.group(2)}")
        return sorted(out)
    return []


def main() -> None:
    from astroquery.simbad import Simbad

    simbad = Simbad()
    simbad.TIMEOUT = 30
    concord: dict[str, list[str]] = {}
    for n in range(1, 314):
        ids = _crossids(simbad, n)
        if ids:
            concord[str(n)] = ids
        if n % 50 == 0:
            print(f"  ...{n}/313, {len(concord)} cross-refs", flush=True)
        time.sleep(0.4)  # be polite; avoids the empty-result throttling

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(concord, indent=0, sort_keys=True))
    print(f"wrote {len(concord)} Sh2->NGC/IC/M cross-refs to {OUT}")


if __name__ == "__main__":
    main()
