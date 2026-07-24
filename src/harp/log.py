"""Observation log: what you actually shot, and how much of it.

HARP plans a night and then forgets it. This module closes the loop, and the
reason it records integration time rather than prose is that the question
imagers actually ask is quantitative: *how much data do I already have on this
target, and is it enough?* A free-text journal cannot answer that; a list of
(subs x exposure) can.

Storage lives beside the sites config -- ``~/.config/harp/observations.yaml``
by default -- and uses the same conventions as :mod:`harp.sites`: plain YAML a
human can read and hand-edit, a flat list rather than a nested structure, and
no database. An observing log is append-mostly, read rarely, and small even
after years (a few hundred entries), so a file is the right shape and SQLite
would be a dependency bought for nothing.

Deliberately NOT recorded: seeing, transparency, temperature. They are
laborious to type at 2am, and most of what they would tell you HARP already
computed when it planned the night.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as ddate
from pathlib import Path
from typing import Any

import yaml

from harp.errors import ConfigError

__all__ = [
    "LogEntry",
    "ObservationLog",
    "TargetTotal",
    "default_log_path",
    "fmt_integration",
    "today_iso",
]


def default_log_path() -> Path:
    """The user-level observation log (``~/.config/harp/observations.yaml``).

    Sits next to ``sites.yaml`` on purpose: one directory holds everything
    HARP persists, so backing up or syncing a setup means copying one folder.
    """
    return Path.home() / ".config" / "harp" / "observations.yaml"


def fmt_integration(seconds: float) -> str:
    """Format an integration time as ``'4h 20m'``, ``'45m'``, or ``'--'``."""
    if seconds <= 0:
        return "--"
    total_min = round(seconds / 60.0)
    hours, minutes = divmod(total_min, 60)
    if hours and minutes:
        return f"{hours}h {minutes:02d}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def today_iso() -> str:
    """Today's date as ``YYYY-MM-DD``, for defaulting a log entry."""
    return ddate.today().isoformat()


def _norm(name: str) -> str:
    """Normalise a target name for matching: casefold and drop spaces."""
    return name.replace(" ", "").casefold()


@dataclass
class LogEntry:
    """One imaging session on one target.

    A single target imaged across several nights is several entries; totals
    are summed on read. That keeps each record an immutable statement of fact
    ("on this night I got this much") rather than a running tally that has to
    be updated in place.

    Parameters
    ----------
    target : str
        Target name as HARP knows it, e.g. ``'M42'``. Not normalised against
        the catalogue: a log must be able to record something HARP has never
        heard of.
    date : str
        Session date, ``YYYY-MM-DD``. The night it STARTED, matching the
        convention ``harp plan`` uses.
    subs : int or None
        Number of sub-exposures kept.
    exposure_s : float or None
        Length of one sub-exposure, seconds.
    filter_name : str
        Filter used, free text (``'L-eXtreme'``, ``'Ha'``, ``'none'``).
    site : str
        Site label or name.
    rig : str
        Optics label.
    notes : str
        Anything else worth remembering.
    """

    target: str
    date: str
    subs: int | None = None
    exposure_s: float | None = None
    filter_name: str = ""
    site: str = ""
    rig: str = ""
    notes: str = ""

    @property
    def integration_s(self) -> float:
        """Total integration for this entry, seconds (0 when unrecorded)."""
        if self.subs is None or self.exposure_s is None:
            return 0.0
        return float(self.subs) * float(self.exposure_s)

    @property
    def integration_label(self) -> str:
        """Integration as ``'4h 20m'``, or ``'--'`` when unrecorded."""
        return fmt_integration(self.integration_s)

    def to_record(self) -> dict[str, Any]:
        """YAML-safe mapping, omitting empty optional fields.

        Empty keys are dropped rather than written as ``null`` so a
        hand-edited log stays readable and a minimal entry stays minimal.
        """
        rec: dict[str, Any] = {"target": self.target, "date": self.date}
        if self.subs is not None:
            rec["subs"] = int(self.subs)
        if self.exposure_s is not None:
            rec["exposure_s"] = float(self.exposure_s)
        for key, val in (
            ("filter", self.filter_name),
            ("site", self.site),
            ("rig", self.rig),
            ("notes", self.notes),
        ):
            if val:
                rec[key] = val
        return rec

    @classmethod
    def from_record(cls, rec: dict[str, Any]) -> LogEntry:
        """Build an entry from a YAML mapping.

        Raises
        ------
        harp.errors.ConfigError
            If ``target`` or ``date`` is missing -- an entry without both is
            not a usable observation record.
        """
        target = str(rec.get("target") or "").strip()
        date = str(rec.get("date") or "").strip()
        if not target:
            raise ConfigError(f"observation entry has no target: {rec!r}")
        if not date:
            raise ConfigError(f"observation entry for {target!r} has no date")
        subs = rec.get("subs")
        exposure = rec.get("exposure_s")
        return cls(
            target=target,
            date=date,
            subs=int(subs) if subs is not None else None,
            exposure_s=float(exposure) if exposure is not None else None,
            filter_name=str(rec.get("filter") or ""),
            site=str(rec.get("site") or ""),
            rig=str(rec.get("rig") or ""),
            notes=str(rec.get("notes") or ""),
        )


