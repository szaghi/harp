"""Layered configuration: CLI options > config file (sites/optics) > defaults.

The config file (YAML or JSON) collects observing sites and optical setups,
selectable by name. Search order when ``--config`` is not given: ``sites.yaml``
/ ``sites.yml`` / ``sites.json`` in the current directory, then the same names
under ``~/.config/harp/``.

Relative ``.hrz`` paths in a config file are resolved against the config
file's own directory, so a config can live anywhere.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harp.errors import ConfigError

log = logging.getLogger(__name__)

__all__ = ["DEFAULTS", "Defaults", "find_config", "load_config", "pick", "resolve_section"]

_CONFIG_NAMES = ("sites.yaml", "sites.yml", "sites.json")


@dataclass(frozen=True)
class Defaults:
    """Built-in fallback values (weakest layer of the precedence chain)."""

    lat: float = 41.738026  # Castelli Romani
    lon: float = 12.889862
    elev: float = 300.0
    tz: str = "Europe/Rome"
    site_label: str = "Site"
    focal_mm: float = 800.0  # Newton 200/800 (f/4)
    sensor: str = "ToupTek ATR2600C (IMX571) 23.5x15.7"
    grid_min: int = 5  # time-grid resolution (minutes)
    mag_limit: float = 11.0  # pyongc objects only
    min_hours: float = 1.0
    min_peak_alt: float = 20.0
    min_moon_sep: float = 30.0  # degrees
    top: int = 40
    n_plot: int = 12
    csv_file: str = "night_targets.csv"
    plot_file: str = "altitude_charts.png"


DEFAULTS = Defaults()


def find_config(explicit: str | None) -> Path | None:
    """Locate the config file: explicit path, cwd, then ``~/.config/harp/``.

    Raises
    ------
    ConfigError
        If an explicitly given path does not exist.
    """
    if explicit is not None:
        path = Path(explicit)
        if not path.exists():
            raise ConfigError(f"config file not found: {path}")
        return path
    for base in (Path.cwd(), Path.home() / ".config" / "harp"):
        for name in _CONFIG_NAMES:
            cand = base / name
            if cand.exists():
                return cand
    return None


def load_config(path: Path) -> dict[str, Any]:
    """Parse a YAML or JSON config file into a dict.

    Raises
    ------
    ConfigError
        If YAML is requested without pyyaml installed, or parsing fails.
    """
    text = path.read_text()
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as e:
            raise ConfigError(
                "YAML config needs pyyaml (pip install pyyaml); alternatively use a .json file"
            ) from e
        try:
            return yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"cannot parse {path}: {e}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"cannot parse {path}: {e}") from e


def resolve_section(
    cfg: dict[str, Any], section: str, name: str | None, cfg_path: Path | None
) -> tuple[str | None, dict[str, Any]]:
    """Select a named entry from ``cfg[section]`` (sites or optics).

    Parameters
    ----------
    cfg : dict
        Parsed config.
    section : str
        ``'sites'`` or ``'optics'``.
    name : str or None
        Requested entry name; None falls back to ``cfg['default_<singular>']``.
    cfg_path : pathlib.Path or None
        Config file location, for error messages.

    Returns
    -------
    (str or None, dict)
        The resolved name (None if nothing selected) and its entry.

    Raises
    ------
    ConfigError
        If a name was requested but is not defined in the config.
    """
    singular = {"sites": "site", "optics": "optics"}[section]
    resolved = name or cfg.get(f"default_{singular}")
    if not resolved:
        return None, {}
    entry = (cfg.get(section) or {}).get(resolved)
    if entry is None:
        raise ConfigError(f"{singular} '{resolved}' not found in config {cfg_path}")
    return resolved, entry


def pick(cli: Any, key: str, src: dict[str, Any], default: Any) -> Any:
    """Layered lookup: CLI (if given) > config value > default."""
    if cli is not None:
        return cli
    value = src.get(key)
    if value is not None:
        return value
    return default
