"""Regenerate src/harp/data/sharpless.db from VizieR VII/20 (build-time only).

Run this once to (re)vendor the Sharpless (Sh2) catalogue. It needs network
access and astroquery; the *shipped* package needs neither — the resulting
SQLite file is committed and read offline by harp.sharpless.

    python -m pip install astroquery
    python tools/build_sharpless.py

The catalogue is Sharpless 1959 (public domain); it does not change, so this
is a one-shot vendoring, not a runtime dependency.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "src" / "harp" / "data" / "sharpless.db"


def main() -> None:
    from astroquery.vizier import Vizier

    # _RAJ2000/_DEJ2000 are VizieR-computed J2000 positions (precessed from
    # the catalogue's native 1900 equinox) — no hand precession needed.
    vizier = Vizier(
        columns=["Sh2", "_RAJ2000", "_DEJ2000", "Diam", "Form", "Struct", "Bright", "Stars"],
        row_limit=-1,
    )
    table = vizier.get_catalogs("VII/20")[0]
    if len(table) != 313:
        raise SystemExit(f"expected 313 Sharpless objects, got {len(table)}")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE sharpless (
            sh2         INTEGER PRIMARY KEY,  -- Sharpless number (Sh2-N)
            ra_deg      REAL NOT NULL,        -- J2000 RA  (VizieR-computed)
            dec_deg     REAL NOT NULL,        -- J2000 Dec
            diam_arcmin INTEGER,              -- max angular diameter
            form        INTEGER,              -- 1 circular 2 elliptical 3 irregular
            struct      INTEGER,              -- 1 amorphous .. 3 filamentary
            bright      INTEGER,              -- 1 faintest .. 3 brightest
            stars       INTEGER               -- # associated stars
        )
        """
    )
    con.executemany(
        "INSERT INTO sharpless VALUES (?,?,?,?,?,?,?,?)",
        [
            (
                int(r["Sh2"]),
                float(r["_RAJ2000"]),
                float(r["_DEJ2000"]),
                int(r["Diam"]),
                int(r["Form"]),
                int(r["Struct"]),
                int(r["Bright"]),
                int(r["Stars"]),
            )
            for r in table
        ],
    )
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM sharpless").fetchone()[0]
    con.close()
    print(f"wrote {n} Sharpless objects to {DB_PATH} ({DB_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
