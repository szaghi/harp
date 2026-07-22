"""Tests for Solar System targets and the target-nature classification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harp.catalog import (
    Target,
    build_targets,
    filter_targets,
    kind_class,
)
from harp.cli import app
from harp.errors import CatalogError, EphemerisError
from harp.links import target_link
from harp.solar_system import SS_BODIES, solar_system_targets

EXAMPLES = Path(__file__).parents[1] / "examples"
PLAN_ARGS = ["plan", "2026-08-15", "--config", str(EXAMPLES / "sites.yaml"), "--no-pyongc"]


# --- classification taxonomy -------------------------------------------------


def test_kind_class_solar_bodies() -> None:
    assert kind_class("Planet") == "planet"
    assert kind_class("Moon") == "moon"
    assert kind_class("Sun") == "sun"
    assert kind_class("Satellite") == "moon"


def test_planetary_nebula_not_a_planet() -> None:
    # the deliberate 'planetary' (nebula) vs 'planet' (Mars) split
    assert kind_class("Planetary Nebula") == "planetary"
    assert kind_class("Planet") == "planet"


def test_target_derives_classification_for_dso() -> None:
    from astropy.coordinates import SkyCoord

    t = Target(
        name="M42",
        kind="Emission Nebula",
        const="Ori",
        mag=None,
        maj_arcmin=85,
        min_arcmin=60,
        narrowband=True,
        coord=SkyCoord("05h35m17s", "-05d23m00s", frame="icrs"),
    )
    assert t.classification == "nebula"


def test_fixed_target_without_coord_is_rejected() -> None:
    with pytest.raises(CatalogError):
        Target(
            name="ghost",
            kind="Nebula",
            const="",
            mag=None,
            maj_arcmin=None,
            min_arcmin=None,
            narrowband=False,
            coord=None,  # no body either -> illegal
        )


# --- Solar System target construction ---------------------------------------


def test_solar_system_default_set() -> None:
    ts = solar_system_targets()
    names = {t.name for t in ts}
    assert names == {b.label for b in SS_BODIES}
    assert {"Moon", "Mars", "Jupiter"} <= names
    # all carry a body, no fixed coord, and are explicitly classified
    for t in ts:
        assert t.body is not None
        assert t.coord is None
        assert t.classification in {"planet", "moon", "sun"}


def test_solar_system_moon_is_classified_moon() -> None:
    moon = next(t for t in solar_system_targets() if t.name == "Moon")
    assert moon.classification == "moon"
    mars = next(t for t in solar_system_targets() if t.name == "Mars")
    assert mars.classification == "planet"


def test_moons_off_by_default() -> None:
    assert len(solar_system_targets()) == len(SS_BODIES)
    assert len(solar_system_targets(include_moons=True)) > len(SS_BODIES)


# --- filtering ---------------------------------------------------------------


def test_filter_planet_and_moon() -> None:
    ts = solar_system_targets()
    planets = filter_targets(ts, "planet")
    assert planets
    assert all(t.classification == "planet" for t in planets)
    moons = filter_targets(ts, "moon")
    assert [t.name for t in moons] == ["Moon"]


def test_build_targets_includes_solar_system() -> None:
    ts = build_targets(use_nebulae=True, use_pyongc=False, use_solar_system=True)
    assert any(t.body is not None for t in ts)
    assert any(t.body is None for t in ts)  # nebulae still there


def test_build_targets_can_exclude_solar_system() -> None:
    ts = build_targets(use_nebulae=True, use_pyongc=False, use_solar_system=False)
    assert all(t.body is None for t in ts)


# --- links: SS bodies have no designation, get name-based links --------------


def test_solar_link_is_name_based() -> None:
    mars = next(t for t in solar_system_targets() if t.name == "Mars")
    assert "Mars" in target_link(mars, "wikipedia")
    assert "Mars" in target_link(mars, "simbad")
    # every provider yields a usable link, none crashes on coord=None
    for provider in ("simbad", "wikipedia", "astrobin", "aladin"):
        assert target_link(mars, provider).startswith("http")


# --- moons opt-in requires the ephemeris (no network in tests) ---------------


def test_ss_moons_ephemeris_error_is_typed(monkeypatch) -> None:
    from harp import solar_system

    def boom(_name: str) -> None:
        raise RuntimeError("no network")

    monkeypatch.setattr("astropy.coordinates.solar_system_ephemeris.set", boom, raising=False)
    with pytest.raises(EphemerisError):
        solar_system.load_moon_ephemeris()


# --- end-to-end: a plan places Solar System bodies and bypasses Moon impact --


def test_plan_places_solar_system(runner: CliRunner) -> None:
    # --top 300: the Sharpless catalogue makes the plan large, and Solar
    # System bodies rank below the default display cutoff — assert against the
    # full ranked set, not the truncated table.
    result = runner.invoke(app, [*PLAN_ARGS, "--no-plot", "--top", "300", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    rows = data["rows"]
    ss = [r for r in rows if r["classification"] in {"planet", "moon"}]
    assert ss, "expected Solar System bodies in the default plan"
    for r in ss:
        # SS bodies bypass the Moon-impact machinery and mosaic framing
        assert r["moon"] == "n/a"
        assert r["frame"] == "planetary"
        assert r["body"] is not None
        assert r["ra_deg"] is None
        assert r["dec_deg"] is None


def test_plan_no_solar_system_flag(runner: CliRunner) -> None:
    result = runner.invoke(app, [*PLAN_ARGS, "--no-plot", "--no-solar-system", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert not [r for r in data["rows"] if r["classification"] in {"planet", "moon", "sun"}]


def test_filter_planet_via_cli(runner: CliRunner) -> None:
    result = runner.invoke(app, [*PLAN_ARGS, "--no-plot", "--filter", "planet", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["rows"]
    assert all(r["classification"] == "planet" for r in data["rows"])


def test_mosaic_rejects_solar_body(runner: CliRunner) -> None:
    result = runner.invoke(app, ["mosaic", "Jupiter", "--config", str(EXAMPLES / "sites.yaml")])
    assert result.exit_code == 1
    assert "Solar System body" in result.output


def test_info_solar_body(runner: CliRunner) -> None:
    result = runner.invoke(
        app, ["info", "Saturn", "--config", str(EXAMPLES / "sites.yaml"), "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["name"] == "Saturn"
    assert data["classification"] == "planet"
    assert data["body"] == "saturn"
    assert data["ra_deg"] is None
    assert data["frame"] == "planetary"
