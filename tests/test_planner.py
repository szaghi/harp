"""Tests for planning helpers (pure logic, no ephemerides)."""

from __future__ import annotations

import numpy as np

from harp.planner import desirability, longest_window, moon_impact

FOV = 100.0  # arcmin, long side


def test_desirability_bounds() -> None:
    assert 0.0 < desirability(5, 5, 90, "none", 50, FOV) <= 100.0
    assert desirability(0.1, 0.0, 5, "high", 1, FOV) < 10.0


def test_desirability_monotonic_in_window() -> None:
    lo = desirability(2, 1, 60, "none", 50, FOV)
    hi = desirability(4, 3, 60, "none", 50, FOV)
    assert hi > lo


def test_desirability_monotonic_in_altitude() -> None:
    assert desirability(4, 3, 70, "none", 50, FOV) > desirability(4, 3, 25, "none", 50, FOV)


def test_desirability_moon_ordering() -> None:
    scores = [desirability(4, 3, 60, m, 50, FOV) for m in ("none", "low", "med", "high")]
    assert scores == sorted(scores, reverse=True)


def test_desirability_fov_match() -> None:
    fits = desirability(4, 3, 60, "none", 50, FOV)  # half the FOV: ideal
    speck = desirability(4, 3, 60, "none", 2, FOV)  # tiny speck
    big_mosaic = desirability(4, 3, 60, "none", 400, FOV)  # 4-panel-wide monster
    assert fits > speck
    assert fits > big_mosaic


def test_desirability_unknown_size_is_neutral() -> None:
    unk = desirability(4, 3, 60, "none", None, FOV)
    fits = desirability(4, 3, 60, "none", 50, FOV)
    speck = desirability(4, 3, 60, "none", 2, FOV)
    assert speck < unk < fits


def test_longest_window_basic() -> None:
    n, s, e = longest_window(np.array([0, 1, 1, 1, 0, 1, 1, 0], dtype=bool))
    assert (n, s, e) == (3, 1, 3)


def test_longest_window_empty_and_full() -> None:
    assert longest_window(np.zeros(4, dtype=bool)) == (0, -1, -1)
    assert longest_window(np.ones(4, dtype=bool)) == (4, 0, 3)


def test_longest_window_ties_keep_first() -> None:
    n, s, e = longest_window(np.array([1, 1, 0, 1, 1], dtype=bool))
    assert (n, s, e) == (2, 0, 1)


def test_moon_impact_moon_down() -> None:
    assert moon_impact(False, 10.0, 0.0, 0.99) == "none"


def test_moon_impact_narrowband() -> None:
    assert moon_impact(True, 25.0, 1.0, 0.99) == "ok(NB)"
    assert moon_impact(True, 15.0, 1.0, 0.99) == "close"


def test_moon_impact_broadband() -> None:
    assert moon_impact(False, 70.0, 1.0, 0.20) == "low"
    assert moon_impact(False, 30.0, 1.0, 0.20) == "high"  # too close
    assert moon_impact(False, 70.0, 1.0, 0.80) == "high"  # too bright
    assert moon_impact(False, 50.0, 1.0, 0.50) == "med"
