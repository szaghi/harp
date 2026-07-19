"""Informative web links for targets, constructed offline.

No provider is queried at run time: URLs are built from the designations
HARP already carries, so the offline guarantee holds — the links are for
your browser, not for HARP.

Providers:

- ``simbad``   — CDS database page: type, distances, magnitudes, cross-ids,
  bibliography, sky preview. Resolves essentially every designation
  (verified incl. ``Sh2-N``); the default.
- ``wikipedia`` — best prose and images WHEN the article exists; faint
  objects 404. Chosen eyes-open by the user.
- ``astrobin`` — community image search: what the object looks like from
  amateur rigs.
- ``aladin``   — Aladin Lite survey viewer centered on the coordinates;
  works for any target, designation or not.

Targets without any catalog designation (custom YAML entries) always get
an Aladin coordinate link, whatever provider was requested — a guaranteed
working link beats a guessed 404.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from harp.catalog import Target

__all__ = ["LINK_PROVIDERS", "target_link"]

LINK_PROVIDERS = ("simbad", "wikipedia", "astrobin", "aladin")

# preferred designation order for URL construction: Messier pages/idents
# are the best known, then NGC, IC, Sharpless, Simeis
_PREFIX_ORDER = ("M", "NGC", "IC", "SH2-", "SIMEIS")


def _primary_ident(target: Target) -> str | None:
    """Pick the most recognizable designation of a target."""
    if not target.idents:
        return None

    def rank(ident: str) -> tuple[int, str]:
        for k, prefix in enumerate(_PREFIX_ORDER):
            if ident.startswith(prefix) and (prefix != "M" or ident[1:2].isdigit()):
                return (k, ident)
        return (len(_PREFIX_ORDER), ident)

    return min(target.idents, key=rank)


def _wikipedia_title(ident: str) -> str:
    """Map a normalized designation to the Wikipedia article-title style."""
    m = re.fullmatch(r"M(\d+)", ident)
    if m:
        return f"Messier_{m.group(1)}"  # bare 'M42' is a disambiguation page
    m = re.fullmatch(r"(NGC|IC)(\d+)", ident)
    if m:
        return f"{m.group(1)}_{m.group(2)}"
    m = re.fullmatch(r"SH2-(\d+)", ident)
    if m:
        return f"Sh2-{m.group(1)}"
    m = re.fullmatch(r"SIMEIS(\d+)", ident)
    if m:
        return f"Simeis_{m.group(1)}"
    return ident


def _aladin_link(target: Target) -> str:
    fov_deg = max((target.maj_arcmin or 30.0) / 60.0 * 3.0, 0.5)
    coords = f"{target.coord.ra.deg:.4f} {target.coord.dec.deg:+.4f}"
    return f"https://aladin.cds.unistra.fr/AladinLite/?target={quote(coords)}&fov={fov_deg:.2f}"


def target_link(target: Target, provider: str = "simbad") -> str:
    """Build an informative web link for a target.

    Parameters
    ----------
    target : Target
        The object to link.
    provider : str
        One of :data:`LINK_PROVIDERS`.

    Raises
    ------
    ValueError
        For an unknown provider name.
    """
    if provider not in LINK_PROVIDERS:
        raise ValueError(f"unknown link provider {provider!r}: choose from {LINK_PROVIDERS}")
    ident = _primary_ident(target)
    if ident is None or provider == "aladin":
        return _aladin_link(target)
    if provider == "simbad":
        return f"https://simbad.cds.unistra.fr/simbad/sim-id?Ident={quote(ident)}"
    if provider == "wikipedia":
        return f"https://en.wikipedia.org/wiki/{quote(_wikipedia_title(ident))}"
    return f"https://www.astrobin.com/search/?q={quote(ident)}"
