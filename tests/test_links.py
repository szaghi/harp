"""Tests for the offline link builders."""

from __future__ import annotations

import pytest
from astropy.coordinates import SkyCoord

from harp.catalog import Target
from harp.links import target_link


def _custom(name: str = "My Field", maj: float | None = 60) -> Target:
    return Target(
        name=name,
        kind="Custom",
        const="",
        mag=None,
        maj_arcmin=maj,
        min_arcmin=None,
        narrowband=False,
        coord=SkyCoord(ra=100.0, dec=-5.0, unit="deg", frame="icrs"),
    )


def _with_ident(ident: str) -> Target:
    """A minimal fixed target carrying one normalized designation."""
    return Target(
        name=ident,
        kind="Nebula",
        const="",
        mag=None,
        maj_arcmin=30,
        min_arcmin=None,
        narrowband=True,
        coord=SkyCoord(ra=100.0, dec=-5.0, unit="deg", frame="icrs"),
        idents=frozenset({ident}),
    )


def test_simbad_link_uses_designation() -> None:
    m42 = _with_ident("M42")
    assert target_link(m42, "simbad") == "https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M42"


def test_wikipedia_messier_maps_to_full_title() -> None:
    # bare 'M42' on Wikipedia is a disambiguation page
    assert (
        target_link(_with_ident("M42"), "wikipedia") == "https://en.wikipedia.org/wiki/Messier_42"
    )


def test_wikipedia_sharpless_and_ngc_styles() -> None:
    assert (
        target_link(_with_ident("SH2-101"), "wikipedia") == "https://en.wikipedia.org/wiki/Sh2-101"
    )
    assert (
        target_link(_with_ident("NGC7000"), "wikipedia") == "https://en.wikipedia.org/wiki/NGC_7000"
    )


def test_designationless_target_falls_back_to_aladin() -> None:
    link = target_link(_custom(), "simbad")
    assert link.startswith("https://aladin.cds.unistra.fr/AladinLite/")
    assert "100.0000" in link
    assert "-5.0000" in link


def test_aladin_fov_scales_with_size() -> None:
    big = target_link(_custom(maj=120), "aladin")
    small = target_link(_custom(maj=10), "aladin")
    assert "fov=6.00" in big
    assert "fov=0.50" in small  # floor at 0.5 deg


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="unknown link provider"):
        target_link(_custom(), "myspace")


def test_primary_ident_prefers_messier() -> None:
    t = Target(
        name="x",
        kind="Galaxy",
        const="And",
        mag=3.4,
        maj_arcmin=178,
        min_arcmin=70,
        narrowband=False,
        coord=SkyCoord(ra=10.7, dec=41.3, unit="deg", frame="icrs"),
        idents=frozenset({"NGC224", "M31", "IC999"}),
    )
    assert "Ident=M31" in target_link(t, "simbad")
