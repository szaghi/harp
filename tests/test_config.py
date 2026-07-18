"""Tests for layered configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from harp.config import find_config, load_config, pick, resolve_section
from harp.errors import ConfigError


def test_pick_precedence() -> None:
    src = {"lat": 40.0, "empty": None}
    assert pick(1.0, "lat", src, 99.0) == 1.0  # CLI wins
    assert pick(None, "lat", src, 99.0) == 40.0  # config next
    assert pick(None, "empty", src, 99.0) == 99.0  # explicit null -> default
    assert pick(None, "missing", src, 99.0) == 99.0  # absent -> default


def test_find_config_explicit_missing() -> None:
    with pytest.raises(ConfigError, match="not found"):
        find_config("no_such_config.yaml")


def test_find_config_none_when_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert find_config(None) is None


def test_load_config_yaml_and_json(tmp_path: Path) -> None:
    y = tmp_path / "sites.yaml"
    y.write_text("sites:\n  balcony:\n    lat: 41.7\n")
    j = tmp_path / "sites.json"
    j.write_text('{"sites": {"balcony": {"lat": 41.7}}}')
    assert load_config(y) == load_config(j)


def test_load_config_bad_json(tmp_path: Path) -> None:
    j = tmp_path / "sites.json"
    j.write_text("{not json")
    with pytest.raises(ConfigError, match="cannot parse"):
        load_config(j)


def test_resolve_default_optics() -> None:
    """Regression: 'default_optics' must be honored (not 'default_optic')."""
    cfg = {"default_optics": "newton800", "optics": {"newton800": {"focal": 800}}}
    name, entry = resolve_section(cfg, "optics", None, None)
    assert name == "newton800"
    assert entry["focal"] == 800


def test_resolve_section_named_default_and_missing(tmp_path: Path) -> None:
    cfg = {
        "default_site": "balcony",
        "sites": {"balcony": {"lat": 41.7}, "mountain": {"lat": 46.5}},
    }
    name, entry = resolve_section(cfg, "sites", None, None)
    assert name == "balcony"
    assert entry["lat"] == 41.7
    name, entry = resolve_section(cfg, "sites", "mountain", None)
    assert name == "mountain"
    with pytest.raises(ConfigError, match="'nowhere' not found"):
        resolve_section(cfg, "sites", "nowhere", None)
    # no name, no default -> nothing selected
    assert resolve_section({}, "optics", None, None) == (None, {})
