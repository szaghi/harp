"""Deep-sky target catalog: curated large nebulae + optional pyongc objects.

The curated list exists because the pyongc catalogue is filtered by V
magnitude, and many large emission nebulae have no integrated magnitude at
all (surface brightness is what matters): a magnitude cut would drop exactly
the targets this planner is for.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from astropy.coordinates import SkyCoord

from harp.errors import CatalogError

log = logging.getLogger(__name__)

__all__ = ["Target", "build_targets", "suggest_detail"]


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
    coord : astropy.coordinates.SkyCoord
        ICRS coordinates.
    """

    name: str
    kind: str
    const: str
    mag: float | None
    maj_arcmin: float | None
    min_arcmin: float | None
    narrowband: bool
    coord: SkyCoord


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
        )
        for nm, ra, dec, maj, minr, con, ha in _NEBULAE
    ]


def pyongc_targets(catalogs: list[str], mag_limit: float) -> list[Target]:
    """Load objects from the offline pyongc catalogue, filtered by magnitude.

    Parameters
    ----------
    catalogs : list of str
        pyongc catalog names, e.g. ``['M']`` or ``['M', 'NGC']``.
    mag_limit : float
        Keep only objects with visual (or blue) magnitude <= this.

    Raises
    ------
    CatalogError
        If pyongc is not installed.
    """
    try:
        from pyongc import ongc
    except ImportError as e:
        raise CatalogError("pyongc is required for catalog objects (pip install pyongc)") from e

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
            mv = vis_mag(obj.magnitudes)
            if mv is None or mv > mag_limit:
                continue
            dims = obj.dimensions or (None, None, None)
            try:
                out.append(
                    Target(
                        name=obj.name,
                        kind=obj.type,
                        const=obj.constellation,
                        mag=round(mv, 1),
                        maj_arcmin=dims[0],
                        min_arcmin=dims[1],
                        narrowband=False,
                        coord=coord_of(obj),
                    )
                )
            except Exception as e:  # malformed catalogue entry: skip, don't die
                log.debug("skipping pyongc object %s: %s", obj.name, e)
    return out


def dedup(targets: list[Target], sep_deg: float = 0.15) -> list[Target]:
    """Drop targets closer than ``sep_deg`` to an earlier one (curated wins)."""
    uniq: list[Target] = []
    for t in targets:
        if not any(t.coord.separation(v.coord).deg < sep_deg for v in uniq):
            uniq.append(t)
    return uniq


def build_targets(
    use_nebulae: bool = True,
    use_pyongc: bool = True,
    pyongc_catalogs: list[str] | None = None,
    mag_limit: float = 11.0,
) -> list[Target]:
    """Assemble the final target list: curated nebulae + pyongc, deduplicated.

    Parameters
    ----------
    use_nebulae : bool
        Include the curated large-nebulae catalogue.
    use_pyongc : bool
        Include pyongc objects (offline Messier/NGC/IC).
    pyongc_catalogs : list of str or None
        pyongc catalog names; defaults to ``['M']``.
    mag_limit : float
        Magnitude limit applied to pyongc objects only.
    """
    items: list[Target] = []
    if use_nebulae:
        items += curated_nebulae()
    if use_pyongc:
        items += pyongc_targets(pyongc_catalogs or ["M"], mag_limit)
    return dedup(items)
