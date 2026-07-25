"""Tests for the shared multi-site store (harp.sites)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harp.errors import ConfigError
from harp.sites import SiteEntry, SitesConfig, slugify


def test_slugify() -> None:
    assert slugify("Castelli Balcony!") == "castelli-balcony"
    assert slugify("  Mountain #2  ") == "mountain-2"
    assert slugify("") == "site"
    assert slugify("---") == "site"


def test_load_missing_requires_create(tmp_path: Path) -> None:
    missing = tmp_path / "sites.yaml"
    with pytest.raises(ConfigError, match="not found"):
        SitesConfig.load(missing)
    # create=True yields an empty, writable config
    store = SitesConfig.load(missing, create=True)
    assert store.names() == []
    assert store.default_name() is None


def test_upsert_writes_hrz_and_sets_first_default(tmp_path: Path) -> None:
    store = SitesConfig.load(tmp_path / "sites.yaml", create=True)
    entry = SiteEntry(name="balcony", label="Balcony", lat=41.7, lon=12.9, tz="Europe/Rome")
    saved = store.upsert(entry, hrz_content="0.0 10.0\n360.0 10.0\n")
    store.save()

    # .hrz written beside the config, referenced by filename
    assert saved.hrz == "balcony.hrz"
    assert (tmp_path / "balcony.hrz").read_text().startswith("0.0 10.0")
    # first site becomes the default automatically
    assert store.default_name() == "balcony"
    assert store.hrz_path(saved) == tmp_path / "balcony.hrz"


def test_bortle_sqm_round_trip(tmp_path: Path) -> None:
    # Sky quality persists through save/load, matching what the CLI reads from
    # a hand-written sites.yaml and what the Android app now writes.
    store = SitesConfig.load(tmp_path / "sites.yaml", create=True)
    store.upsert(
        SiteEntry(name="dark", label="Dark", lat=45.0, lon=7.0, tz="Europe/Rome", bortle=3),
        hrz_content=None,
    )
    store.upsert(
        SiteEntry(name="measured", label="Measured", lat=45.0, lon=7.0, sqm=21.3),
        hrz_content=None,
    )
    store.save()

    reloaded = SitesConfig.load(tmp_path / "sites.yaml")
    assert reloaded.get("dark").bortle == 3
    assert reloaded.get("dark").sqm is None
    assert reloaded.get("measured").sqm == 21.3


def test_no_sky_site_omits_keys(tmp_path: Path) -> None:
    # A site declaring no sky quality serialises without bortle/sqm keys, so
    # existing configs and behaviour are unchanged.
    entry = SiteEntry(name="plain", label="Plain", lat=1.0, lon=2.0)
    section = entry.to_section()
    assert "bortle" not in section
    assert "sqm" not in section


def test_bortle_from_hand_written_config(tmp_path: Path) -> None:
    # The CLI's config path reads raw YAML; a hand-added bortle survives the
    # SiteEntry round-trip the app and shared store use.
    cfg = tmp_path / "sites.yaml"
    cfg.write_text(
        "sites:\n  balcony:\n    label: Balcony\n    lat: 41.9\n    lon: 12.5\n"
        "    bortle: 6\ndefault_site: balcony\n"
    )
    store = SitesConfig.load(cfg)
    assert store.get("balcony").bortle == 6


def test_roundtrip_preserves_unrelated_keys(tmp_path: Path) -> None:
    cfg = tmp_path / "sites.yaml"
    cfg.write_text(
        "optics:\n  newton:\n    focal: 800\nmag_limit: 11.0\n"
        "sites:\n  a:\n    label: A\n    lat: 1.0\n    lon: 2.0\n"
        "default_site: a\n"
    )
    store = SitesConfig.load(cfg)
    store.upsert(SiteEntry(name="b", label="B", lat=3.0, lon=4.0))
    store.save()

    import yaml

    raw = yaml.safe_load(cfg.read_text())
    assert raw["optics"]["newton"]["focal"] == 800  # untouched
    assert raw["mag_limit"] == 11.0
    assert set(raw["sites"]) == {"a", "b"}
    assert raw["default_site"] == "a"  # not clobbered by the second upsert


def test_resolve_default_and_named(tmp_path: Path) -> None:
    store = SitesConfig.load(tmp_path / "sites.json", create=True)
    store.upsert(SiteEntry(name="a", label="A", lat=1.0, lon=2.0), make_default=True)
    store.upsert(SiteEntry(name="b", label="B", lat=3.0, lon=4.0))

    assert store.resolve(None).name == "a"  # default
    assert store.resolve("b").name == "b"  # explicit
    with pytest.raises(ConfigError, match="not found"):
        store.resolve("nope")


def test_resolve_without_default_errors(tmp_path: Path) -> None:
    store = SitesConfig.load(tmp_path / "sites.json", create=True)
    with pytest.raises(ConfigError, match="no site requested and no default"):
        store.resolve(None)


def test_remove_deletes_hrz_and_repoints_default(tmp_path: Path) -> None:
    store = SitesConfig.load(tmp_path / "sites.yaml", create=True)
    store.upsert(SiteEntry(name="a", label="A", lat=1.0, lon=2.0), hrz_content="0 0\n360 0\n")
    store.upsert(SiteEntry(name="b", label="B", lat=3.0, lon=4.0))
    store.set_default("a")
    store.save()
    assert (tmp_path / "a.hrz").exists()

    store.remove("a")
    store.save()
    assert not (tmp_path / "a.hrz").exists()  # local .hrz cleaned up
    assert store.names() == ["b"]
    assert store.default_name() == "b"  # default fell through to the survivor


def test_remove_keep_hrz(tmp_path: Path) -> None:
    store = SitesConfig.load(tmp_path / "sites.yaml", create=True)
    store.upsert(SiteEntry(name="a", label="A", lat=1.0, lon=2.0), hrz_content="0 0\n360 0\n")
    store.remove("a", delete_hrz=False)
    assert (tmp_path / "a.hrz").exists()
    assert store.names() == []


def test_set_default_unknown_errors(tmp_path: Path) -> None:
    store = SitesConfig.load(tmp_path / "sites.json", create=True)
    with pytest.raises(ConfigError, match="not found"):
        store.set_default("ghost")


def test_from_section_missing_geo_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid or missing"):
        SiteEntry.from_section("bad", {"label": "no coords"})


def test_absolute_hrz_not_deleted_on_remove(tmp_path: Path) -> None:
    """A site pointing at an absolute .hrz must not delete that shared file."""
    shared = tmp_path / "shared.hrz"
    shared.write_text("0 0\n360 0\n")
    store = SitesConfig.load(tmp_path / "sites.yaml", create=True)
    store.upsert(SiteEntry(name="a", label="A", lat=1.0, lon=2.0, hrz=str(shared)))
    store.remove("a")
    assert shared.exists()  # absolute reference left intact
