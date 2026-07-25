"""Comets as moving targets, positioned from orbital elements.

Comets are the one target class HARP cannot resolve offline. Unlike the Moon
and planets -- which astropy's built-in ephemeris places by NAME -- a comet's
position comes from a set of *osculating orbital elements* (perihelion distance
``q``, eccentricity ``e``, inclination, node, argument of perihelion, epoch of
perihelion passage) that:

* have no offline canonical source: the Minor Planet Center (MPC) and JPL
  publish them, and they are refit periodically as new astrometry arrives;
* go stale in weeks -- a bright comet outgasses, and non-gravitational forces
  pull it off any old two-body prediction;
* are not carried by astropy at all.

So this module is the ONE part of HARP that fetches from the network, gated
behind an explicit opt-in (``harp plan --comets``) exactly like the satellite
ephemeris (:func:`harp.solar_system.load_moon_ephemeris`). Offline, the opt-in
fails with a clear :class:`~harp.errors.EphemerisError`; it never degrades the
default offline plan.

Propagation is deliberately **two-body Kepler**, not a perturbed integration.
The fetched MPC line IS a two-body osculating snapshot; integrating it with
planetary perturbations and an outgassing model would fabricate precision the
input cannot support, pull in heavy dependencies, and break the Android build.
Two-body propagation is accurate to arcminutes over the element set's
weeks-long validity window -- comfortably inside HARP's horizon-planning
resolution ("does this comet clear my balcony, and is it worth chasing?").
Pointing-grade positions are NINA/ASTAP's job at the mount, after HARP has
picked the target.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from harp.catalog import Target
from harp.errors import EphemerisError

__all__ = [
    "MPC_COMETS_URL",
    "CometElements",
    "comet_targets",
    "fetch_comet_elements",
    "parse_mpc_comets",
]

#: MPC's current-comets orbital-elements file, one comet per line in the
#: classic 80-column MPC "comet ephemeris" format. Small (a few hundred
#: lines): the bright, currently observable comets, not the full database.
MPC_COMETS_URL = "https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt"

#: Standard gravitational parameter of the Sun, in au**3 / day**2. This is the
#: Gaussian gravitational constant k**2 with k = 0.01720209895; using it keeps
#: the Kepler math in the heliocentric au/day units the MPC elements are in.
_GM_SUN = 0.01720209895**2

#: A near-parabolic orbit (|e - 1| below this) is propagated as if e == 1 to
#: avoid the elliptic/hyperbolic solvers blowing up near the singularity. Most
#: bright long-period comets sit here.
_PARABOLIC_TOL = 1.0e-6


@dataclass(frozen=True)
class CometElements:
    """Two-body osculating orbital elements for one comet.

    All angles in degrees, distances in au, times as Julian Dates (TT). These
    are exactly the quantities on an MPC comet line; propagation
    (:meth:`state_au`) turns them into a heliocentric position.

    Parameters
    ----------
    designation : str
        Packed/unpacked designation, e.g. ``'C/2023 A3'``.
    name : str
        Human name if the MPC line carries one, else the designation.
    epoch_tp_jd : float
        Julian Date (TT) of perihelion passage ``T``.
    q_au : float
        Perihelion distance ``q`` in au.
    e : float
        Eccentricity (``< 1`` elliptic, ``== 1`` parabolic, ``> 1`` hyperbolic).
    incl_deg, node_deg, argp_deg : float
        Inclination ``i``, longitude of ascending node ``Omega``, argument of
        perihelion ``omega`` -- all referred to the J2000 ecliptic.
    h_mag, g_mag : float or None
        Absolute magnitude ``H`` and slope ``G`` for the standard comet
        magnitude law; ``None`` when the MPC line omits them.
    """

    designation: str
    name: str
    epoch_tp_jd: float
    q_au: float
    e: float
    incl_deg: float
    node_deg: float
    argp_deg: float
    h_mag: float | None = None
    g_mag: float | None = None

    def mean_motion(self) -> float:
        """Mean motion ``n`` in radians/day (elliptic orbits only)."""
        a = self.q_au / (1.0 - self.e)  # semi-major axis
        return math.sqrt(_GM_SUN / (a * a * a))

    def apparent_mag(self, r_au: float, delta_au: float) -> float | None:
        """Predicted total apparent magnitude via the standard comet law.

        ``m = H + 5 log10(delta) + K log10(r)``, with ``r`` the heliocentric
        distance, ``delta`` the geocentric distance, and ``K`` the activity
        slope taken directly from the MPC ``G`` column (``K`` already equals
        ``2.5 n``; it multiplies ``log10(r)`` with no further factor). Absent
        ``G``, ``K = 4`` is the conventional default (``n ~ 1.6``). Unlike a
        fixed deep-sky magnitude this is distance-dependent -- the same comet
        is far brighter near perihelion and near Earth.

        Returns ``None`` when ``H`` is unknown (the brightness cannot be
        predicted, which is different from predicting it to be faint).
        """
        if self.h_mag is None:
            return None
        k = self.g_mag if self.g_mag is not None else 4.0
        return self.h_mag + 5.0 * math.log10(delta_au) + k * math.log10(r_au)

    def state_au(self, jd_tt: float) -> tuple[float, float, float]:
        """Heliocentric J2000-ecliptic position at ``jd_tt``.

        Returns
        -------
        (float, float, float)
            ``(x, y, z)`` in au, referred to the J2000 ecliptic. The caller
            rotates to equatorial and adds the Sun's geocentric position to get
            a geocentric vector.

        Notes
        -----
        Solves Kepler's equation for the true anomaly, branching on orbit type
        (elliptic / near-parabolic / hyperbolic). Near-parabolic comets use
        Barker's equation, which has a closed-form solution and no iteration
        singularity as ``e -> 1``.
        """
        dt = jd_tt - self.epoch_tp_jd  # days since perihelion
        if abs(self.e - 1.0) < _PARABOLIC_TOL:
            nu, r = self._parabolic(dt)
        elif self.e < 1.0:
            nu, r = self._elliptic(dt)
        else:
            nu, r = self._hyperbolic(dt)
        return self._orbit_to_ecliptic(nu, r)

    def _parabolic(self, dt: float) -> tuple[float, float]:
        """True anomaly and radius on a parabola via Barker's equation."""
        # Barker: solve s**3 + 3 s - W = 0 for s = tan(nu/2), W from time.
        w = 3.0 * math.sqrt(_GM_SUN / (2.0 * self.q_au**3)) * dt
        # Real root of the depressed cubic (Cardano), always exactly one.
        y = math.cbrt(w + math.sqrt(w * w + 1.0))
        s = y - 1.0 / y
        nu = 2.0 * math.atan(s)
        r = self.q_au * (1.0 + s * s)
        return nu, r

    def _elliptic(self, dt: float) -> tuple[float, float]:
        """True anomaly and radius on an ellipse via Newton on Kepler's eqn."""
        e = self.e
        m = self.mean_motion() * dt  # mean anomaly
        m = math.fmod(m, 2.0 * math.pi)
        ea = m if e < 0.8 else math.pi  # eccentric-anomaly seed
        for _ in range(64):  # Newton-Raphson; converges in a handful of steps
            delta = (ea - e * math.sin(ea) - m) / (1.0 - e * math.cos(ea))
            ea -= delta
            if abs(delta) < 1.0e-12:
                break
        a = self.q_au / (1.0 - e)
        r = a * (1.0 - e * math.cos(ea))
        nu = 2.0 * math.atan2(
            math.sqrt(1.0 + e) * math.sin(ea / 2.0),
            math.sqrt(1.0 - e) * math.cos(ea / 2.0),
        )
        return nu, r

    def _hyperbolic(self, dt: float) -> tuple[float, float]:
        """True anomaly and radius on a hyperbola via Newton on the H eqn."""
        e = self.e
        a = self.q_au / (e - 1.0)  # positive for the hyperbolic branch
        nh = math.sqrt(_GM_SUN / (a * a * a))
        mh = nh * dt  # hyperbolic mean anomaly
        h = math.asinh(mh / e) if mh != 0.0 else 0.0  # seed
        for _ in range(64):
            delta = (e * math.sinh(h) - h - mh) / (e * math.cosh(h) - 1.0)
            h -= delta
            if abs(delta) < 1.0e-12:
                break
        r = a * (e * math.cosh(h) - 1.0)
        nu = 2.0 * math.atan2(
            math.sqrt(e + 1.0) * math.sinh(h / 2.0),
            math.sqrt(e - 1.0) * math.cosh(h / 2.0),
        )
        return nu, r

    def _orbit_to_ecliptic(self, nu: float, r: float) -> tuple[float, float, float]:
        """Rotate an (in-plane nu, r) to a J2000-ecliptic (x, y, z) in au."""
        # Position in the orbital plane, perihelion along +x.
        xp = r * math.cos(nu)
        yp = r * math.sin(nu)
        i = math.radians(self.incl_deg)
        node = math.radians(self.node_deg)
        argp = math.radians(self.argp_deg)
        cos_o, sin_o = math.cos(node), math.sin(node)
        cos_w, sin_w = math.cos(argp), math.sin(argp)
        cos_i, sin_i = math.cos(i), math.sin(i)
        # Standard 3-1-3 (omega, i, Omega) rotation from orbital to ecliptic.
        x = (cos_o * cos_w - sin_o * sin_w * cos_i) * xp + (
            -cos_o * sin_w - sin_o * cos_w * cos_i
        ) * yp
        y = (sin_o * cos_w + cos_o * sin_w * cos_i) * xp + (
            -sin_o * sin_w + cos_o * cos_w * cos_i
        ) * yp
        z = (sin_w * sin_i) * xp + (cos_w * sin_i) * yp
        return x, y, z


