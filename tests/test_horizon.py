"""Tests for the horizon mask and the .hrz builder."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from harp.errors import HorizonError
from harp.horizon import Horizon, build_profile, validate_profile, write_hrz

BALCONY_POINTS = [(107.0, 7.0), (108.0, 90.0), (335.0, 90.0), (336.0, 6.0)]
DECLINATION = 4.10


def test_from_hrz_parses_and_sorts(tmp_path: Path) -> None:
    f = tmp_path / "h.hrz"
    f.write_text("# comment\n180.0 30.0\n0.0 5.0\n90.0 10.0\n")
    h = Horizon.from_hrz(f)
    assert list(h.az) == [0.0, 90.0, 180.0]
    assert list(h.alt) == [5.0, 10.0, 30.0]


def test_from_hrz_missing_file() -> None:
    with pytest.raises(HorizonError, match="not found"):
        Horizon.from_hrz("no_such_file.hrz")


def test_from_hrz_bad_line(tmp_path: Path) -> None:
    f = tmp_path / "h.hrz"
    f.write_text("0.0 5.0\nnot numbers\n")
    with pytest.raises(HorizonError, match="bad line"):
        Horizon.from_hrz(f)


def test_altitude_interpolates_with_wraparound() -> None:
    h = Horizon(az=np.array([0.0, 90.0, 180.0, 270.0]), alt=np.array([0.0, 10.0, 20.0, 30.0]))
    assert h.altitude(45.0) == pytest.approx(5.0)
    # between 270 (30 deg) and 0/360 (0 deg), periodic interpolation
    assert h.altitude(315.0) == pytest.approx(15.0)
    # azimuth wrapping: 405 == 45
    assert h.altitude(405.0) == pytest.approx(5.0)


def test_flat_horizon() -> None:
    h = Horizon.flat(5.0)
    assert np.all(h.altitude(np.array([0.0, 123.4, 359.9])) == 5.0)


def test_build_profile_matches_reference_hrz(tmp_path: Path) -> None:
    """The example points must regenerate exactly the shipped balcony.hrz."""
    profile = build_profile(BALCONY_POINTS, DECLINATION, 90.0)
    out = tmp_path / "balcony.hrz"
    write_hrz(profile, out)
    generated = [line for line in out.read_text().splitlines() if not line.startswith("#")]
    reference = Path(__file__).parents[1] / "examples" / "balcony.hrz"
    expected = [line for line in reference.read_text().splitlines() if not line.startswith("#")]
    assert generated == expected


def test_build_profile_closure_endpoints() -> None:
    profile = build_profile(BALCONY_POINTS, DECLINATION, 90.0)
    assert profile[0][0] == 0.0
    assert profile[-1][0] == 360.0
    # the 0/360 closure altitude is interpolated across the open arc
    assert profile[0][1] == pytest.approx(profile[-1][1])
    assert 6.0 < profile[0][1] < 7.0


def test_validate_profile_flags_problems() -> None:
    problems = validate_profile([(10.0, 5.0), (5.0, 95.0)])
    joined = " | ".join(problems)
    assert "ascending" in joined
    assert "altitude out of range" in joined
    assert "start at Az 0" in joined


def test_validate_profile_accepts_good_profile() -> None:
    assert validate_profile(build_profile(BALCONY_POINTS, DECLINATION, 90.0)) == []
