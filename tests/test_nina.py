"""Round-trip tests for the N.I.N.A. CSV exports.

The importer below emulates N.I.N.A.'s SimpleSequenceVM parser, including
its digits-only coordinate regex and — crucially — its declination bug
(it re-reads a bare ``right ascension`` column for the declination), so
these tests prove our files survive the REAL parser, not an idealized one.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
from astropy.coordinates import SkyCoord
from typer.testing import CliRunner

from harp.cli import app
from harp.mosaic import mosaic_panels
from harp.optics import Rig

EXAMPLES = Path(__file__).parents[1] / "examples"


def nina_dms_to_degrees(s: str) -> float:
    """Port of NINA AstroUtil.DMSToDegrees: digits-only regex, sign from '-'."""
    s = s.strip()
    sign = -1.0 if "-" in s else 1.0
    nums = [float(x) for x in re.findall(r"[0-9.]+", s)]
    d = nums[0] if nums else 0.0
    m = nums[1] if len(nums) > 1 else 0.0
    sec = nums[2] if len(nums) > 2 else 0.0
    return sign * (d + m / 60.0 + sec / 3600.0)


def nina_hms_to_degrees(s: str) -> float:
    return nina_dms_to_degrees(s) * 15.0


def nina_import(path: Path) -> list[dict]:
    """Emulate NINA's importer, INCLUDING its dec bug: for observing lists
    the declination is first looked up in a bare 'right ascension' column."""
    out = []
    with path.open() as f:
        for row in csv.DictReader(f):
            row = {k.lower().strip(): v for k, v in row.items()}
            if "pane" in row:
                out.append(
                    {
                        "name": row["pane"],
                        "ra": nina_hms_to_degrees(row["ra"]),
                        "dec": nina_dms_to_degrees(row["dec"]),
                        "pa": float(row["position angle (east)"]) % 360.0,
                    }
                )
            elif "familiar name" in row:
                ra_field = row.get("right ascension") or row["right ascension (j2000)"]
                dec_field = row.get("right ascension") or row["declination (j2000)"]  # NINA bug
                out.append(
                    {
                        "name": row["familiar name"] or row["catalogue entry"],
                        "ra": nina_hms_to_degrees(ra_field),
                        "dec": nina_dms_to_degrees(dec_field),
                    }
                )
    return out


def test_mosaic_csv_roundtrip(tmp_path: Path) -> None:
    from harp.nina import write_mosaic_csv

    rig = Rig(focal_mm=800.0, sensor_name="imx571", sensor_w_mm=23.5, sensor_h_mm=15.7)
    center = SkyCoord("21h39m00s", "+57d30m00s", frame="icrs")
    panels = mosaic_panels(center, 2, 3, rig, pa_deg=30.0)
    out = tmp_path / "mosaic.csv"
    assert write_mosaic_csv("IC1396", panels, 30.0, out) == 6

    imported = nina_import(out)
    assert len(imported) == 6
    for panel, got in zip(panels, imported, strict=True):
        back = SkyCoord(ra=got["ra"], dec=got["dec"], unit="deg", frame="icrs")
        # precision=0 writing rounds to 1s RA / 1" Dec: allow 10 arcsec
        assert back.separation(panel.coord).arcsec < 10.0
        assert got["pa"] == pytest.approx(30.0)
    assert imported[0]["name"] == "IC1396 r1c1"


def test_plan_nina_export_survives_real_parser(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "nina.csv"
    result = runner.invoke(
        app,
        [
            "plan",
            "2026-08-15",
            "--config",
            str(EXAMPLES / "sites.yaml"),
            "--no-pyongc",
            "--no-plot",
            "--top",
            "100",
            "--csv",
            str(tmp_path / "t.csv"),
            "--nina",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output

    # the bare 'right ascension' header MUST be absent: NINA's importer
    # would read it for the declination too, corrupting every target
    with out.open() as f:
        headers = [h.lower().strip() for h in next(csv.reader(f))]
    assert "right ascension" not in headers
    assert "right ascension (j2000)" in headers
    assert "declination (j2000)" in headers

    imported = {t["name"]: t for t in nina_import(out)}
    assert imported
    trunk = imported["IC1396 Elephant Trunk"]
    ref = SkyCoord("21h39m00s", "+57d30m00s", frame="icrs")
    back = SkyCoord(ra=trunk["ra"], dec=trunk["dec"], unit="deg", frame="icrs")
    assert back.separation(ref).arcsec < 10.0

    # Solar System bodies are exported with a dusk snapshot and a marked name
    # (the position is a placeholder; N.I.N.A. re-slews from its ephemeris).
    snapshots = [n for n in imported if "dusk)" in n]
    assert snapshots, "expected a Solar System dusk-snapshot row in the export"
    assert any(n.startswith(("Mars", "Saturn", "Uranus", "Neptune")) for n in snapshots)


def test_mosaic_cli_nina_option(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "panels_nina.csv"
    result = runner.invoke(
        app,
        [
            "mosaic",
            "IC1396",
            "--config",
            str(EXAMPLES / "sites.yaml"),
            "--pa",
            "345",
            "--nina",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    imported = nina_import(out)
    assert len(imported) == 6
    assert all(t["pa"] == pytest.approx(345.0) for t in imported)