def parse_mpc_comets(text: str) -> list[CometElements]:
    """Parse the MPC ``CometEls.txt`` fixed-column format.

    Parameters
    ----------
    text : str
        The full contents of the MPC comet-elements file.

    Returns
    -------
    list of CometElements
        One entry per parseable line; malformed lines are skipped rather than
        aborting the whole fetch (the file is third-party and occasionally
        carries a stray line).

    Notes
    -----
    Column layout of ``CometEls.txt`` (1-indexed, per the MPC "Format For
    Cometary Orbits" spec):

    ==========  ================================================
    Columns     Field
    ==========  ================================================
    15-18       Year of perihelion passage ``T``
    20-21       Month of ``T``
    23-29       Day of ``T`` (with decimal)
    31-39       Perihelion distance ``q`` (au)
    42-49       Eccentricity ``e``
    52-59       Argument of perihelion ``omega`` (deg, J2000)
    62-69       Longitude of ascending node ``Omega`` (deg)
    72-79       Inclination ``i`` (deg)
    82-89       Epoch of osculation (YYYYMMDD) -- NOT used here; two-body
                propagation references the elements to perihelion, and this
                field sits between the inclination and the magnitude
    92-95       Absolute magnitude ``H``
    97-100      Slope parameter ``G``
    103-158     Designation and name
    ==========  ================================================

    The epoch-of-osculation field (cols 82-89) is easy to mistake for the
    magnitude -- a bare column-count off by that field yields ``H`` values
    like ``2026`` (the epoch year). The slices below are pinned against a real
    file line (C/1995 O1 Hale-Bopp).
    """
    out: list[CometElements] = []
    for raw in text.splitlines():
        if len(raw) < 80 or not raw[14:18].strip():
            continue  # header/blank/short line
        try:
            year = int(raw[14:18])
            month = int(raw[19:21])
            day = float(raw[22:29])
            q = float(raw[30:39])
            e = float(raw[41:49])
            argp = float(raw[51:59])
            node = float(raw[61:69])
            incl = float(raw[71:79])
            # cols 81:89 are the epoch of osculation (skipped); H and G follow.
            h = _opt_float(raw[91:96])
            g = _opt_float(raw[96:101])
            desig, name = _mpc_name(raw)
            tp_jd = _calendar_to_jd(year, month, day)
        except (ValueError, IndexError):
            continue  # third-party file: skip the odd malformed line
        out.append(
            CometElements(
                designation=desig,
                name=name,
                epoch_tp_jd=tp_jd,
                q_au=q,
                e=e,
                incl_deg=incl,
                node_deg=node,
                argp_deg=argp,
                h_mag=h,
                g_mag=g,
            )
        )
    return out


