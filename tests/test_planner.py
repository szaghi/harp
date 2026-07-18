"""Tests for planning helpers (pure logic, no ephemerides)."""

from __future__ import annotations

import numpy as np

from harp.planner import longest_window, moon_impact


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
