"""Sites bridge: durable multi-site store for the Android app, JSON in/out.

Same contract as the other bridges (everything crosses the Kotlin/Python
boundary as JSON strings). All operations go through the shared
:class:`harp.sites.SitesConfig`, so the app and the ``harp sites`` CLI create
identical ``sites.yaml`` + ``.hrz`` layouts -- the config the app writes under
its ``filesDir`` can be copied straight to a desktop ``~/.config/harp/``.

The caller (Kotlin) passes ``config_dir`` -- the app's ``filesDir`` -- and the
store lives at ``<config_dir>/sites.yaml`` with one ``<name>.hrz`` per site
beside it. ``filesDir`` is private, durable app storage: unlike ``cacheDir``
it survives OS cache eviction and 'Clear cache'.
"""

from __future__ import annotations

import json
from pathlib import Path


def _config_path(config_dir: str) -> Path:
    return Path(config_dir) / "sites.yaml"


def list_sites(config_dir: str) -> str:
    """Return the saved sites and the default, as JSON.

    Returns
    -------
    str
        ``{"default": <name|null>, "sites": [<site dict>, ...]}`` or
        ``{"error": ...}``.
    """
    try:
        from harp.api import SitesConfig, site_to_dict

        store = SitesConfig.load(_config_path(config_dir), create=True)
        default = store.default_name()
        out = []
        for name in store.names():
            site = store.get(name)
            hp = store.hrz_path(site)
            out.append(
                site_to_dict(
                    site,
                    has_hrz=bool(hp and hp.exists()),
                    is_default=(name == default),
                )
            )
        return json.dumps({"default": default, "sites": out})
    except Exception as e:  # surfaced in the UI, never a crash
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def save_site(request_json: str) -> str:
    """Add or update a site; optionally write its horizon. Returns JSON.

    Request keys: config_dir (required), name (required), label, lat, lon,
    elev, tz, hrz (raw .hrz text to store), make_default (bool). When the site
    already exists, omitted geo fields keep their stored values.

    Returns
    -------
    str
        ``{"ok": true, "name": <slug>, "default": <name>}`` or
        ``{"error": ...}``.
    """
    try:
        from harp.api import SiteEntry, SitesConfig, slugify

        req = json.loads(request_json)
        store = SitesConfig.load(_config_path(req["config_dir"]), create=True)
        slug = slugify(req["name"])

        if slug in store.names():
            base = store.get(slug)
            entry = SiteEntry(
                name=slug,
                label=str(req.get("label") or base.label),
                lat=float(req["lat"]) if req.get("lat") is not None else base.lat,
                lon=float(req["lon"]) if req.get("lon") is not None else base.lon,
                elev=float(req["elev"]) if req.get("elev") is not None else base.elev,
                tz=str(req.get("tz") or base.tz),
            )
        else:
            entry = SiteEntry(
                name=slug,
                label=str(req.get("label") or req["name"]),
                lat=float(req["lat"]),
                lon=float(req["lon"]),
                elev=float(req.get("elev") or 0.0),
                tz=str(req.get("tz") or "UTC"),
            )

        hrz = req.get("hrz")
        store.upsert(
            entry,
            hrz_content=(str(hrz) if hrz else None),
            make_default=bool(req.get("make_default")),
        )
        store.save()
        return json.dumps({"ok": True, "name": slug, "default": store.default_name()})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def remove_site(config_dir: str, name: str) -> str:
    """Remove a site and its .hrz. Returns the new default as JSON."""
    try:
        from harp.api import SitesConfig

        store = SitesConfig.load(_config_path(config_dir), create=True)
        store.remove(name)
        store.save()
        return json.dumps({"ok": True, "default": store.default_name()})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def set_default(config_dir: str, name: str) -> str:
    """Select the default site. Returns JSON."""
    try:
        from harp.api import SitesConfig

        store = SitesConfig.load(_config_path(config_dir), create=True)
        store.set_default(name)
        store.save()
        return json.dumps({"ok": True, "default": name})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def hrz_path_for(config_dir: str, name: str) -> str:
    """Absolute path to a site's .hrz, or "" if it has none / doesn't exist.

    The planner bridge takes a raw ``hrz_path``; this resolves the selected
    site's stored horizon to that path.
    """
    try:
        from harp.api import SitesConfig

        store = SitesConfig.load(_config_path(config_dir), create=True)
        site = store.get(name)
        hp = store.hrz_path(site)
        return str(hp) if hp and hp.exists() else ""
    except Exception:
        return ""
