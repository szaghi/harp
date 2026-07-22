"""Deep-sky target catalog: pyongc + Sharpless, with a small curated rescue.

Targets are assembled and deduplicated from several offline sources
(:func:`build_targets`):

- **pyongc** (OpenNGC): Messier/NGC/IC. Emission nebulae frequently have no
  integrated magnitude — surface brightness, not magnitude, is what matters —
  so magnitude-less objects of an emission type are kept regardless of the
  magnitude cut (a naive cut would drop exactly the targets this planner is
  for). OpenNGC's nebula *sizes* come from the LBN bright-plate table and
  often under-report the imageable H-alpha extent.
- **Sharpless** (Sh2 H II regions, :mod:`harp.sharpless`): the emission
  nebulae OpenNGC lacks, and — via a vendored Sh2<->NGC/IC/M concordance —
  the measured extent used to correct pyongc's under-sized nebulae
  (:func:`_apply_sharpless_sizes`).
- a small hand-curated **rescue list** (``_NEBULAE``) for the handful of
  emission nebulae the databases still cannot deliver to the plan.

All sources are on disk; no network at run time.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from astropy.coordinates import SkyCoord

from harp.errors import CatalogError

log = logging.getLogger(__name__)

__all__ = [
    "FILTER_TOKENS",
    "PYONGC_CATALOGS",
    "Target",
    "build_targets",
    "filter_targets",
    "find_targets",
    "kind_class",
    "suggest_detail",
    "user_targets",
]

# Catalogs pyongc can enumerate offline.
PYONGC_CATALOGS = ("M", "NGC", "IC")

# Max factor by which a Sharpless diameter may enlarge a pyongc nebula size
# (see _apply_sharpless_sizes): guards an embedded knot from adopting a whole
# Sharpless-complex diameter.
_SH2_MAX_ENLARGE = 4.0

# OpenNGC types whose objects are emission-line sources: narrowband filters
# reject moonlit continuum for these, so the Moon-impact verdict is relaxed.
# Generic "Nebula" is deliberately absent: it mixes emission and reflection
# members (e.g. Merope), and a flag that RELAXES a warning must only be set
# when the type guarantees emission lines.
_NARROWBAND_TYPES = frozenset(
    {
        "Planetary Nebula",
        "Supernova remnant",
        "HII Ionized region",
        "Emission Nebula",
        "Star cluster + Nebula",
    }
)

# OpenNGC types that are not imaging targets for a deep-sky planner.
_EXCLUDED_TYPES = frozenset(
    {
        "Duplicated record",
        "Nonexistent object",
        "Star",
        "Double star",
    }
)


@dataclass(frozen=True)
class Target:
    """A deep-sky object candidate.

    Parameters
    ----------
    name : str
        Object designation and nickname.
    kind : str
        Object type (``'Nebula'``, pyongc type string, ...).
    const : str
        Constellation abbreviation.
    mag : float or None
        Integrated V (or B) magnitude; None for most emission nebulae.
    maj_arcmin, min_arcmin : float or None
        Apparent major/minor axis in arcminutes.
    narrowband : bool
        True for Halpha emission nebulae that image well in narrowband.
    coord : astropy.coordinates.SkyCoord or None
        Fixed ICRS coordinates for deep-sky objects; ``None`` for Solar
        System bodies, whose position is computed live from :attr:`body`.
    idents : frozenset of str
        Normalized catalog designations (M42, NGC1976, SH2-101, ...) used
        for identity-based deduplication across sources.
    classification : str
        Object nature, one of the :func:`kind_class` values (``nebula``,
        ``galaxy``, ..., ``planet``, ``moon``, ``sun``). Defaults to
        ``kind_class(kind)`` for deep-sky objects; Solar System targets set
        it explicitly.
    body : str or None
        ``get_body`` name (``'mars'``, ``'moon'``, ...) for a Solar System
        target; ``None`` for a fixed deep-sky object.
    """

    name: str
    kind: str
    const: str
    mag: float | None
    maj_arcmin: float | None
    min_arcmin: float | None
    narrowband: bool
    coord: SkyCoord | None
    idents: frozenset[str] = field(default_factory=frozenset)
    classification: str = ""
    body: str | None = None

    def __post_init__(self) -> None:
        # Deep-sky targets derive their class from the raw kind; Solar System
        # targets pass an explicit classification. A moving body carries no
        # fixed coord (position is computed live from `body`); a fixed object
        # must have one.
        if not self.classification:
            object.__setattr__(self, "classification", kind_class(self.kind))
        if self.body is None and self.coord is None:
            raise CatalogError(f"fixed target {self.name!r} has no coordinates")


def _norm_ident(raw: str) -> str:
    """Normalize a designation: upper-case, no spaces, no zero-padding."""
    s = raw.strip().upper().replace(" ", "")
    m = re.fullmatch(r"(.*?)(\d+)", s)
    if m:
        s = f"{m.group(1)}{int(m.group(2))}"
    return s


def _messier_label(messier: str | None) -> str | None:
    """pyongc's Messier id (``'M031'``) as its display handle (``'M31'``).

    Returns None when the object has no Messier designation.
    """
    return _norm_ident(messier) if messier else None


def _extract_idents(name: str) -> frozenset[str]:
    """Extract catalog designations from a free-form target name.

    Understands ``M``/``NGC``/``IC`` (with slash lists like ``IC59/63``),
    ``Sh2-N`` and ``Simeis N`` tokens; nicknames are ignored.
    """
    idents: set[str] = set()
    for m in re.finditer(r"\b(M|NGC|IC)(\d+)((?:/\d+)*)", name, flags=re.IGNORECASE):
        prefix = m.group(1).upper()
        idents.add(_norm_ident(f"{prefix}{m.group(2)}"))
        for extra in m.group(3).split("/"):
            if extra:
                idents.add(_norm_ident(f"{prefix}{extra}"))
    for m in re.finditer(r"\bSh2-(\d+)", name, flags=re.IGNORECASE):
        idents.add(f"SH2-{int(m.group(1))}")
    for m in re.finditer(r"\bSimeis\s*(\d+)", name, flags=re.IGNORECASE):
        idents.add(f"SIMEIS{int(m.group(1))}")
    return frozenset(idents)


# Curated rescue list (RA, Dec J2000, maj', min', const, Halpha?).
# Sizes in arcminutes; Halpha=True -> great in narrowband (dual-band filter).
#
# This used to be a 31-object hand-maintained catalogue. It is now reduced to
# only the emission nebulae that the offline databases genuinely cannot supply
# to the ranked plan:
#   - Simeis 147, IC1318: no NGC/IC/M designation at all (absent from pyongc);
#   - Rosette, Jellyfish, Tadpoles, Ghost of Cas: present in pyongc but dropped
#     by positional dedup against a coincident bare Sharpless region, and with
#     no Messier alias to survive the tie;
#   - IC1396 (Elephant Trunk): pyongc reports the small central cluster (14'),
#     and its Sharpless region (Sh2-131) has no concordance link to correct it,
#     so the true ~170' extent must be curated.
# Everything else now comes from pyongc (magnitude-less emission objects are no
# longer dropped) with Sharpless-measured sizes applied via the Sh2 concordance
# (see _apply_sharpless_sizes). Nicknames for those come from OpenNGC where it
# has them; a bare designation otherwise (the ranking is size/position-driven,
# not name-driven).
_NEBULAE: list[tuple[str, str, str, float, float, str, bool]] = [
    ("IC1318 Sadr/Gamma Cyg", "20h22m00s", "+40d15m00s", 150, 120, "Cyg", True),
    ("IC59/63 Ghost of Cas", "00h56m42s", "+61d04m00s", 20, 10, "Cas", True),
    ("IC1396 Elephant Trunk", "21h39m00s", "+57d30m00s", 170, 140, "Cep", True),
    ("IC410 Tadpoles", "05h22m36s", "+33d31m00s", 40, 30, "Aur", True),
    ("Simeis147 Spaghetti", "05h39m00s", "+28d00m00s", 180, 180, "Tau", True),
    ("NGC2237 Rosette", "06h32m18s", "+05d03m00s", 80, 80, "Mon", True),
    ("IC443 Jellyfish", "06h17m42s", "+22d47m00s", 50, 40, "Gem", True),
]

# For targets too big for one frame: what to shoot as a single-frame detail.
# key = substring of the target name; value = (suggested detail, approx size).
_DETAILS: dict[str, tuple[str, str]] = {
    "North America": ("the 'Cygnus Wall' / Mexico border (most detailed edge)", "~45x30'"),
    "Pelican": ("the central ionization front (the 'neck')", "~40x30'"),
    "Elephant Trunk": ("the Trunk vdB142 (western edge of IC1396)", "~25x15'"),
    "Heart": ("Melotte 15, the central core (or 'Fish Head' NGC896)", "~25x20'"),
    "Soul": ("the central cluster/embryo (CR34)", "~30x25'"),
    "Sadr": ("the region around Sadr (crop of the core)", "~90x60'->crop"),
    "California": ("the 'head' near xi Persei (dense filament)", "~50x40'"),
    "Rosette": ("NGC2244 and the central cavity", "~60x60'->crop"),
    "Simeis147": ("the brightest filament (NE sector)", "~40x30'"),
    "NGC0224": ("core + dust lanes, or the NGC206 star cloud", "~60x40'"),
    "Mel022": ("the central Pleiades (Alcyone/Merope) with IC349", "~40x30'"),
    "Jellyfish": ("the bright front of IC443 (NE arc)", "~40x30'"),
}


def suggest_detail(name: str) -> str:
    """Suggest a single-frame crop for a target that needs a mosaic."""
    for key, (txt, size) in _DETAILS.items():
        if key.lower() in name.lower():
            return f"{txt} ({size})"
    return "frame the brightest portion / the central cluster"


def curated_nebulae() -> list[Target]:
    """Return the small curated rescue list (see ``_NEBULAE``).

    Only the emission nebulae the offline databases cannot otherwise deliver
    to the plan; everything else comes from pyongc + Sharpless.
    """
    return [
        Target(
            name=nm,
            kind="Nebula",
            const=con,
            mag=None,
            maj_arcmin=maj,
            min_arcmin=minr,
            narrowband=ha,
            coord=SkyCoord(ra, dec, frame="icrs"),
            idents=_extract_idents(nm),
        )
        for nm, ra, dec, maj, minr, con, ha in _NEBULAE
    ]


def pyongc_targets(catalogs: list[str], mag_limit: float) -> list[Target]:
    """Load objects from the offline pyongc catalogue, filtered by magnitude.

    Non-target types (duplicated/nonexistent records, single/double stars)
    are excluded. The narrowband flag is derived from the object type:
    emission-line sources (planetaries, supernova remnants, HII regions)
    get a relaxed Moon-impact verdict; everything else stays broadband.

    Emission-type objects with NO magnitude are kept regardless of the cut:
    surface brightness, not magnitude, is what matters for them, and dropping
    them would discard large classics (NGC281 Pacman, NGC1499 California).

    Parameters
    ----------
    catalogs : list of str
        pyongc catalog names, e.g. ``['M']`` or ``['M', 'NGC']``.
    mag_limit : float
        Keep only objects with visual (or blue) magnitude <= this. Applies to
        non-emission types only; magnitude-less emission objects are always
        kept.

    Raises
    ------
    CatalogError
        If pyongc is not installed or a catalog name is unknown.
    """
    try:
        from pyongc import ongc
    except ImportError as e:
        raise CatalogError("pyongc is required for catalog objects (pip install pyongc)") from e

    for cat in catalogs:
        if cat not in PYONGC_CATALOGS:
            raise CatalogError(f"unknown catalog {cat!r}: choose from {', '.join(PYONGC_CATALOGS)}")

    def vis_mag(mags: tuple) -> float | None:
        return mags[1] if mags[1] is not None else mags[0]

    def coord_of(obj) -> SkyCoord:
        (h, mi, s), (dd, dm, ds) = obj.coords
        sign = "-" if obj.coords[1][0] < 0 else "+"
        return SkyCoord(
            f"{int(h)}h{int(mi)}m{s}s",
            f"{sign}{abs(int(dd))}d{int(dm)}m{ds}s",
            frame="icrs",
        )

    out: list[Target] = []
    for cat in catalogs:
        for obj in ongc.listObjects(catalog=cat):
            if obj.type in _EXCLUDED_TYPES:
                continue
            mv = vis_mag(obj.magnitudes)
            # Emission nebulae (H II regions, planetaries, SNRs...) frequently
            # have NO integrated magnitude — surface brightness, not magnitude,
            # is what matters. Keep those regardless of the cut; magnitude
            # filtering applies only to types where magnitude is meaningful.
            # This is why large classics (NGC281 Pacman, NGC1499 California)
            # need no hand-curated entry.
            if obj.type in _NARROWBAND_TYPES:
                if mv is not None and mv > mag_limit:
                    continue
            elif mv is None or mv > mag_limit:
                continue
            dims = obj.dimensions or (None, None, None)
            try:
                # identifiers = (messier, ngc, ic, common_names, other_idents)
                messier, ngc, ic, common_names, others = obj.identifiers
                idents = {obj.name}
                for ref in (messier, ngc, ic, *(others or [])):
                    if isinstance(ref, str):
                        idents.add(ref)
                    elif isinstance(ref, list | tuple):
                        idents.update(ref)
                # Build the display name: prefer the Messier number as the
                # handle when there is one (M31 is the recognizable name for
                # NGC0224), then fold in OpenNGC's maintained common name
                # (-> "M31 Andromeda Galaxy"). No hand list: both the Messier
                # id and the common name ship with pyongc and update upstream.
                # Many objects have no common name (-> None); most have no M id.
                nickname = common_names[0] if common_names else None
                designation = _messier_label(messier) or obj.name
                display_name = f"{designation} {nickname}" if nickname else designation
                out.append(
                    Target(
                        name=display_name,
                        kind=obj.type,
                        const=obj.constellation,
                        # mv is None for magnitude-less emission nebulae (now
                        # admitted): round() would raise and silently drop them.
                        mag=round(mv, 1) if mv is not None else None,
                        maj_arcmin=dims[0],
                        min_arcmin=dims[1],
                        narrowband=obj.type in _NARROWBAND_TYPES,
                        coord=coord_of(obj),
                        idents=frozenset(_norm_ident(i) for i in idents),
                    )
                )
            except Exception as e:  # malformed catalogue entry: skip, don't die
                log.debug("skipping pyongc object %s: %s", obj.name, e)
    return out


def dedup(targets: list[Target], sep_deg: float = 2.0 / 60.0) -> list[Target]:
    """Drop later targets that duplicate an earlier one; earlier source wins.

    Two targets are the same object when they share a normalized catalog
    designation (M42 == NGC1976 via OpenNGC cross-ids), or — fallback for
    designation-less entries — when they lie within ``sep_deg`` degrees.
    The fallback radius is deliberately tight (2 arcmin): distinct neighbors
    such as M43, 8 arcmin from M42, must survive.
    """
    import numpy as np

    # vectorized proximity test: pairwise astropy separation() calls are
    # ~0.1 ms each, O(n^2) of them is minutes at full-NGC/IC scale
    cos_thr = np.cos(np.radians(sep_deg))
    uniq: list[Target] = []
    seen: set[str] = set()
    kept_xyz = np.empty((0, 3))
    for t in targets:
        if t.idents & seen:
            continue
        # Solar System bodies carry no fixed coord and no designations: they
        # are unique by construction, so skip both dedup branches.
        if t.coord is None:
            uniq.append(t)
            continue
        ra, dec = t.coord.ra.rad, t.coord.dec.rad
        v = np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])
        if kept_xyz.size and (kept_xyz @ v).max() > cos_thr:
            continue
        uniq.append(t)
        seen |= t.idents
        kept_xyz = np.vstack([kept_xyz, v])
    return uniq


def user_targets(path: str | Path) -> list[Target]:
    """Load user-defined targets from a YAML/JSON file.

    Expected shape::

        targets:
          - name: "Sh2-240 Spaghetti"        # required
            ra:   "05h39m00s"                # required (or decimal degrees)
            dec:  "+28d00m00s"               # required (or decimal degrees)
            maj:  180                        # arcmin, optional
            min:  180                        # arcmin, optional
            const: Tau                       # optional
            kind: Nebula                     # optional, default 'Custom'
            mag:  null                       # optional
            narrowband: true                 # optional, default false

    Raises
    ------
    CatalogError
        If the file is missing, unparsable, or an entry lacks required keys.
    """
    from harp.config import load_config

    path = Path(path)
    if not path.exists():
        raise CatalogError(f"targets file not found: {path}")
    try:
        data = load_config(path)
    except Exception as e:
        raise CatalogError(f"cannot parse targets file {path}: {e}") from e
    entries = data.get("targets")
    if not isinstance(entries, list) or not entries:
        raise CatalogError(f"no 'targets' list in {path}")

    out: list[Target] = []
    for n, entry in enumerate(entries, 1):
        try:
            ra, dec = entry["ra"], entry["dec"]
            coord = (
                SkyCoord(ra=float(ra), dec=float(dec), unit="deg", frame="icrs")
                if isinstance(ra, int | float)
                else SkyCoord(ra, dec, frame="icrs")
            )
            out.append(
                Target(
                    name=entry["name"],
                    kind=entry.get("kind", "Custom"),
                    const=entry.get("const", ""),
                    mag=entry.get("mag"),
                    maj_arcmin=entry.get("maj"),
                    min_arcmin=entry.get("min"),
                    narrowband=bool(entry.get("narrowband", False)),
                    coord=coord,
                    idents=_extract_idents(str(entry["name"])),
                )
            )
        except (KeyError, ValueError) as e:
            raise CatalogError(f"bad entry #{n} in {path}: {e}") from e
    return out


_CLASS_TOKENS = frozenset(
    {"nebula", "galaxy", "cluster", "planetary", "star", "planet", "moon", "sun", "other"}
)
FILTER_TOKENS = _CLASS_TOKENS | {"emission", "non-emission"}


def kind_class(kind: str) -> str:
    """Collapse a raw catalog kind into the filter taxonomy.

    One of ``nebula``, ``galaxy``, ``cluster``, ``planetary``, ``star``,
    ``planet``, ``moon``, ``sun``, ``other``. Emission-ness is NOT a class:
    it is the orthogonal ``narrowband`` flag.

    Note the deliberate ``planetary`` (planetary *nebula*) vs ``planet``
    (a Solar System planet) split: the ``planetary`` test runs first, so a
    ``'Planetary Nebula'`` kind never falls through to ``planet``. Solar
    System targets set their classification explicitly rather than routing a
    raw kind through here, but the branches exist for filter symmetry.
    """
    k = kind.lower()
    if "galax" in k:
        return "galaxy"
    if "planetary" in k:
        return "planetary"
    if "nebula" in k or "hii" in k or "supernova" in k:
        # 'Star cluster + Nebula' lands here on purpose: photographically
        # the nebulosity is the subject
        return "nebula"
    if "cluster" in k or "association" in k:
        return "cluster"
    if "moon" in k or "satellite" in k:
        return "moon"
    if "planet" in k:
        return "planet"
    if "sun" in k:
        return "sun"
    if "star" in k:
        return "star"
    return "other"


def filter_targets(targets: list[Target], spec: str | list[str]) -> list[Target]:
    """Filter targets by class and emission tokens.

    Class tokens (``nebula``/``galaxy``/``cluster``/``planetary``/``star``/
    ``other``) are OR-ed; ``emission``/``non-emission`` AND on top of them.
    ``'galaxy,cluster'`` keeps either; ``'emission,nebula'`` keeps emission
    nebulae only.

    Raises
    ------
    CatalogError
        On an unknown token.
    """
    raw = spec.split(",") if isinstance(spec, str) else list(spec)
    tokens = {t.strip().lower() for t in raw if t.strip()}
    unknown = tokens - FILTER_TOKENS
    if unknown:
        raise CatalogError(
            f"unknown filter {', '.join(sorted(unknown))!s}: "
            f"choose from {', '.join(sorted(FILTER_TOKENS))}"
        )
    classes = tokens & _CLASS_TOKENS
    want_emission = "emission" in tokens
    want_non = "non-emission" in tokens

    out = []
    for t in targets:
        if classes and t.classification not in classes:
            continue
        if want_emission and not want_non and not t.narrowband:
            continue
        if want_non and not want_emission and t.narrowband:
            continue
        out.append(t)
    return out


def find_targets(query: str, targets: list[Target]) -> list[Target]:
    """Find targets by designation or name substring.

    A designation query (``m42``, ``NGC 7000``, ``ic1396``) matches exactly
    via normalized identifiers; otherwise the query is a case-insensitive
    substring of the target name.
    """
    q_ident = _norm_ident(query)
    exact = [t for t in targets if q_ident in t.idents]
    if exact:
        return exact
    q = query.lower()
    return [t for t in targets if q in t.name.lower()]


def build_targets(
    use_nebulae: bool = True,
    use_pyongc: bool = True,
    use_sharpless: bool = True,
    use_solar_system: bool = True,
    ss_moons: bool = False,
    pyongc_catalogs: list[str] | None = None,
    mag_limit: float = 11.0,
    sharpless_min_diam: float = 10.0,
    targets_file: str | Path | None = None,
) -> list[Target]:
    """Assemble the final target list, deduplicated across sources.

    Source priority for duplicates: user targets > curated nebulae >
    Sharpless > pyongc. Solar System bodies carry no designation and no fixed
    coordinate, so they are appended after dedup — they never collide with a
    deep-sky object.

    The curated nebulae rank above Sharpless on purpose: a hand-tuned entry
    (nickname, imaging size, e.g. ``Sh2-101 Tulip``) wins over the bare
    catalogue ``Sh2-101`` via the shared ``SH2-N`` identifier, so the nickname
    survives while Sharpless supplies the ~180 emission nebulae the curated
    list never had.

    Parameters
    ----------
    use_nebulae : bool
        Include the small curated rescue list (:func:`curated_nebulae`).
    use_pyongc : bool
        Include pyongc objects (offline Messier/NGC/IC).
    use_sharpless : bool
        Include the Sharpless (Sh2) H II regions (offline emission nebulae).
    use_solar_system : bool
        Include the Solar System bodies (Moon + planets, offline).
    ss_moons : bool
        Also include the major natural satellites. Requires the JPL satellite
        ephemeris (online); the caller must have loaded it via
        :func:`harp.solar_system.load_moon_ephemeris` first.
    pyongc_catalogs : list of str or None
        pyongc catalog names among ``M``/``NGC``/``IC``; defaults to ``['M']``.
    mag_limit : float
        Magnitude limit applied to pyongc objects only. Sharpless H II regions
        have no magnitude and are never magnitude-filtered.
    sharpless_min_diam : float
        Minimum Sharpless angular diameter to keep, arcmin (drops tiny/compact
        H II regions that are not deep-sky imaging targets).
    targets_file : str, pathlib.Path or None
        Optional user-defined targets file (see :func:`user_targets`).
    """
    items: list[Target] = []
    if targets_file is not None:
        items += user_targets(targets_file)
    if use_nebulae:
        items += curated_nebulae()
    # pyongc BEFORE Sharpless: a catalogued NGC/IC/M object (richer metadata,
    # cross-ids, a name) must win a positional dedup tie over the bare Sharpless
    # region at the same spot (e.g. NGC281 Pacman == Sh2-184, 1.4' apart). The
    # Sharpless *size* is still adopted afterwards via _apply_sharpless_sizes,
    # so Sharpless acts as a size authority without stealing identity; its
    # objects that have NO NGC/IC counterpart survive dedup on their own.
    if use_pyongc:
        items += pyongc_targets(pyongc_catalogs or ["M"], mag_limit)
    if use_sharpless:
        from harp.sharpless import sharpless_targets

        items += sharpless_targets(min_diam_arcmin=sharpless_min_diam)
    result = dedup(items)
    if use_sharpless:
        result = _apply_sharpless_sizes(result)
    if use_solar_system:
        from harp.solar_system import solar_system_targets

        result += solar_system_targets(include_moons=ss_moons)
    return result


def _apply_sharpless_sizes(targets: list[Target]) -> list[Target]:
    """Override too-small pyongc nebula sizes with the Sharpless extent.

    pyongc/OpenNGC nebula dimensions come from the LBN bright-plate table and
    often under-report the imageable H-alpha extent (measured 2-12x too small
    for e.g. the Heart, the Soul, the Lagoon). The Sharpless catalogue measures
    the region's extent; via the vendored Sh2<->NGC/IC/M concordance we map an
    NGC/IC/M object to its Sharpless number and, when Sharpless is larger,
    adopt that diameter and mark the object narrowband (H II = emission).

    Two guards keep the transfer honest, because a small catalogued object
    (a cluster or a planetary nebula) can be embedded in a much larger
    Sharpless region and must NOT inherit the whole region's size:

    - **type gate**: only objects whose class is ``nebula`` are eligible, so
      clusters (NGC2264) and planetary nebulae (NGC6302) are left untouched;
    - **ratio cap**: the enlargement must be <= ``_SH2_MAX_ENLARGE`` (4x), so
      an embedded knot does not adopt a whole-complex diameter.

    Only enlarges — never shrinks — and drops the minor axis (Sharpless gives
    a single max diameter).
    """
    from dataclasses import replace

    from harp.sharpless import sh2_concordance, sharpless_sizes

    concord = sh2_concordance()
    if not concord:
        return targets
    sizes = sharpless_sizes()
    # reverse map: NGC/IC/M ident -> best Sharpless diameter linked to it
    override: dict[str, float] = {}
    for sh2_num, designations in concord.items():
        diam = sizes.get(f"SH2-{sh2_num}")
        if diam is None:
            continue
        for desig in designations:
            key = _norm_ident(desig)
            override[key] = max(override.get(key, 0.0), diam)

    out: list[Target] = []
    for t in targets:
        hit = next((override[i] for i in t.idents if i in override), None)
        eligible = (
            hit is not None
            and kind_class(t.kind) == "nebula"
            and (t.maj_arcmin is None or (t.maj_arcmin < hit <= t.maj_arcmin * _SH2_MAX_ENLARGE))
        )
        if eligible:
            out.append(replace(t, maj_arcmin=hit, min_arcmin=None, narrowband=True))
        else:
            out.append(t)
    return out
