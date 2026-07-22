"""Stable programmatic API for HARP frontends (CLI, Android app, scripts).

This module is the supported surface for non-CLI consumers: it re-exports
the core entry points and provides JSON-safe converters. Breaking changes
here bump :data:`API_VERSION` and the package minor version; everything
else in the package is internal and may change freely.
"""

from __future__ import annotations

from typing import Any

from harp.catalog import (
    FILTER_TOKENS,
    Target,
    build_targets,
    filter_targets,
    find_targets,
    kind_class,
    user_targets,
)
from harp.horizon import Horizon, build_profile, validate_profile, write_hrz
from harp.links import LINK_PROVIDERS, target_link
from harp.mosaic import Panel, mosaic_panels
from harp.optics import Rig, parse_sensor
from harp.planner import NightPlan, PlanRow, Site, desirability, plan_night
from harp.sites import SiteEntry, SitesConfig, default_config_path, slugify

# 2: added the multi-site store (SitesConfig/SiteEntry) and site JSON helpers.
# 3: Solar System targets (Target.body/coord=None) and the target
#    classification field, both surfaced additively in every converter.
API_VERSION = "3"

__all__ = [
    "API_VERSION",
    "FILTER_TOKENS",
    "Horizon",
    "NightPlan",
    "Panel",
    "PlanRow",
    "Rig",
    "Site",
    "SiteEntry",
    "SitesConfig",
    "Target",
    "build_profile",
    "build_targets",
    "default_config_path",
    "desirability",
    "filter_targets",
    "find_targets",
    "info_to_dict",
    "kind_class",
    "mosaic_panels",
    "panels_to_dict",
    "parse_sensor",
    "plan_night",
    "plan_to_dict",
    "site_to_dict",
    "slugify",
    "target_link",
    "target_to_dict",
    "user_targets",
    "validate_profile",
    "write_hrz",
]


def site_to_dict(
    site: SiteEntry, *, has_hrz: bool = False, is_default: bool = False
) -> dict[str, Any]:
    """JSON-safe view of a saved site, for the app's site list.

    Parameters
    ----------
    site : SiteEntry
        The stored site.
    has_hrz : bool
        Whether the site's ``.hrz`` file actually exists on disk (the caller
        resolves this against the config dir).
    is_default : bool
        Whether this site is the selected default.
    """
    return {
        "name": site.name,
        "label": site.label,
        "lat": site.lat,
        "lon": site.lon,
        "elev": site.elev,
        "tz": site.tz,
        "hrz": site.hrz,
        "has_hrz": has_hrz,
        "default": is_default,
    }


def _ra_dec(t: Target) -> tuple[float | None, float | None]:
    """Fixed ICRS (ra, dec) in degrees, or (None, None) for a moving body."""
    if t.coord is None:
        return None, None
    return round(t.coord.ra.deg, 5), round(t.coord.dec.deg, 5)


def target_to_dict(t: Target) -> dict[str, Any]:
    """JSON-safe view of a catalog target.

    ``ra_deg``/``dec_deg`` are ``None`` for Solar System bodies (they have no
    fixed coordinate); ``body`` names the ``get_body`` body for those and is
    ``None`` for fixed deep-sky objects.
    """
    ra_deg, dec_deg = _ra_dec(t)
    return {
        "name": t.name,
        "kind": t.kind,
        "classification": t.classification,
        "body": t.body,
        "const": t.const,
        "mag": t.mag,
        "maj_arcmin": t.maj_arcmin,
        "min_arcmin": t.min_arcmin,
        "narrowband": t.narrowband,
        "ra_deg": ra_deg,
        "dec_deg": dec_deg,
        "idents": sorted(t.idents),
    }


