"""Tests for rig geometry and mosaic framing."""

from __future__ import annotations

import math

import pytest

from harp.errors import ConfigError
from harp.optics import Rig, parse_sensor


@pytest.fixture
def newton() -> Rig:
    """Newton 200/800 + IMX571 (APS-C), the reference rig."""
    return Rig(focal_mm=800.0, sensor_name="imx571", sensor_w_mm=23.5, sensor_h_mm=15.7)


def test_parse_sensor_preset() -> None:
    name, w, h = parse_sensor("Full-frame (36x24)")
    assert (w, h) == (36.0, 24.0)
    assert name == "Full-frame (36x24)"


def test_parse_sensor_custom_wxh() -> None:
    name, w, h = parse_sensor("23.5x15.7")
    assert (w, h) == (23.5, 15.7)
    assert name.startswith("custom")


def test_parse_sensor_invalid() -> None:
    with pytest.raises(ConfigError, match="not recognized"):
        parse_sensor("banana")
    with pytest.raises(ConfigError, match="WxH"):
        parse_sensor("axb")


def test_fov_formula(newton: Rig) -> None:
    expected_w = 2 * math.degrees(math.atan(23.5 / 2 / 800.0)) * 60
    assert newton.fov_w == pytest.approx(expected_w)
    assert newton.fov_w == pytest.approx(100.9, abs=0.1)  # ~101' for 23.5mm @ 800mm
    assert newton.fov_long == newton.fov_w
    assert newton.fov_short == newton.fov_h


def test_framing_single_frame(newton: Rig) -> None:
    assert newton.framing(18, 12) == "1 frame"  # Crescent nebula


def test_framing_mosaic(newton: Rig) -> None:
    assert newton.framing(170, 140) == "mosaic 2x3"  # IC1396, matches old output


def test_framing_missing_sizes(newton: Rig) -> None:
    assert newton.framing(None, None) == "n/a"
    # missing minor axis falls back to the major one
    assert newton.framing(18, None) == "1 frame"
