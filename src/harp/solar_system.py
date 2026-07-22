"""Solar System targets: the Moon and the major planets.

Unlike deep-sky objects, Solar System bodies move: a single fixed
:class:`~harp.catalog.Target.coord` would be physically wrong (Mars swings
several degrees across a night, the Moon ~0.5 deg/hour). So these targets
carry ``coord=None`` and a ``body`` name; the planner computes their alt-az
and apparent size live, per grid sample, from :func:`astropy.coordinates.get_body`.

The default set is exactly what astropy's *built-in* ephemeris resolves with
no download and no network — Sun, Moon and the eight planets — preserving
HARP's offline guarantee (and its Android/Chaquopy build, which cannot ship
or fetch multi-megabyte JPL kernels).

Natural satellites (Titan, the Galilean moons, ...) are NOT in the built-in
ephemeris: ``get_body`` cannot resolve them. They require a JPL satellite
kernel loaded at run time — a real dependency and a network download — and
on a deep-sky rig they are unresolvable dots inside the parent planet's
glare. They are therefore gated behind an explicit opt-in
(:func:`load_moon_ephemeris`), online-only, and off by default.
"""

from __future__ import annotations

from dataclasses import dataclass

from harp.catalog import Target
from harp.errors import EphemerisError

__all__ = [
    "SS_BODIES",
    "SS_MOONS",
    "SolarBody",
    "load_moon_ephemeris",
    "solar_system_targets",
]


@dataclass(frozen=True)
class SolarBody:
    """A Solar System body known to the planner.

    Parameters
    ----------
    body : str
        The ``get_body`` name, e.g. ``'mars'``.
    label : str
        Display name, e.g. ``'Mars'``.
    classification : str
        ``'planet'``, ``'moon'``, or ``'sun'``.
    radius_km : float
        Equatorial radius, used to derive the apparent disk diameter from
        the geocentric/topocentric distance at each grid sample.
    naif_id : int or None
        NAIF body ID, needed only for satellites loaded from a JPL kernel;
        ``None`` for the built-in bodies (addressed by ``body`` name).
    """

    body: str
    label: str
    classification: str
    radius_km: float
    naif_id: int | None = None


# Built-in set: resolvable by astropy's default ephemeris, fully offline.
# Radii are equatorial (IAU 2015 nominal), in km.
SS_BODIES: tuple[SolarBody, ...] = (
    SolarBody("moon", "Moon", "moon", 1737.4),
    SolarBody("mercury", "Mercury", "planet", 2439.7),
    SolarBody("venus", "Venus", "planet", 6051.8),
    SolarBody("mars", "Mars", "planet", 3396.2),
    SolarBody("jupiter", "Jupiter", "planet", 71492.0),
    SolarBody("saturn", "Saturn", "planet", 60268.0),
    SolarBody("uranus", "Uranus", "planet", 25559.0),
    SolarBody("neptune", "Neptune", "planet", 24764.0),
)

# Satellites: NOT in the built-in ephemeris. Require a JPL satellite kernel
# (see load_moon_ephemeris). NAIF IDs address them within that kernel.
SS_MOONS: tuple[SolarBody, ...] = (
    SolarBody("501", "Io", "moon", 1821.6, naif_id=501),
    SolarBody("502", "Europa", "moon", 1560.8, naif_id=502),
    SolarBody("503", "Ganymede", "moon", 2634.1, naif_id=503),
    SolarBody("504", "Callisto", "moon", 2410.3, naif_id=504),
    SolarBody("606", "Titan", "moon", 2574.7, naif_id=606),
)


def solar_system_targets(include_moons: bool = False) -> list[Target]:
    """Build the Solar System target list.

    Parameters
    ----------
    include_moons : bool
        Also include the major natural satellites. This requires the JPL
        satellite ephemeris to have been loaded first via
        :func:`load_moon_ephemeris` (online, off by default); the caller is
        responsible for that. The bodies are still returned regardless — the
        ephemeris failure, if any, surfaces later in the planner when their
        position is computed.

    Returns
    -------
    list of harp.catalog.Target
        Targets with ``coord=None`` and a populated ``body``. Size and
        magnitude are left ``None`` here: the apparent disk is distance- and
        time-dependent and is computed in the planner.
    """
    bodies = SS_BODIES + (SS_MOONS if include_moons else ())
    return [
        Target(
            name=b.label,
            kind=b.classification.capitalize(),
            const="",
            mag=None,
            maj_arcmin=None,
            min_arcmin=None,
            narrowband=False,
            coord=None,
            idents=frozenset(),
            classification=b.classification,
            body=b.body,
        )
        for b in bodies
    ]


def load_moon_ephemeris() -> None:
    """Load a JPL satellite ephemeris so natural satellites can be placed.

    The built-in astropy ephemeris resolves only Sun/Moon/planets. Placing
    Titan or the Galilean moons needs a JPL satellite kernel, which astropy
    fetches from a remote URL on first use — this is the ONLY part of HARP
    that touches the network, hence the explicit opt-in.

    Raises
    ------
    EphemerisError
        If the ephemeris cannot be loaded (typically no network access).
    """
    from astropy.coordinates import solar_system_ephemeris

    try:
        # 'jpl' pulls the default DE kernel; satellite positions come from the
        # planetary-satellite kernels astropy resolves by NAIF id on demand.
        solar_system_ephemeris.set("jpl")
    except Exception as e:  # network failure, missing kernel, jplephem absent
        raise EphemerisError(
            "loading the JPL satellite ephemeris failed (needs network access "
            "and jplephem); Solar System moons are unavailable offline"
        ) from e
