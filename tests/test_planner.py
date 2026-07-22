"""Tests for planning helpers (pure logic, no ephemerides)."""

from __future__ import annotations

import numpy as np

from harp.planner import desirability, longest_window, moon_impact, moon_score

FOV = 100.0  # arcmin, long side
# desirability now takes a moon FACTOR (float in [0.2, 1.0]) from moon_score(),
# not a verdict string; 1.0 = Moon down / benign, low = heavy penalty.
CLEAR = 1.0  # Moon down or negligible
HEAVY = 0.2  # worst-case bright close Moon


def test_desirability_bounds() -> None:
    assert 0.0 < desirability(5, 5, 90, CLEAR, 50, FOV) <= 100.0
    assert desirability(0.1, 0.0, 5, HEAVY, 1, FOV) < 10.0


def test_desirability_monotonic_in_window() -> None:
    lo = desirability(2, 1, 60, CLEAR, 50, FOV)
    hi = desirability(4, 3, 60, CLEAR, 50, FOV)
    assert hi > lo


def test_desirability_monotonic_in_altitude() -> None:
    assert desirability(4, 3, 70, CLEAR, 50, FOV) > desirability(4, 3, 25, CLEAR, 50, FOV)


def test_desirability_moon_ordering() -> None:
    # higher moon factor (less lunar impact) must score higher, all else equal
    scores = [desirability(4, 3, 60, m, 50, FOV) for m in (1.0, 0.8, 0.5, 0.2)]
    assert scores == sorted(scores, reverse=True)


def test_moon_score_graded_not_stepped() -> None:
    # Moon down -> no penalty for anyone.
    assert moon_score(narrowband=False, sep_min=90, moon_up_frac=0.0, illumination=0.9) == 1.0
    # A bright, high-up, close Moon hurts a broadband target a lot...
    close = moon_score(narrowband=False, sep_min=20, moon_up_frac=1.0, illumination=0.9)
    # ...far more than a dim, briefly-up, distant Moon.
    benign = moon_score(narrowband=False, sep_min=90, moon_up_frac=0.2, illumination=0.2)
    assert close < benign
    # Separation relieves the penalty (same Moon, farther away scores higher).
    near = moon_score(narrowband=False, sep_min=25, moon_up_frac=1.0, illumination=0.7)
    far = moon_score(narrowband=False, sep_min=85, moon_up_frac=1.0, illumination=0.7)
    assert far > near
    # Narrowband is near-immune: it beats broadband under the SAME bright Moon.
    nb = moon_score(narrowband=True, sep_min=40, moon_up_frac=1.0, illumination=0.9)
    bb = moon_score(narrowband=False, sep_min=40, moon_up_frac=1.0, illumination=0.9)
    assert nb > bb


def test_desirability_fov_match() -> None:
    fits = desirability(4, 3, 60, CLEAR, 50, FOV)  # half the FOV: ideal
    speck = desirability(4, 3, 60, CLEAR, 2, FOV)  # tiny speck
    big_mosaic = desirability(4, 3, 60, CLEAR, 400, FOV)  # 4-panel-wide monster
    assert fits > speck
    assert fits > big_mosaic


def test_desirability_unknown_size_is_neutral() -> None:
    unk = desirability(4, 3, 60, CLEAR, None, FOV)
    fits = desirability(4, 3, 60, CLEAR, 50, FOV)
    speck = desirability(4, 3, 60, CLEAR, 2, FOV)
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
