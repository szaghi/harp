"""Observation-log bridge for the Android app, JSON in/out.

Same contract as the other bridges (everything crosses the Kotlin/Python
boundary as JSON strings). All operations go through the shared
:class:`harp.log.ObservationLog`, so the app and the ``harp log`` CLI produce
an identical ``observations.yaml`` -- the file the app writes under its
``filesDir`` can be copied straight to a desktop ``~/.config/harp/`` and
queried with the CLI, exactly as ``sites.yaml`` already can.

The caller (Kotlin) passes ``config_dir`` -- the app's ``filesDir`` -- and the
log lives at ``<config_dir>/observations.yaml``, beside the sites store.
``filesDir`` is private, durable app storage: unlike ``cacheDir`` it survives
OS cache eviction and 'Clear cache'.

This bridge WRITES USER DATA THAT CANNOT BE REGENERATED. A lost plan is
recomputed in seconds; a lost observing history is gone. Hence: every write
goes through the core's own save (no bespoke serialisation here), and
:func:`export_text` exists so the user can always get their log out.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _log_path(config_dir: str) -> Path:
    return Path(config_dir) / "observations.yaml"


def _load(config_dir: str):
    from harp.api import ObservationLog

    return ObservationLog.load(_log_path(config_dir))


def list_totals(config_dir: str) -> str:
    """Per-target totals, most-imaged first.

    Returns
    -------
    str
        The :func:`harp.api.log_to_dict` payload, or ``{"error": ...}``.
    """
    try:
        from harp.api import log_to_dict

        return json.dumps(log_to_dict(_load(config_dir)))
    except Exception as e:  # surfaced in the UI, never a crash
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def integration_for(config_dir: str, target: str) -> str:
    """How much integration one target already has.

    Returns
    -------
    str
        ``{"target": ..., "sessions": n, "integration_s": f,
        "integration": "4h 20m"}`` or ``{"error": ...}``.
    """
    try:
        from harp.api import fmt_integration

        log = _load(config_dir)
        seconds = log.integration_for(target)
        return json.dumps(
            {
                "target": target,
                "sessions": len(log.for_target(target)),
                "integration_s": round(seconds, 1),
                "integration": fmt_integration(seconds),
            }
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def totals_map(config_dir: str) -> str:
    """Every target's integration at once, keyed by normalised name.

    The Plan tab shows totals across a whole list of rows. Calling
    :func:`integration_for` per row would re-read and re-parse the file once
    per target; this returns the whole map in a single pass instead.

    Keys are casefolded and space-stripped, matching how the core matches
    target names, so the caller must normalise its lookup key the same way.

    Returns
    -------
    str
        ``{"totals": {"m42": {"integration": "8h 20m", "sessions": 2}, ...}}``
        or ``{"error": ...}``.
    """
    try:
        log = _load(config_dir)
        out: dict[str, Any] = {}
        for t in log.totals():
            key = t.target.replace(" ", "").casefold()
            out[key] = {
                "target": t.target,
                "sessions": t.sessions,
                "integration_s": round(t.integration_s, 1),
                "integration": t.integration_label,
            }
        return json.dumps({"totals": out})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def add_entry(config_dir: str, request_json: str) -> str:
    """Append one imaging session.

    Request keys: target (required); date (YYYY-MM-DD, default today); subs
    (int); exposure_s (float); filter, site, rig, notes (str).

    Returns the target's NEW total, so the UI can confirm the write with a
    fact the user can check ("M42: now 8h 20m") rather than a bare 'saved'.
    """
    try:
        from harp.api import LogEntry, fmt_integration
        from harp.log import today_iso

        req = json.loads(request_json)
        target = str(req.get("target") or "").strip()
        if not target:
            return json.dumps({"error": "no target given"})

        subs = req.get("subs")
        exposure = req.get("exposure_s")
        entry = LogEntry(
            target=target,
            date=str(req.get("date") or today_iso()),
            subs=int(subs) if subs not in (None, "") else None,
            exposure_s=float(exposure) if exposure not in (None, "") else None,
            filter_name=str(req.get("filter") or ""),
            site=str(req.get("site") or ""),
            rig=str(req.get("rig") or ""),
            notes=str(req.get("notes") or ""),
        )
        log = _load(config_dir)
        log.add(entry)
        log.save()

        seconds = log.integration_for(target)
        return json.dumps(
            {
                "ok": True,
                "target": target,
                "logged": entry.integration_label,
                "sessions": len(log.for_target(target)),
                "integration_s": round(seconds, 1),
                "integration": fmt_integration(seconds),
                "path": str(log.path),
            }
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def sessions_for(config_dir: str, target: str) -> str:
    """Every recorded session on one target, newest first.

    Returns
    -------
    str
        ``{"target": ..., "sessions": [<entry dict>, ...]}`` or
        ``{"error": ...}``.
    """
    try:
        log = _load(config_dir)
        entries = log.for_target(target)
        return json.dumps(
            {
                "target": target,
                "sessions": [
                    {
                        "date": e.date,
                        "subs": e.subs,
                        "exposure_s": e.exposure_s,
                        "integration": e.integration_label,
                        "filter": e.filter_name,
                        "site": e.site,
                        "rig": e.rig,
                        "notes": e.notes,
                    }
                    for e in sorted(entries, key=lambda x: x.date, reverse=True)
                ],
            }
        )
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def export_text(config_dir: str) -> str:
    """The raw ``observations.yaml`` text, for the share sheet.

    The log is the one thing in the app the user cannot regenerate, so it must
    be possible to get it out. Returning the file's own text (rather than a
    re-serialisation) means what the user shares is byte-identical to what the
    CLI would read back.

    Returns
    -------
    str
        ``{"text": ..., "path": ..., "empty": bool}`` or ``{"error": ...}``.
    """
    try:
        p = _log_path(config_dir)
        if not p.exists():
            return json.dumps({"text": "", "path": str(p), "empty": True})
        text = p.read_text(encoding="utf-8")
        return json.dumps({"text": text, "path": str(p), "empty": not text.strip()})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
