"""Site horizon mask: load, interpolate, and build N.I.N.A. ``.hrz`` files.

The ``.hrz`` format (N.I.N.A. official docs):

- ``azimuth altitude`` pairs in degrees, space separated;
- azimuth referred to TRUE NORTH, clockwise (N=0, E=90, S=180, W=270);
- azimuth in ascending order, file starting at Az 0;
- comment lines start with ``#``.

N.I.N.A. interpolates linearly between consecutive points, so a profile only
needs the vertices where the slope changes; fully blocked sectors are modelled
with altitude 90 degrees.

Magnetic-declination correction is applied when the file is CREATED
(:func:`build_profile`), not at planning time: every ``.hrz`` is in true north.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from harp.errors import HorizonError

log = logging.getLogger(__name__)

__all__ = [
    "Horizon",
    "build_profile",
    "preview_profile",
    "validate_profile",
    "write_hrz",
]


@dataclass(frozen=True)
class Horizon:
    """Azimuth-dependent obstruction mask of an observing site.

    Parameters
    ----------
    az : numpy.ndarray
        Azimuths in degrees, true north, ascending.
    alt : numpy.ndarray
        Obstruction altitude in degrees at each azimuth.
    """

    az: np.ndarray
    alt: np.ndarray

    @classmethod
    def from_hrz(cls, path: str | Path) -> Horizon:
        """Load a horizon profile from a ``.hrz`` file.

        Parameters
        ----------
        path : str or pathlib.Path
            Horizon file, azimuth in true north.

        Returns
        -------
        Horizon
            The parsed profile, sorted by azimuth.

        Raises
        ------
        HorizonError
            If the file is missing, unparsable, or holds fewer than 2 points.
        """
        path = Path(path)
        if not path.exists():
            raise HorizonError(f"horizon file not found: {path}")
        az, alt = [], []
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                a, h = line.split()[:2]
                az.append(float(a))
                alt.append(float(h))
            except ValueError as e:
                raise HorizonError(f"bad line in {path}: {line!r}") from e
        if len(az) < 2:
            raise HorizonError(f"horizon file {path} needs at least 2 points")
        az_arr, alt_arr = np.asarray(az), np.asarray(alt)
        order = np.argsort(az_arr)
        return cls(az=az_arr[order], alt=alt_arr[order])

    @classmethod
    def flat(cls, altitude: float = 0.0) -> Horizon:
        """Return an unobstructed horizon at a constant altitude.

        Parameters
        ----------
        altitude : float
            Obstruction altitude in degrees applied at every azimuth.
        """
        return cls(az=np.array([0.0, 360.0]), alt=np.array([altitude, altitude]))

    def altitude(self, az: np.ndarray | float) -> np.ndarray:
        """Obstruction altitude at the given azimuth(s), linear interpolation.

        Parameters
        ----------
        az : numpy.ndarray or float
            Azimuth(s) in degrees, any range (wrapped into [0, 360)).

        Returns
        -------
        numpy.ndarray
            Obstruction altitude in degrees, periodic over 360.
        """
        return np.interp(np.mod(az, 360.0), self.az, self.alt, period=360.0)


# ---------------------------------------------------------------------------
# Builder: measured magnetic vertices -> true-north .hrz profile
# ---------------------------------------------------------------------------


def build_profile(
    points_mag: list[tuple[float, float]],
    declination: float,
    blocked_alt: float = 90.0,
) -> list[tuple[float, float]]:
    """Convert measured magnetic vertices into a true-north ``.hrz`` profile.

    Applies the magnetic declination, sorts by azimuth, and closes the loop at
    0/360 by wrap-around interpolation (azimuth as a periodic quantity).

    Parameters
    ----------
    points_mag : list of (float, float)
        Measured ``(magnetic_azimuth, altitude)`` vertices in degrees.
    declination : float
        Magnetic declination at the site in degrees, positive towards East
        (NOAA IGRF/WMM). Use 0.0 if the measuring app already outputs true
        azimuth.
    blocked_alt : float
        Altitude assigned when the 0/360 closure falls in a degenerate gap.

    Returns
    -------
    list of (float, float)
        Sorted ``(true_azimuth, altitude)`` profile starting at Az 0 and
        ending at Az 360.
    """
    points = sorted(((az + declination) % 360.0, alt) for az, alt in points_mag)
    az = [p[0] for p in points]
    alt = [p[1] for p in points]

    # Circular closure: value at 0/360 interpolated between last and first
    # point, treating azimuth as periodic (wrap at 360).
    a0, alt0 = az[0], alt[0]
    a1, alt1 = az[-1], alt[-1]
    gap = (a0 + 360.0) - a1
    if gap <= 0:
        edge_alt = blocked_alt
    else:
        frac = (360.0 - a1) / gap
        edge_alt = alt1 + (alt0 - alt1) * frac

    profile: list[tuple[float, float]] = []
    if az[0] > 0.0:
        profile.append((0.0, edge_alt))
    profile.extend(zip(az, alt, strict=True))
    if az[-1] < 360.0:
        profile.append((360.0, edge_alt))
    return profile


def validate_profile(profile: list[tuple[float, float]]) -> list[str]:
    """Sanity-check a profile before writing; return a list of problems.

    Parameters
    ----------
    profile : list of (float, float)
        ``(true_azimuth, altitude)`` pairs.

    Returns
    -------
    list of str
        Human-readable problems; empty when the profile is valid.
    """
    problems = []
    az = [p[0] for p in profile]
    if az != sorted(az):
        problems.append("azimuths are not in ascending order")
    if len(set(az)) != len(az):
        problems.append("duplicate azimuths (merge them)")
    if az and az[0] != 0.0:
        problems.append("profile does not start at Az 0")
    for a, h in profile:
        if not 0.0 <= a <= 360.0:
            problems.append(f"azimuth out of range: {a}")
        if not 0.0 <= h <= 90.0:
            problems.append(f"altitude out of range [0,90]: {h}")
    if len(profile) < 2:
        problems.append("at least 2 points are required")
    return problems


def write_hrz(profile: list[tuple[float, float]], path: str | Path) -> None:
    """Write a profile to a ``.hrz`` file (N.I.N.A./Stellarium compatible)."""
    path = Path(path)
    lines = ["# Az Alt  (site horizon - true north, degrees)"]
    lines += [f"{a:.1f} {h:.1f}" for a, h in profile]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def preview_profile(profile: list[tuple[float, float]], png_path: str | Path) -> None:
    """Save a polar preview of the profile (inner area = visible sky)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    az = [math.radians(a) for a, _ in profile]
    alt = [h for _, h in profile]
    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("N")  # 0 at top = North
    ax.set_theta_direction(-1)  # clockwise
    ax.plot(az, alt, marker="o")
    ax.fill(az, alt, alpha=0.15)
    ax.set_rmax(90)
    ax.set_rlabel_position(135)
    ax.set_title("Horizon profile (obstruction altitude)\ninner area = visible sky")
    ax.set_xticks([math.radians(x) for x in (0, 90, 180, 270)])
    ax.set_xticklabels(["N", "E", "S", "W"])
    fig.savefig(png_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    log.info("horizon preview saved: %s", png_path)
