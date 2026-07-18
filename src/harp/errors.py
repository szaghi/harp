"""Exception hierarchy for HARP.

Every exception raised by HARP code derives from :class:`HarpError`, so
callers can catch the whole family with a single ``except HarpError``.
"""

from __future__ import annotations


class HarpError(Exception):
    """Base class for all HARP errors."""


class ConfigError(HarpError):
    """Invalid or missing configuration (site, rig, horizon profile)."""


class CatalogError(HarpError):
    """Target catalog cannot be loaded or queried."""


class HorizonError(HarpError):
    """Horizon (.hrz) file missing, unparsable, or invalid."""


class EphemerisError(HarpError):
    """Astronomical computation failed (Sun/Moon/target ephemerides)."""
