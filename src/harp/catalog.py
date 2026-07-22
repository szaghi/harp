"""Deep-sky target catalog: curated large nebulae + optional pyongc objects.

The curated list exists because the pyongc catalogue is filtered by V
magnitude, and many large emission nebulae have no integrated magnitude at
all (surface brightness is what matters): a magnitude cut would drop exactly
the targets this planner is for.
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


# Curated large-nebula catalogue (RA, Dec J2000, maj', min', const, Halpha?)
# Sizes in arcminutes; Halpha=True -> great in narrowband (dual-band filter).
_NEBULAE: list[tuple[str, str, str, float, float, str, bool]] = [
    ("NGC7000 North America", "20h59m17s", "+44d31m00s", 120, 100, "Cyg", True),
    ("IC5070 Pelican", "20h50m48s", "+44d21m00s", 60, 50, "Cyg", True),
    ("IC1318 Sadr/Gamma Cyg", "20h22m00s", "+40d15m00s", 150, 120, "Cyg", True),
    ("NGC6888 Crescent", "20h12m07s", "+38d21m00s", 18, 12, "Cyg", True),
    ("Sh2-101 Tulip", "19h59m54s", "+35d16m00s", 16, 9, "Cyg", True),
    ("NGC6960 Veil-West", "20h45m38s", "+30d43m00s", 70, 6, "Cyg", True),
    ("NGC6992 Veil-East", "20h56m19s", "+31d43m00s", 60, 8, "Cyg", True),
    ("IC5146 Cocoon", "21h53m29s", "+47d16m00s", 12, 12, "Cyg", True),
    ("IC1396 Elephant Trunk", "21h39m00s", "+57d30m00s", 170, 140, "Cep", True),
    ("Sh2-155 Cave", "22h57m54s", "+62d31m00s", 50, 30, "Cep", True),
    ("NGC7380 Wizard", "22h47m21s", "+58d06m00s", 25, 25, "Cep", True),
    ("Sh2-171 NGC7822", "00h03m36s", "+67d09m00s", 60, 30, "Cep", True),
    ("NGC7635 Bubble", "23h20m48s", "+61d12m00s", 15, 8, "Cas", True),
    ("IC1805 Heart", "02h33m22s", "+61d27m00s", 150, 150, "Cas", True),
    ("IC1848 Soul", "02h55m24s", "+60d25m00s", 150, 75, "Cas", True),
    ("NGC281 Pacman", "00h52m48s", "+56d37m00s", 35, 30, "Cas", True),
    ("Sh2-132 Lion", "22h19m00s", "+56d05m00s", 40, 30, "Cep", True),
    ("IC59/63 Ghost of Cas", "00h56m42s", "+61d04m00s", 20, 10, "Cas", True),
    ("NGC1499 California", "04h03m18s", "+36d25m00s", 145, 40, "Per", True),
    ("IC405 Flaming Star", "05h16m12s", "+34d16m00s", 37, 19, "Aur", True),
    ("IC410 Tadpoles", "05h22m36s", "+33d31m00s", 40, 30, "Aur", True),
    ("IC417 Spider", "05h28m06s", "+34d25m00s", 13, 13, "Aur", True),
    ("Simeis147 Spaghetti", "05h39m00s", "+28d00m00s", 180, 180, "Tau", True),
    ("M42 Orion", "05h35m17s", "-05d23m00s", 85, 60, "Ori", True),
    ("NGC2237 Rosette", "06h32m18s", "+05d03m00s", 80, 80, "Mon", True),
    ("NGC2264 Cone/Xmas", "06h41m06s", "+09d53m00s", 40, 30, "Mon", True),
    ("IC443 Jellyfish", "06h17m42s", "+22d47m00s", 50, 40, "Gem", True),
    ("M27 Dumbbell", "19h59m36s", "+22d43m00s", 8, 6, "Vul", True),
    ("M8 Lagoon", "18h03m37s", "-24d23m00s", 90, 40, "Sgr", True),
    ("M16 Eagle/Pillars", "18h18m48s", "-13d47m00s", 35, 28, "Ser", True),
    ("M17 Omega", "18h20m47s", "-16d10m00s", 46, 37, "Sgr", True),
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
    """Return the curated large-nebulae catalogue (no magnitude filter)."""
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

    Parameters
    ----------
    catalogs : list of str
        pyongc catalog names, e.g. ``['M']`` or ``['M', 'NGC']``.
    mag_limit : float
        Keep only objects with visual (or blue) magnitude <= this.

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
            if mv is None or mv > mag_limit:
                continue
            dims = obj.dimensions or (None, None, None)
            try:
                # identifiers = (messier, ngc, ic, common_names, other_idents)
                messier, ngc, ic, _, others = obj.identifiers
                idents = {obj.name}
                for ref in (messier, ngc, ic, *(others or [])):
                    if isinstance(ref, str):
                        idents.add(ref)
                    elif isinstance(ref, list | tuple):
                        idents.update(ref)
                out.append(
                    Target(
                        name=obj.name,
                        kind=obj.type,
                        const=obj.constellation,
                        mag=round(mv, 1),
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
    use_solar_system: bool = True,
    ss_moons: bool = False,
    pyongc_catalogs: list[str] | None = None,
    mag_limit: float = 11.0,
    targets_file: str | Path | None = None,
) -> list[Target]:
    """Assemble the final target list, deduplicated across sources.

    Source priority for duplicates: user targets > curated nebulae > pyongc.
    Solar System bodies carry no designation and no fixed coordinate, so they
    are appended after dedup — they never collide with a deep-sky object.

    Parameters
    ----------
    use_nebulae : bool
        Include the curated large-nebulae catalogue.
    use_pyongc : bool
        Include pyongc objects (offline Messier/NGC/IC).
    use_solar_system : bool
        Include the Solar System bodies (Moon + planets, offline).
    ss_moons : bool
        Also include the major natural satellites. Requires the JPL satellite
        ephemeris (online); the caller must have loaded it via
        :func:`harp.solar_system.load_moon_ephemeris` first.
    pyongc_catalogs : list of str or None
        pyongc catalog names among ``M``/``NGC``/``IC``; defaults to ``['M']``.
    mag_limit : float
        Magnitude limit applied to pyongc objects only.
    targets_file : str, pathlib.Path or None
        Optional user-defined targets file (see :func:`user_targets`).
    """
    items: list[Target] = []
    if targets_file is not None:
        items += user_targets(targets_file)
    if use_nebulae:
        items += curated_nebulae()
    if use_pyongc:
        items += pyongc_targets(pyongc_catalogs or ["M"], mag_limit)
    result = dedup(items)
    if use_solar_system:
        from harp.solar_system import solar_system_targets

        result += solar_system_targets(include_moons=ss_moons)
    return result
