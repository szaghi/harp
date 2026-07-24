"""Tests for the stable API surface and the CLI --json outputs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from harp.cli import app

EXAMPLES = Path(__file__).parents[1] / "examples"
PLAN_ARGS = ["plan", "2026-08-15", "--config", str(EXAMPLES / "sites.yaml"), "--no-pyongc"]


def test_plan_json_shape(runner: CliRunner) -> None:
    # --top 300: with the Sharpless catalogue the plan is large and Solar
    # System bodies rank below the default cutoff; assert on the full set.
    result = runner.invoke(app, [*PLAN_ARGS, "--no-plot", "--top", "300", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["api_version"] == "4"
    assert data["night"]["date"] == "2026-08-15"
    assert data["site"]["label"] == "Castelli Balcony"
    assert data["rig"]["fov_w_arcmin"] > data["rig"]["fov_h_arcmin"]
    rows = data["rows"]
    assert rows
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    first = rows[0]
    assert {"name", "score", "window", "ra_deg", "dec_deg", "link"} <= set(first)
    # every row carries its nature; the default plan includes Solar System bodies
    assert all("classification" in r for r in rows)
    classes = {r["classification"] for r in rows}
    assert classes & {"planet", "moon"}, "Solar System bodies should be present by default"
    # curves are included and consistent with the grid
    curves = data["curves"]
    n_times = len(curves["times"])
    assert len(curves["moon_alt"]) == n_times
    tgt = curves["targets"][first["name"]]
    assert len(tgt["alt"]) == n_times
    assert len(tgt["horizon"]) == n_times
    assert any(tgt["visible"])


def test_plan_json_writes_no_default_csv(runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, [*PLAN_ARGS, "--no-plot", "--json"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "night_targets.csv").exists()


def test_info_json(runner: CliRunner) -> None:
    result = runner.invoke(
        app, ["info", "IC1396", "--config", str(EXAMPLES / "sites.yaml"), "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["name"] == "IC1396 Elephant Trunk"
    assert data["narrowband"] is True
    assert data["frame"] == "mosaic 2x3"
    assert set(data["links"]) == {"simbad", "wikipedia", "astrobin", "aladin"}


def test_mosaic_json(runner: CliRunner) -> None:
    result = runner.invoke(
        app, ["mosaic", "IC1396", "--config", str(EXAMPLES / "sites.yaml"), "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data["panels"]) == 6
    assert data["panels"][0]["row"] == 1
    assert data["overlap"] == 0.15


def test_polar_align_to_dict_is_json_safe() -> None:
    """The alignment payload must survive the Chaquopy JSON boundary."""
    from harp.api import polar_align_to_dict

    d = polar_align_to_dict(datetime(2026, 7, 23, 22, tzinfo=UTC), 41.9, 12.5)
    assert json.loads(json.dumps(d)) == d
    assert d["api_version"] == "4"
    assert d["pole_az"] == 0.0
    assert d["pole_star"] == "Polaris"
    assert d["northern"] is True
    # both altitudes are reported; refraction lifts the apparent pole
    assert d["pole_alt_true"] == 41.9
    assert d["pole_alt_refracted"] > d["pole_alt_true"]
    # apparent separation, not the 44.2' J2000 catalogue value
    assert 37.0 < d["polaris_sep_arcmin"] < 38.0


def test_polar_align_southern_site() -> None:
    """Southern sites target the south pole and the southern pole star."""
    from harp.api import polar_align_to_dict

    d = polar_align_to_dict(datetime(2026, 7, 23, 22, tzinfo=UTC), -33.9, 151.2)
    assert d["pole_az"] == 180.0
    assert d["northern"] is False
    assert d["pole_star"] == "sigma Octantis"
    assert d["pole_alt_refracted"] > 33.9


def test_polar_align_atmosphere_affects_altitude() -> None:
    """Pressure/temperature reach the refraction term; 0 pressure disables it.

    This pins the contract the Android polar_bridge depends on -- a regression
    here is what the bridge's falsy-0 coalescing bug would have silently
    reintroduced (0 pressure snapping back to the default).
    """
    from harp.api import polar_align_to_dict

    when = datetime(2026, 7, 23, 22, tzinfo=UTC)
    default = polar_align_to_dict(when, 41.9, 12.5)["pole_alt_refracted"]
    vacuum = polar_align_to_dict(when, 41.9, 12.5, pressure_hpa=0.0)["pole_alt_refracted"]
    dense = polar_align_to_dict(when, 41.9, 12.5, pressure_hpa=1030.0, temp_c=-15.0)[
        "pole_alt_refracted"
    ]
    assert vacuum == 41.9  # no atmosphere -> bare latitude
    assert dense > default > vacuum  # denser, colder air refracts more


def test_polar_align_flags_unverified_mount() -> None:
    """An unconfirmed vendor reticle must be reported as unverified."""
    from harp.api import polar_align_to_dict

    when = datetime(2026, 7, 23, 22, tzinfo=UTC)
    assert polar_align_to_dict(when, 41.9, 12.5, mount="skywatcher")["mount_verified"] is True
    assert polar_align_to_dict(when, 41.9, 12.5, mount="ioptron")["mount_verified"] is False


def test_mounts_to_dict() -> None:
    from harp.api import mounts_to_dict

    d = mounts_to_dict()
    assert json.loads(json.dumps(d)) == d
    keys = {m["key"] for m in d["mounts"]}
    assert {"generic", "skywatcher", "ioptron", "celestron"} <= keys