def _row_to_dict(r: PlanRow, plan: NightPlan, link_site: str) -> dict[str, Any]:
    t = plan.targets[r.index]
    ra_deg, dec_deg = _ra_dec(t)
    return {
        "name": r.name,
        "score": r.score,
        "kind": r.kind,
        # 'class' kept for backward compatibility; PlanRow.classification is
        # now authoritative (explicit for Solar System bodies, derived for DSOs).
        "class": r.classification,
        "classification": r.classification,
        "body": t.body,
        "const": r.const,
        "mag": r.mag,
        "hours": r.hours,
        "cont_hours": r.cont_hours,
        "window": r.window,
        "alt_max": r.alt_max,
        "az_peak": r.az_peak,
        "peak_time": r.peak_time,
        "moon_sep": r.moon_sep,
        "moon": r.moon,
        "frame": r.frame,
        "detail": r.detail,
        "ra_deg": ra_deg,
        "dec_deg": dec_deg,
        "narrowband": t.narrowband,
        "link": target_link(t, link_site),
    }


def plan_to_dict(
    plan: NightPlan,
    top: int | None = None,
    curves: bool = False,
    link_site: str = "simbad",
) -> dict[str, Any]:
    """JSON-safe view of a night plan.

    Parameters
    ----------
    plan : NightPlan
        The plan to serialize.
    top : int or None
        Limit rows (None = all ranked rows).
    curves : bool
        Also include per-row altitude curves plus the shared time grid,
        Moon altitude, and per-row horizon profile — what a frontend needs
        to draw the altitude charts natively.
    link_site : str
        Provider for each row's ``link`` field.
    """
    tz = plan.window.tz
    rows = plan.rows if top is None else plan.rows[:top]
    out: dict[str, Any] = {
        "api_version": API_VERSION,
        "night": {
            "date": plan.window.day.isoformat(),
            "dusk": plan.window.dusk.to_datetime(timezone=tz).isoformat(),
            "dawn": plan.window.dawn.to_datetime(timezone=tz).isoformat(),
            "grid_min": plan.window.grid_min,
        },
        "site": {
            "label": plan.site.label,
            "lat": plan.site.lat,
            "lon": plan.site.lon,
            "elev": plan.site.elev,
            "tz": plan.site.tz,
        },
        "rig": {
            "focal_mm": plan.rig.focal_mm,
            "sensor": plan.rig.sensor_name,
            "fov_w_arcmin": round(plan.rig.fov_w, 1),
            "fov_h_arcmin": round(plan.rig.fov_h, 1),
        },
        "moon": {
            "illumination": round(plan.moon.illumination, 3),
            "up": plan.moon.up_str,
        },
        "horizon": plan.horizon_label,
        "rows": [_row_to_dict(r, plan, link_site) for r in rows],
    }
    if curves:
        out["curves"] = {
            "times": [t.to_datetime(timezone=tz).isoformat() for t in plan.window.times],
            "moon_alt": [round(float(a), 1) for a in plan.moon.alt],
            "targets": {
                r.name: {
                    "alt": [round(float(a), 1) for a in plan.alt[r.index]],
                    "horizon": [
                        round(float(h), 1) for h in plan.horizon.altitude(plan.az[r.index])
                    ],
                    "visible": [bool(v) for v in plan.vis[r.index]],
                }
                for r in rows
            },
        }
    return out


def panels_to_dict(
    target_name: str, panels: list[Panel], rig: Rig, pa_deg: float
) -> dict[str, Any]:
    """JSON-safe view of a mosaic panel plan."""
    return {
        "api_version": API_VERSION,
        "target": target_name,
        "pa_deg": pa_deg,
        "panel_fov_arcmin": [round(rig.fov_long, 1), round(rig.fov_short, 1)],
        "overlap": rig.overlap,
        "panels": [
            {
                "row": p.row,
                "col": p.col,
                "ra_deg": round(p.coord.ra.deg, 5),
                "dec_deg": round(p.coord.dec.deg, 5),
            }
            for p in panels
        ],
    }


def info_to_dict(t: Target, rig: Rig) -> dict[str, Any]:
    """JSON-safe view of a single target's details plus all provider links."""
    d = target_to_dict(t)
    d["api_version"] = API_VERSION
    d["frame"] = "planetary" if t.body is not None else rig.framing(t.maj_arcmin, t.min_arcmin)
    d["links"] = {provider: target_link(t, provider) for provider in LINK_PROVIDERS}
    return d
