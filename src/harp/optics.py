"""Optical rig: focal length + sensor, field of view, mosaic framing."""

from __future__ import annotations

import math
from dataclasses import dataclass

from harp.errors import ConfigError

__all__ = ["SENSOR_PRESETS", "Rig", "parse_sensor"]

# Known sensors: name -> (width_mm, height_mm)
SENSOR_PRESETS: dict[str, tuple[float, float]] = {
    "ToupTek ATR2600C (IMX571) 23.5x15.7": (23.5, 15.7),
    "Full-frame (36x24)": (36.0, 24.0),
    "ASI533 square (11.3x11.3)": (11.3, 11.3),
}


def parse_sensor(value: str) -> tuple[str, float, float]:
    """Resolve a sensor spec into ``(name, width_mm, height_mm)``.

    Parameters
    ----------
    value : str
        A preset name in :data:`SENSOR_PRESETS`, or ``'WxH'`` in mm
        (e.g. ``'23.5x15.7'``).

    Raises
    ------
    ConfigError
        If the value is neither a preset nor a parsable ``WxH`` pair.
    """
    if value in SENSOR_PRESETS:
        w, h = SENSOR_PRESETS[value]
        return value, w, h
    if "x" in value.lower():
        try:
            w_s, h_s = value.lower().split("x")
            return f"custom {value}", float(w_s), float(h_s)
        except ValueError as e:
            raise ConfigError(f"cannot parse sensor size {value!r} as WxH mm") from e
    raise ConfigError(
        f"sensor {value!r} not recognized: use a preset "
        f"({', '.join(SENSOR_PRESETS)}) or the 'WxH' format in mm"
    )


@dataclass(frozen=True)
class Rig:
    """Telescope + camera pair, with derived framing geometry.

    Parameters
    ----------
    focal_mm : float
        Effective focal length in mm (correctors/reducers included).
    sensor_name : str
        Human-readable sensor label.
    sensor_w_mm, sensor_h_mm : float
        Sensor physical size in mm.
    overlap : float
        Mosaic panel overlap fraction.
    margin : float
        Framing margin: an object fits "1 frame" only within this fraction
        of the field of view.
    """

    focal_mm: float
    sensor_name: str
    sensor_w_mm: float
    sensor_h_mm: float
    overlap: float = 0.15
    margin: float = 0.90

    @staticmethod
    def _fov_arcmin(size_mm: float, focal_mm: float) -> float:
        return 2.0 * math.degrees(math.atan(size_mm / 2.0 / focal_mm)) * 60.0

    @property
    def fov_w(self) -> float:
        """Field of view along the sensor width, in arcminutes."""
        return self._fov_arcmin(self.sensor_w_mm, self.focal_mm)

    @property
    def fov_h(self) -> float:
        """Field of view along the sensor height, in arcminutes."""
        return self._fov_arcmin(self.sensor_h_mm, self.focal_mm)

    @property
    def fov_long(self) -> float:
        """Longer field-of-view side, in arcminutes."""
        return max(self.fov_w, self.fov_h)

    @property
    def fov_short(self) -> float:
        """Shorter field-of-view side, in arcminutes."""
        return min(self.fov_w, self.fov_h)

    def framing(self, maj_arcmin: float | None, min_arcmin: float | None) -> str:
        """Classify an object as ``'1 frame'`` or ``'mosaic NxM'``.

        Parameters
        ----------
        maj_arcmin, min_arcmin : float or None
            Object major/minor axis in arcminutes; ``None`` size gives
            ``'n/a'``, a missing minor axis falls back to the major one.
        """
        if maj_arcmin is None:
            return "n/a"
        minr = min_arcmin if min_arcmin else maj_arcmin
        if maj_arcmin <= self.fov_long * self.margin and minr <= self.fov_short * self.margin:
            return "1 frame"
        nx = max(1, math.ceil(maj_arcmin / (self.fov_long * (1.0 - self.overlap))))
        ny = max(1, math.ceil(minr / (self.fov_short * (1.0 - self.overlap))))
        return "1 frame" if nx * ny == 1 else f"mosaic {nx}x{ny}"
