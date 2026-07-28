"""Tests for the Android Shoot-tab bridge.

``shoot_bridge`` lives under ``android/`` rather than in the package, because it
is frontend glue rather than core physics. It is still worth testing here: it is
the contract the Kotlin UI codes against, and a silent change to its JSON shape
would break the app with no failing test anywhere in the repo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

BRIDGE_DIR = Path(__file__).resolve().parents[1] / "android/app/src/main/python"
sys.path.insert(0, str(BRIDGE_DIR))

shoot_bridge = pytest.importorskip("shoot_bridge")


#: A Pixel-class phone rig: fast wide lens, small pixels, 8.3 s ceiling.
PIXEL_RIG: dict[str, Any] = {
    "focal_mm": 6.9,
    "f_number": 1.8,
    "pixel_pitch_um": 1.2,
    "iso_min": 50,
    "iso_max": 3200,
    "max_analog_iso": 800,
    "max_exposure_s": 8.3,
}


def advise(**overrides: Any) -> dict[str, Any]:
    """Call the bridge with the Pixel rig plus any overrides."""
    return json.loads(shoot_bridge.advise_json(json.dumps({**PIXEL_RIG, **overrides})))


def test_recommends_iso_when_sky_is_known() -> None:
    """A site with SQM gets a full recommendation."""
    out = advise(sqm=20.4, tracked=True, integration_hours=1.0)
    assert out["iso"] is not None
    assert out["exposure_s"] > 0
    assert out["frames"] > 0
    assert out["reasons"]


def test_iso_is_none_when_the_site_declares_no_sky() -> None:
    """The neutrality rule reaches the frontend.

    Without a Bortle class or SQM there is no sky brightness to solve against,
    and :mod:`harp.sky` declines to guess. The exposure advice still stands, so
    the app can render a partial card -- but a fabricated ISO would be worse
    than an absent one, and this is the assertion that keeps it absent.
    """
    out = advise()
    assert out["iso"] is None
    assert out["exposure_s"] > 0
    assert any("Bortle" in r or "SQM" in r for r in out["reasons"])


def test_iso_never_exceeds_the_analog_ceiling() -> None:
    """Digital gain adds noise without signal, so it is never recommended."""
    out = advise(sqm=18.0)
    assert out["iso"] is not None
    assert out["iso"] <= PIXEL_RIG["max_analog_iso"]


def test_wide_phone_lens_is_not_trailing_limited() -> None:
    """At 6.9 mm the NPF limit is ~14 s, so the 8.3 s hardware ceiling binds.

    Worth pinning: it is tempting to assume "untracked" always shortens the
    sub, and for a phone's wide lens it does not. Diurnal motion crosses few
    pixels at that focal length, so removing the tracker changes nothing and
    the advisor must say the hardware limit still governs.
    """
    tracked = advise(sqm=21.0, tracked=True)
    untracked = advise(sqm=21.0, tracked=False, declination_deg=0.0)
    assert untracked["exposure_s"] == tracked["exposure_s"]
    assert any("NPF" in r for r in untracked["reasons"])


def test_long_focal_length_is_trailing_limited_when_untracked() -> None:
    """On a 400 mm lens the NPF rule bites hard and shortens the sub."""
    scope = {
        **PIXEL_RIG,
        "focal_mm": 400.0,
        "f_number": 5.6,
        "pixel_pitch_um": 3.76,
    }
    tracked = json.loads(
        shoot_bridge.advise_json(json.dumps({**scope, "sqm": 21.0, "tracked": True})),
    )
    untracked = json.loads(
        shoot_bridge.advise_json(
            json.dumps({**scope, "sqm": 21.0, "tracked": False, "declination_deg": 0.0}),
        ),
    )
    assert untracked["exposure_s"] < tracked["exposure_s"]
    assert any("trail" in r for r in untracked["reasons"])


def test_malformed_request_returns_an_error_rather_than_raising() -> None:
    """A Python exception across the JNI boundary is useless to the user.

    Chaquopy surfaces it as a bare ``PyException`` carrying no message, so the
    bridge converts failures into a named ``error`` key instead.
    """
    out = json.loads(shoot_bridge.advise_json('{"focal_mm": 1.0}'))
    assert "error" in out
    assert "f_number" in out["error"]


def test_json_result_is_serialisable_and_flat() -> None:
    """Every value must survive the JSON round trip the app relies on."""
    out = advise(sqm=20.4)
    assert json.loads(json.dumps(out)) == out
    for key in ("exposure_s", "iso", "frames", "storage_bytes", "reasons"):
        assert key in out