def fetch_comet_elements(url: str = MPC_COMETS_URL, timeout: float = 30.0) -> list[CometElements]:
    """Download and parse the MPC current-comets file (ONLINE).

    This is the only network access in HARP outside the satellite-ephemeris
    opt-in. Offline, it raises :class:`~harp.errors.EphemerisError` with a
    clear message rather than silently returning nothing.

    Parameters
    ----------
    url : str
        Source URL; defaults to :data:`MPC_COMETS_URL`.
    timeout : float
        Socket timeout in seconds.

    Returns
    -------
    list of CometElements
        The currently published bright comets.

    Raises
    ------
    EphemerisError
        On any network failure, or if the fetched file parses to zero comets
        (a sign the URL or format changed, not a legitimately empty sky).
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (fixed https URL)
            text = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise EphemerisError(
            "fetching comet elements failed (needs network access); comets are "
            "unavailable offline -- run without --comets for an offline plan"
        ) from e
    comets = parse_mpc_comets(text)
    if not comets:
        raise EphemerisError(
            f"comet-elements file at {url} parsed to zero comets; the source "
            "format may have changed"
        )
    return comets


def comet_targets(elements: list[CometElements], mag_limit: float | None = None) -> list[Target]:
    """Turn parsed comet elements into planner :class:`~harp.catalog.Target` s.

    Comets are moving bodies, so they carry ``coord=None`` and no ``body``
    name; the planner recognises them by a populated ``elements`` and
    propagates their position live (:meth:`CometElements.state_au`).

    Parameters
    ----------
    elements : list of CometElements
        Parsed comet elements (from :func:`fetch_comet_elements`).
    mag_limit : float or None
        If given, drop comets whose absolute magnitude ``H`` is fainter than
        this. Comets without an ``H`` are always kept (their brightness is
        unknown, not known-faint). ``None`` keeps everything.

    Returns
    -------
    list of harp.catalog.Target
        One moving target per comet, classified ``'comet'``.
    """
    out: list[Target] = []
    for el in elements:
        if mag_limit is not None and el.h_mag is not None and el.h_mag > mag_limit:
            continue
        out.append(
            Target(
                name=el.name,
                kind="Comet",
                const="",
                mag=el.h_mag,
                maj_arcmin=None,
                min_arcmin=None,
                narrowband=False,
                coord=None,
                idents=frozenset(),
                classification="comet",
                elements=el,
            )
        )
    return out


def _opt_float(s: str) -> float | None:
    """Parse a possibly-blank fixed-column float field."""
    s = s.strip()
    return float(s) if s else None


def _mpc_name(raw: str) -> tuple[str, str]:
    """Extract (designation, display name) from the tail of an MPC comet line.

    The designation and name occupy a fixed 56-column field at ``103-158``
    (0-indexed ``102:158``), e.g. ``C/2023 A3 (Tsuchinshan-ATLAS)``. A trailing
    *reference* field (``MPC191592``, ``MPEC 2026-O53``) follows it and must NOT
    be swept into the name -- for a periodic comet like ``14P/Wolf`` there is no
    parenthesised name, so a greedy ``raw[102:]`` would append the reference.
    When a parenthesised name is present it becomes the display name; otherwise
    the designation is used for both.
    """
    tail = raw[102:158].strip() if len(raw) > 102 else ""
    if not tail:
        return "comet", "comet"
    if "(" in tail and ")" in tail:
        desig = tail[: tail.index("(")].strip()
        name = tail[tail.index("(") + 1 : tail.index(")")].strip()
        label = f"{desig} ({name})" if desig else name
        return (desig or name), label
    return tail, tail


def _calendar_to_jd(year: int, month: int, day: float) -> float:
    """Gregorian calendar date (with fractional day) to Julian Date.

    Uses the standard Fliegel-Van Flandern algorithm; valid for all dates the
    MPC file carries. ``day`` may be fractional (perihelion time of day).
    """
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    iday = int(day)
    jdn = iday + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    frac = day - iday
    # JDN is for calendar noon; subtract 0.5 to anchor at midnight, add frac.
    return jdn - 0.5 + frac
