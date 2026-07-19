"""Mosaic geometry: per-panel sky coordinates for multi-frame targets.

The panel grid lies in the tangent plane at the target center: ``nx`` panels
step along the object's major axis, ``ny`` along the minor one, with the
rig's overlap fraction between neighbours. The grid is rotated by the
position angle of the major axis (degrees, North through East; PA 0 puts
the major axis toward North) and projected back to the sphere with
``SkyCoord.spherical_offsets_by``, so panel centers stay correct at any
declination.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import astropy.units as u
from astropy.coordinates import SkyCoord

from harp.optics import Rig

__all__ = ["Panel", "mosaic_panels"]


@dataclass(frozen=True)
class Panel:
    """One mosaic panel: grid position and sky coordinates of its center.

    Parameters
    ----------
    row, col : int
        1-based grid position; columns step along the major axis.
    coord : astropy.coordinates.SkyCoord
        ICRS center of the panel.
    """

    row: int
    col: int
    coord: SkyCoord


def mosaic_panels(center: SkyCoord, nx: int, ny: int, rig: Rig, pa_deg: float = 0.0) -> list[Panel]:
    """Compute the panel centers of an ``nx x ny`` mosaic around a target.

    Parameters
    ----------
    center : astropy.coordinates.SkyCoord
        Target center (mosaic centroid).
    nx, ny : int
        Panels along the major/minor axis (from :meth:`Rig.grid_dims`).
    rig : Rig
        Provides panel field of view and overlap.
    pa_deg : float
        Position angle of the object's major axis, degrees North through
        East. 0 puts the major axis (and the long FOV side) toward North.

    Returns
    -------
    list of Panel
        Panels ordered row-major (row 1 first), centered on ``center``.
    """
    step_u = rig.fov_long * (1.0 - rig.overlap)  # arcmin along major axis
    step_v = rig.fov_short * (1.0 - rig.overlap)  # arcmin along minor axis
    pa = math.radians(pa_deg)
    panels: list[Panel] = []
    for j in range(ny):
        v = (j - (ny - 1) / 2.0) * step_v
        for i in range(nx):
            u_off = (i - (nx - 1) / 2.0) * step_u
            # rotate (u, v) from object axes into (East, North)
            d_east = u_off * math.sin(pa) + v * math.cos(pa)
            d_north = u_off * math.cos(pa) - v * math.sin(pa)
            coord = center.spherical_offsets_by(d_east * u.arcmin, d_north * u.arcmin)
            panels.append(Panel(row=j + 1, col=i + 1, coord=coord))
    return panels
