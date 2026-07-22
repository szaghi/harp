"""Tests for the target catalog (offline parts only)."""

from __future__ import annotations

from pathlib import Path

import pytest
from astropy.coordinates import SkyCoord

from harp.catalog import (
    Target,
    _extract_idents,
    build_targets,
    curated_nebulae,
    dedup,
    filter_targets,
    kind_class,
    pyongc_targets,
    suggest_detail,
    user_targets,
)
from harp.errors import CatalogError


def test_curated_nebulae_well_formed() -> None:
    # The curated list is now a small rescue set (objects the offline DBs
    # cannot supply to the plan); everything else comes from pyongc + Sharpless.
    nebulae = curated_nebulae()
    assert nebulae
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


def test_extract_idents() -> None:
    assert _extract_idents("M42 Orion") == {"M42"}
    assert _extract_idents("IC59/63 Ghost of Cas") == {"IC59", "IC63"}
    assert _extract_idents("Sh2-171 NGC7822") == {"SH2-171", "NGC7822"}
    assert _extract_idents("Simeis147 Spaghetti") == {"SIMEIS147"}
    # slash between words (not digits) must not create ghost designations
    assert _extract_idents("NGC2264 Cone/Xmas") == {"NGC2264"}
    # zero-padding is normalized away
    assert _extract_idents("NGC0224 Andromeda") == {"NGC224"}


def test_dedup_by_cross_identity_and_m43_survives() -> None:
    """Regression: a single pyongc object is not duplicated across its own
    cross-ids, and M43 (NGC1982) stays distinct from M42 (NGC1976) 8' away."""
    merged = dedup(pyongc_targets(["M"], 11.0))
    idents = {i for t in merged for i in t.idents}
    # M42 and M43 are distinct objects and both survive (not merged together)
    assert "M42" in idents
    assert "M43" in idents
    # each appears exactly once (no self-duplication across NGC/M cross-ids)
    m42_rows = [t for t in merged if "M42" in t.idents]
    assert len(m42_rows) == 1


def test_dedup_neighbors_beyond_radius_survive() -> None:
    a = _target("one", "05h35m00s", "+00d00m00s")
    b = _target("two", "05h35m32s", "+00d00m00s")  # ~8' away in RA
    assert len(dedup([a, b])) == 2


def test_pyongc_unknown_catalog() -> None:
    with pytest.raises(CatalogError, match="unknown catalog"):
        pyongc_targets(["SHARPLESS"], 11.0)


def test_pyongc_narrowband_derived_from_type() -> None:
    by_ident = {i: t for t in pyongc_targets(["M"], 11.0) for i in t.idents}
    assert by_ident["M1"].narrowband  # supernova remnant (Crab)
    assert by_ident["M57"].narrowband  # planetary nebula (Ring)
    assert not by_ident["M78"].narrowband  # reflection nebula
    assert not by_ident["M31"].narrowband  # galaxy
    assert not by_ident["M45"].narrowband  # open cluster (Pleiades)


def test_pyongc_excludes_non_targets() -> None:
    by_ident = {i: t for t in pyongc_targets(["M"], 11.0) for i in t.idents}
    assert "M40" not in by_ident  # double star: not an imaging target


def test_pyongc_generic_nebula_stays_broadband() -> None:
    """Generic 'Nebula' mixes emission and reflection members (Running Man,
    Merope): the warning-relaxing flag must NOT be set for them."""
    ngc = pyongc_targets(["NGC"], 11.0)
    running_man = next(t for t in ngc if "NGC1973" in t.idents)
    assert running_man.kind == "Nebula"
    assert not running_man.narrowband


def test_user_targets_load_and_defaults(tmp_path: Path) -> None:
    f = tmp_path / "my.yaml"
    f.write_text(
        "targets:\n"
        "  - name: 'Sh2-240 Spaghetti West'\n"
        "    ra: '05h32m00s'\n"
        "    dec: '+27d00m00s'\n"
        "    maj: 100\n"
        "    narrowband: true\n"
        "  - name: 'Decimal Object'\n"
        "    ra: 83.0\n"
        "    dec: -5.4\n"
    )
    ts = user_targets(f)
    assert ts[0].idents == {"SH2-240"}
    assert ts[0].narrowband
    assert ts[0].min_arcmin is None
    assert ts[1].kind == "Custom"
    assert ts[1].coord.ra.deg == pytest.approx(83.0)


def test_user_targets_errors(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="not found"):
        user_targets(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("targets:\n  - name: 'No coords'\n")
    with pytest.raises(CatalogError, match="bad entry #1"):
        user_targets(bad)
    empty = tmp_path / "empty.yaml"
    empty.write_text("something_else: 1\n")
    with pytest.raises(CatalogError, match="no 'targets' list"):
        user_targets(empty)


def test_kind_class_taxonomy() -> None:
    assert kind_class("Galaxy") == "galaxy"
    assert kind_class("Galaxy Pair") == "galaxy"
    assert kind_class("Planetary Nebula") == "planetary"
    assert kind_class("Nebula") == "nebula"
    assert kind_class("HII Ionized region") == "nebula"
    assert kind_class("Supernova remnant") == "nebula"
    assert kind_class("Star cluster + Nebula") == "nebula"  # nebulosity is the subject
    assert kind_class("Reflection Nebula") == "nebula"
    assert kind_class("Open Cluster") == "cluster"
    assert kind_class("Globular Cluster") == "cluster"
    assert kind_class("Association of stars") == "cluster"
    assert kind_class("Nova star") == "star"
    assert kind_class("Object of other/unknown type") == "other"


def test_filter_targets_semantics() -> None:
    targets = build_targets()  # curated + Messier
    galaxies = filter_targets(targets, "galaxy")
    assert galaxies
    assert all(kind_class(t.kind) == "galaxy" for t in galaxies)

    either = filter_targets(targets, "galaxy,cluster")
    assert len(either) > len(galaxies)  # OR semantics between classes

    emission_neb = filter_targets(targets, "emission,nebula")
    assert emission_neb
    assert all(t.narrowband and kind_class(t.kind) == "nebula" for t in emission_neb)

    non_em = filter_targets(targets, "non-emission")
    assert all(not t.narrowband for t in non_em)

    # both emission tokens -> no emission constraint
    assert len(filter_targets(targets, "emission,non-emission")) == len(targets)


def test_filter_targets_unknown_token() -> None:
    with pytest.raises(CatalogError, match="unknown filter"):
        filter_targets(curated_nebulae(), "quasar")


def test_build_targets_user_priority(tmp_path: Path) -> None:
    """A user-defined M42 must displace both the curated and pyongc entries."""
    f = tmp_path / "my.yaml"
    f.write_text(
        "targets:\n"
        "  - name: 'M42 my framing'\n"
        "    ra: '05h35m17s'\n"
        "    dec: '-05d23m00s'\n"
        "    maj: 60\n"
    )
    merged = build_targets(targets_file=f)
    m42 = [t for t in merged if "M42" in t.idents]
    assert len(m42) == 1
    assert m42[0].name == "M42 my framing"
