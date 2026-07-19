"""Tests for mosaic panel geometry."""

from __future__ import annotations

import pytest
from astropy.coordinates import SkyCoord

from harp.mosaic import mosaic_panels
from harp.optics import Rig


@pytest.fixture
def newton() -> Rig:
    return Rig(focal_mm=800.0, sensor_name="imx571", sensor_w_mm=23.5, sensor_h_mm=15.7)


def test_grid_dims_matches_framing(newton: Rig) -> None:
    assert newton.grid_dims(18, 12) == (1, 1)
    assert newton.grid_dims(170, 140) == (2, 3)  # IC1396 -> 'mosaic 2x3'
    assert newton.grid_dims(None, None) is None


def test_panel_count_and_order(newton: Rig) -> None:
    center = SkyCoord("21h39m00s", "+57d30m00s", frame="icrs")
    panels = mosaic_panels(center, 2, 3, newton)
    assert len(panels) == 6
    assert (panels[0].row, panels[0].col) == (1, 1)
    assert (panels[-1].row, panels[-1].col) == (3, 2)


def test_panels_centered_on_target(newton: Rig) -> None:
    center = SkyCoord(ra=100.0, dec=30.0, unit="deg", frame="icrs")
    panels = mosaic_panels(center, 3, 3, newton)
    # symmetric grid: the central panel IS the target center
    mid = panels[4]
    assert mid.coord.separation(center).arcsec < 1e-6
    # and opposite corners are equidistant from it
    d1 = panels[0].coord.separation(center).arcmin
    d2 = panels[-1].coord.separation(center).arcmin
    assert d1 == pytest.approx(d2, abs=1e-6)


def test_panel_step_includes_overlap(newton: Rig) -> None:
    center = SkyCoord(ra=50.0, dec=0.0, unit="deg", frame="icrs")
    panels = mosaic_panels(center, 2, 1, newton, pa_deg=90.0)
    # PA 90: major axis toward East -> adjacent columns separated in RA
    step = panels[0].coord.separation(panels[1].coord).arcmin
    assert step == pytest.approx(newton.fov_long * (1 - newton.overlap), rel=1e-4)


def test_pa_zero_puts_major_axis_north(newton: Rig) -> None:
    center = SkyCoord(ra=50.0, dec=0.0, unit="deg", frame="icrs")
    panels = mosaic_panels(center, 2, 1, newton, pa_deg=0.0)
    # columns step along the major axis: at PA 0 that is North -> Dec changes
    assert panels[0].coord.ra.deg == pytest.approx(panels[1].coord.ra.deg, abs=1e-9)
    assert panels[0].coord.dec.deg != pytest.approx(panels[1].coord.dec.deg, abs=1e-3)
