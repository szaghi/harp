"""N.I.N.A.-importable target lists (the Telescopius CSV dialects).

N.I.N.A.'s sequencer imports two CSV flavors (SimpleSequenceVM.cs, headers
matched lower-cased):

- **mosaic plans**: ``pane``, ``ra``, ``dec``, ``position angle (east)`` —
  one sequencer target per panel;
- **observing lists**: ``familiar name``, ``catalogue entry``, coordinates,
  optional ``position angle (east)``.

For observing lists we emit ONLY the ``... (j2000)`` coordinate headers,
never a bare ``right ascension`` column: N.I.N.A.'s importer re-reads the
``right ascension`` field for the declination too (a copy-paste bug in
SimpleSequenceVM), so a bare-named column would silently corrupt every
declination. With only the ``(j2000)`` variants present, both lookups fall
through to the correct columns.

Coordinates are written as ``05h35m17s`` / ``+57d30m00s``: N.I.N.A. parses
them with a digits-only regex (sign from any ``-``), so these are
unambiguous for it and readable for humans.
"""

from __future__ import annotations

import csv
from pathlib import Path

import astropy.units as u
from astropy.coordinates import SkyCoord

from harp.mosaic import Panel
from harp.planner import NightPlan

__all__ = ["write_mosaic_csv", "write_targets_csv"]


def _hms(coord: SkyCoord) -> str:
    return coord.ra.to_string(unit=u.hourangle, sep="hms", precision=0, pad=True)


def _dms(coord: SkyCoord) -> str:
    return coord.dec.to_string(sep="dms", precision=0, alwayssign=True, pad=True)


def _solar_dusk_coord(plan: NightPlan, body: str) -> SkyCoord:
    """ICRS position of a Solar System body at the plan's dusk.

    A moving body has no fixed J2000 coordinate; this is a single-instant
    snapshot at dusk, transformed to ICRS so the ``(J2000)`` columns are
    honest. It is stale by dawn and wrong on any other night — N.I.N.A. should
    re-slew from its own ephemeris; the snapshot is only a placeholder so the
    body still appears in the imported list.
    """
    from astropy.coordinates import get_body

    return get_body(body, plan.window.dusk, plan.site.location).icrs


def write_targets_csv(plan: NightPlan, path: str | Path, top: int | None = None) -> int:
    """Write the ranked plan as a N.I.N.A.-importable observing-list CSV.

    Parameters
    ----------
    plan : NightPlan
        The night plan; rows are exported in their ranked order.
    path : str or pathlib.Path
        Output CSV file.
    top : int or None
        Export only the first ``top`` rows (None = all).

    Returns
    -------
    int
        Number of targets written. Solar System bodies are included with a
        dusk-snapshot coordinate and a name marked ``(<date> dusk)``.
    """
    rows = plan.rows if top is None else plan.rows[:top]
    path = Path(path)
    written = 0
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "Catalogue Entry",
                "Familiar Name",
                "Right Ascension (J2000)",
                "Declination (J2000)",
                "Position Angle (East)",
            ]
        )
        for r in rows:
            t = plan.targets[r.index]
            if t.coord is None:
                # Solar System body: no fixed J2000 coordinate. Export a
                # dusk snapshot, transformed to ICRS, with the name marked so
                # it is clear the position is a single-instant placeholder
                # (N.I.N.A. should re-slew from its own ephemeris).
                coord = _solar_dusk_coord(plan, t.body)
                name = f"{t.name} ({plan.window.day.isoformat()} dusk)"
                w.writerow([t.name, name, _hms(coord), _dms(coord), ""])
            else:
                catalogue = min(t.idents) if t.idents else t.name
                w.writerow([catalogue, t.name, _hms(t.coord), _dms(t.coord), ""])
            written += 1
    return written


def write_mosaic_csv(target_name: str, panels: list[Panel], pa_deg: float, path: str | Path) -> int:
    """Write mosaic panels as a N.I.N.A.-importable mosaic-plan CSV.

    Every panel becomes one sequencer target named ``<target> rRcC`` with
    the camera rotation set to the mosaic position angle.

    Returns
    -------
    int
        Number of panels written.
    """
    path = Path(path)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Pane", "RA", "DEC", "Position Angle (East)"])
        for p in panels:
            w.writerow(
                [
                    f"{target_name} r{p.row}c{p.col}",
                    _hms(p.coord),
                    _dms(p.coord),
                    f"{pa_deg % 360.0:.1f}",
                ]
            )
    return len(panels)
