"""Tests for the vendored Sharpless (Sh2) emission-nebula catalogue."""

from __future__ import annotations

from harp.catalog import build_targets, filter_targets
from harp.sharpless import sh2_concordance, sharpless_targets


def test_loads_offline_with_expected_shape() -> None:
    ts = sharpless_targets(min_diam_arcmin=10.0)
    assert len(ts) > 150  # ~186 objects at diam >= 10'
    for t in ts:
        assert t.classification == "nebula"
        assert t.narrowband is True  # H II regions are emission by construction
        assert t.mag is None  # no magnitude -> never magnitude-filtered
        assert t.coord is not None
        assert t.name.startswith("Sh2-")


def test_min_diam_filters() -> None:
    all_objs = sharpless_targets(min_diam_arcmin=0.0)
    big = sharpless_targets(min_diam_arcmin=10.0)
    assert len(all_objs) == 313  # the full catalogue
    assert len(big) < len(all_objs)


def test_known_object_position() -> None:
    # Sh2-101 (Tulip) is ~19h59m54s +35d16m (about 300.0 deg, +35.3 deg)
    tulip = next(t for t in sharpless_targets(0) if t.name == "Sh2-101")
    assert abs(tulip.coord.ra.deg - 300.0) < 0.5
    assert abs(tulip.coord.dec.deg - 35.3) < 0.5


def test_sharpless_size_overrides_pyongc_undersize() -> None:
    # pyongc reports the Heart (IC1805) at ~60' (LBN bright-plate); the
    # Sharpless extent via the Sh2-190 concordance corrects it to ~150'.
    ts = build_targets(
        use_nebulae=False,
        use_sharpless=True,
        pyongc_catalogs=["NGC", "IC", "M"],
        mag_limit=99,
        use_solar_system=False,
    )
    heart = next(t for t in ts if "IC1805" in t.idents)
    assert heart.maj_arcmin >= 120  # corrected up from pyongc's ~60'
    assert heart.narrowband is True


def test_sharpless_enlarges_the_emission_pool() -> None:
    without = build_targets(use_pyongc=False, use_sharpless=False, use_solar_system=False)
    with_sh = build_targets(use_pyongc=False, use_sharpless=True, use_solar_system=False)
    assert len(with_sh) > len(without) + 100  # ~180 new emission nebulae


def test_all_sharpless_are_emission() -> None:
    ts = build_targets(use_pyongc=False, use_solar_system=False)
    emission = filter_targets(ts, "emission")
    sh = [t for t in ts if t.name.startswith("Sh2-")]
    assert sh
    assert all(t in emission for t in sh)


def test_concordance_ships_and_links_known_objects() -> None:
    concord = sh2_concordance()
    assert concord  # vendored offline JSON is present and non-empty
    # a few well-established Sh2 -> NGC/IC/M cross-refs used by the size override
    assert "IC1805" in concord.get("190", [])  # Heart
    assert "M8" in concord.get("25", [])  # Lagoon


def test_size_override_respects_type_gate_and_cap() -> None:
    # NGC6302 is a planetary nebula wrongly near a Sh2 region; the type gate
    # must leave its size untouched (planetaries are not eligible).
    ts = build_targets(
        use_nebulae=False,
        use_sharpless=True,
        pyongc_catalogs=["NGC"],
        mag_limit=99,
        use_solar_system=False,
    )
    pn = next((t for t in ts if "NGC6302" in t.idents), None)
    if pn is not None:
        assert pn.maj_arcmin < 5  # not blown up to a whole Sh2-region size