@dataclass
class TargetTotal:
    """Aggregated integration across every session on one target."""

    target: str
    sessions: int
    integration_s: float
    first_date: str
    last_date: str
    filters: list[str] = field(default_factory=list)

    @property
    def integration_label(self) -> str:
        """Total integration as ``'4h 20m'``."""
        return fmt_integration(self.integration_s)


class ObservationLog:
    """A mutable view over the observation log file.

    Mirrors :class:`harp.sites.SitesConfig`: load (or start empty), mutate,
    save. Entries are kept in file order, which is chronological in practice
    because appending is the only way they are created.
    """

    def __init__(self, path: str | Path, entries: list[LogEntry]) -> None:
        self.path = Path(path)
        self.entries = entries

    @classmethod
    def load(cls, path: str | Path | None = None) -> ObservationLog:
        """Load the log, or return an empty one when the file is absent.

        A missing log is the normal state before the first session, so it is
        not an error.

        Raises
        ------
        harp.errors.ConfigError
            If the file exists but is not a mapping with an ``observations``
            list, or an entry lacks a target/date.
        """
        p = Path(path) if path else default_log_path()
        if not p.exists():
            return cls(p, [])
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"cannot parse observation log {p}: {e}") from e
        if not isinstance(raw, dict):
            raise ConfigError(f"observation log {p} must be a mapping")
        records = raw.get("observations") or []
        if not isinstance(records, list):
            raise ConfigError(f"'observations' in {p} must be a list")
        return cls(p, [LogEntry.from_record(r) for r in records])

    def add(self, entry: LogEntry) -> None:
        """Append one session.

        Duplicates are allowed: two runs on the same target in one night are
        two genuine records, and silently merging them would destroy the fact
        that the filter or exposure changed between them.
        """
        self.entries.append(entry)

    def save(self) -> None:
        """Write the log back, creating the directory if needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"observations": [e.to_record() for e in self.entries]}
        self.path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def for_target(self, target: str) -> list[LogEntry]:
        """Every entry for one target, matched case- and space-insensitively.

        ``'m42'`` finds ``'M 42'`` -- the same leniency the catalogue search
        offers, because a log the user cannot query is a log they will not
        keep.
        """
        key = _norm(target)
        return [e for e in self.entries if _norm(e.target) == key]

    def integration_for(self, target: str) -> float:
        """Total integration on one target across all sessions, seconds."""
        return sum(e.integration_s for e in self.for_target(target))

    def totals(self) -> list[TargetTotal]:
        """Per-target totals, ordered by descending integration time."""
        buckets: dict[str, list[LogEntry]] = {}
        for e in self.entries:
            buckets.setdefault(_norm(e.target), []).append(e)
        out: list[TargetTotal] = []
        for group in buckets.values():
            dates = sorted(e.date for e in group)
            filters = sorted({e.filter_name for e in group if e.filter_name})
            out.append(
                TargetTotal(
                    # Display the most recent spelling: if the user renamed
                    # 'M 42' to 'M42' mid-log, the newer form is what they use.
                    target=group[-1].target,
                    sessions=len(group),
                    integration_s=sum(e.integration_s for e in group),
                    first_date=dates[0],
                    last_date=dates[-1],
                    filters=filters,
                )
            )
        out.sort(key=lambda t: (-t.integration_s, t.target))
        return out
