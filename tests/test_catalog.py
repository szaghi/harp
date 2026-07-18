"""Tests for the target catalog (offline parts only)."""

from __future__ import annotations

from astropy.coordinates import SkyCoord

from harp.catalog import Target, curated_nebulae, dedup, suggest_detail


def test_curated_nebulae_well_formed() -> None:
    nebulae = curated_nebulae()
    assert len(nebulae) == 31
    for t in nebulae:
        assert t.kind == "Nebula"
        assert t.narrowband
        assert t.maj_arcmin > 0
        assert t.mag is None


def test_suggest_detail_known_and_fallback() -> None:
    assert "Cygnus Wall" in suggest_detail("NGC7000 North America")
    assert "vdB142" in suggest_detail("IC1396 Elephant Trunk")
    assert "brightest portion" in suggest_detail("Unknown Object")


def _target(name: str, ra: str, dec: str) -> Target:
    return Target(
        name=name,
        kind="Nebula",
        const="Cyg",
        mag=None,
        maj_arcmin=10,
        min_arcmin=10,
        narrowband=True,
        coord=SkyCoord(ra, dec, frame="icrs"),
    )


def test_dedup_drops_close_duplicates_first_wins() -> None:
    a = _target("first", "20h59m17s", "+44d31m00s")
    b = _target("duplicate", "20h59m20s", "+44d32m00s")  # ~1' away
    c = _target("far", "10h00m00s", "+10d00m00s")
    kept = dedup([a, b, c])
    assert [t.name for t in kept] == ["first", "far"]
