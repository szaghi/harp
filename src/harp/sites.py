"""Shared multi-site store: named observatories, each with its own horizon.

A *site* is an observing location -- a label, geographic position, timezone,
and a ``.hrz`` horizon mask. Sites live in the same ``sites.yaml`` config the
CLI already reads (:mod:`harp.config`); this module adds the *write* side so
that both frontends -- the ``harp sites`` CLI group and the Android app --
create, update, remove, and select sites through one code path, never
diverging.

Layout on disk::

    <config-dir>/
        sites.yaml          # the config: sites{}, default_site, globals
        balcony.hrz         # one .hrz per site, referenced by filename
        mountain.hrz

The ``.hrz`` of each site is stored as a file *beside* the config and
referenced by a relative filename (``hrz: balcony.hrz``), matching the
historical convention and the config-relative path resolution in the CLI. A
site whose ``.hrz`` is absent plans against a flat horizon, exactly as before.

This module owns only the sites section and ``default_site``; unrelated config
keys (``optics``, global filters) are preserved verbatim on save.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from harp.errors import ConfigError

log = logging.getLogger(__name__)

__all__ = [
    "SiteEntry",
    "SitesConfig",
    "default_config_path",
    "slugify",
]

# Fields of a site entry that are optional geo/label metadata; kept in sync
# with SiteEntry so a round-trip through YAML/JSON is lossless.
_SITE_FIELDS = ("label", "lat", "lon", "elev", "tz", "hrz")


@dataclass
class SiteEntry:
    """One named observing site.

    Parameters
    ----------
    name : str
        Config key / slug that selects this site (``--site <name>``).
    label : str
        Human-readable name for report headers.
    lat, lon : float
        Latitude and longitude in degrees (longitude East positive).
    elev : float
        Elevation in metres.
    tz : str
        IANA timezone, e.g. ``Europe/Rome``.
    hrz : str or None
        Filename of the site's ``.hrz`` mask, relative to the config
        directory. ``None`` means "no horizon" (flat 0 deg at plan time).
    """

    name: str
    label: str
    lat: float
    lon: float
    elev: float = 0.0
    tz: str = "UTC"
    hrz: str | None = None

    def to_section(self) -> dict[str, Any]:
        """Serialise to the config's per-site mapping (without the name key)."""
        out: dict[str, Any] = {f: getattr(self, f) for f in _SITE_FIELDS}
        if out["hrz"] is None:
            del out["hrz"]
        return out

    @classmethod
    def from_section(cls, name: str, section: dict[str, Any]) -> SiteEntry:
        """Build from a config per-site mapping.

        Raises
        ------
        ConfigError
            If a required geographic field is missing or non-numeric.
        """
        try:
            return cls(
                name=name,
                label=str(section.get("label", name)),
                lat=float(section["lat"]),
                lon=float(section["lon"]),
                elev=float(section.get("elev", 0.0)),
                tz=str(section.get("tz", "UTC")),
                hrz=(str(section["hrz"]) if section.get("hrz") else None),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ConfigError(f"site '{name}' has invalid or missing fields: {e}") from e


def slugify(label: str) -> str:
    """Turn a free-text label into a filesystem/config-safe site name.

    Lowercases, keeps ``[a-z0-9_-]``, collapses runs of other characters to a
    single ``-``. ``"Castelli Balcony!"`` -> ``"castelli-balcony"``.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return slug or "site"


def default_config_path() -> Path:
    """The user-level config path (``~/.config/harp/sites.yaml``).

    Used when no explicit config is given for a *write* operation; the CLI's
    read path (:func:`harp.config.find_config`) also searches here.
    """
    return Path.home() / ".config" / "harp" / "sites.yaml"


class SitesConfig:
    """A mutable view over the sites of one config file.

    Loads (or starts empty), lets callers add/update/remove sites and set the
    default, and writes the whole config back, preserving unrelated keys. The
    ``.hrz`` of each site is read from / written to the config directory.
    """

    def __init__(self, path: str | Path, raw: dict[str, Any]) -> None:
        self.path = Path(path)
        self._raw = raw

    # -- construction ----------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None = None, *, create: bool = False) -> SitesConfig:
        """Load a sites config, or start an empty one.

        Parameters
        ----------
        path : str or pathlib.Path or None
            Config file. ``None`` uses :func:`default_config_path`.
        create : bool
            If True, a missing file yields an empty config rather than an
            error (the write path); if False, a missing file is an error.

        Raises
        ------
        ConfigError
            If ``create`` is False and the file does not exist, or the file
            cannot be parsed.
        """
        p = Path(path) if path is not None else default_config_path()
        if not p.exists():
            if create:
                return cls(p, {})
            raise ConfigError(f"config file not found: {p}")
        raw = _read_config(p)
        return cls(p, raw)

    # -- queries ---------------------------------------------------------

    @property
    def config_dir(self) -> Path:
        """Directory the config lives in; ``.hrz`` paths resolve against it."""
        return self.path.parent

    def names(self) -> list[str]:
        """Site names, sorted."""
        return sorted((self._raw.get("sites") or {}).keys())

    def default_name(self) -> str | None:
        """The selected default site name, if any."""
        return self._raw.get("default_site")

    def get(self, name: str) -> SiteEntry:
        """Return the named site.

        Raises
        ------
        ConfigError
            If the site is not defined.
        """
        section = (self._raw.get("sites") or {}).get(name)
        if section is None:
            raise ConfigError(f"site '{name}' not found in config {self.path}")
        return SiteEntry.from_section(name, section)

    def resolve(self, name: str | None) -> SiteEntry:
        """Return the requested site, or the default when ``name`` is None.

        Raises
        ------
        ConfigError
            If no name is given and no default is set, or the resolved site
            is not defined.
        """
        chosen = name or self.default_name()
        if not chosen:
            raise ConfigError(
                f"no site requested and no default_site set in {self.path}; "
                "add one with 'harp sites add' or pass --site"
            )
        return self.get(chosen)

    def hrz_path(self, site: SiteEntry) -> Path | None:
        """Absolute path to the site's ``.hrz``, or None if it has no horizon."""
        if not site.hrz:
            return None
        p = Path(site.hrz)
        return p if p.is_absolute() else self.config_dir / p

    # -- mutations -------------------------------------------------------

    def upsert(
        self,
        site: SiteEntry,
        *,
        hrz_content: str | None = None,
        make_default: bool = False,
    ) -> SiteEntry:
        """Add or replace a site, optionally writing its ``.hrz`` content.

        Parameters
        ----------
        site : SiteEntry
            The site to store. When ``hrz_content`` is given, ``site.hrz`` is
            set to ``<name>.hrz`` and that file is written in the config dir.
        hrz_content : str or None
            Raw ``.hrz`` file text to persist for this site. None leaves any
            existing ``site.hrz`` reference untouched.
        make_default : bool
            Also set this site as ``default_site``.

        Returns
        -------
        SiteEntry
            The stored entry (with ``hrz`` filename filled in if written).
        """
        if hrz_content is not None:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{site.name}.hrz"
            (self.config_dir / fname).write_text(hrz_content, encoding="utf-8")
            site = SiteEntry(**{**asdict(site), "hrz": fname})

        sites = self._raw.setdefault("sites", {})
        sites[site.name] = site.to_section()
        if make_default or self.default_name() is None:
            self._raw["default_site"] = site.name
        return site

    def remove(self, name: str, *, delete_hrz: bool = True) -> None:
        """Remove a site and, by default, its ``.hrz`` file.

        Clears ``default_site`` when it pointed at the removed site (falling
        back to another site if one remains).

        Raises
        ------
        ConfigError
            If the site is not defined.
        """
        sites = self._raw.get("sites") or {}
        if name not in sites:
            raise ConfigError(f"site '{name}' not found in config {self.path}")
        if delete_hrz:
            entry = SiteEntry.from_section(name, sites[name])
            hp = self.hrz_path(entry)
            # only delete a config-local .hrz, never an absolute/shared one
            if hp and hp.exists() and not Path(entry.hrz or "").is_absolute():
                hp.unlink()
        del sites[name]
        if self._raw.get("default_site") == name:
            self._raw["default_site"] = next(iter(sorted(sites)), None)

    def set_default(self, name: str) -> None:
        """Select ``name`` as the default site.

        Raises
        ------
        ConfigError
            If the site is not defined.
        """
        if name not in (self._raw.get("sites") or {}):
            raise ConfigError(f"site '{name}' not found in config {self.path}")
        self._raw["default_site"] = name

    def save(self) -> None:
        """Write the config back to disk (YAML or JSON per its suffix)."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        _write_config(self.path, self._raw)


# ---------------------------------------------------------------------------
# File I/O: YAML preferred, JSON fallback, chosen by suffix
# ---------------------------------------------------------------------------


def _read_config(path: Path) -> dict[str, Any]:
    text = path.read_text()
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as e:
            raise ConfigError(
                "YAML config needs pyyaml (pip install pyyaml); or use a .json config"
            ) from e
        try:
            return yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"cannot parse {path}: {e}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"cannot parse {path}: {e}") from e


def _write_config(path: Path, data: dict[str, Any]) -> None:
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as e:
            raise ConfigError(
                "writing a YAML config needs pyyaml (pip install pyyaml); or use a .json config"
            ) from e
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
        path.write_text(text, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
