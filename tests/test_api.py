"""Tests for the stable API surface and the CLI --json outputs."""

from __future__ import annotations

import json
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
    assert data["api_version"] == "3"
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
