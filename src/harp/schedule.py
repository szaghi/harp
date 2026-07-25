"""Multi-night scheduling: when, over the coming weeks, to shoot one target.

``harp plan`` answers "what should I shoot tonight?". This module answers the
question imagers actually ask more often -- *"when is the best night this month
for the Heart Nebula?"* -- by inverting the query from night->targets to
target->nights.

No new physics: each candidate night is planned with the same
:func:`harp.planner.plan_night` and ranked by the same desirability score, so
"best night" means exactly what it means everywhere else in HARP. Building a
second scoring model would be the real risk here -- two definitions of "good"
that drift apart.

PERFORMANCE. A naive sweep re-plans the whole catalogue once per night: about
1.6 s x N, or 47 s for a month. That is not an interactive command. The fix is
structural rather than clever -- filter to the requested target FIRST, then
sweep -- which takes a 30-night search to under 3 s.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import date as ddate
from datetime import timedelta

from harp.catalog import Target
from harp.errors import EphemerisError
from harp.horizon import Horizon
from harp.optics import Rig
from harp.planner import PlanRow, Site, plan_night

__all__ = [
    "NightScore",
    "best_nights",
    "score_nights",
]


@dataclass(frozen=True)
class NightScore:
    """How good one night is for one target.

    Parameters
    ----------
    date : str
        The night, ``YYYY-MM-DD`` -- the calendar day it STARTS on, matching
        ``harp plan``'s convention.
    score : float
        Desirability 0-100, the same score the planner assigns that target on
        that night.
    hours : float
        Total usable hours through the site horizon.
    cont_hours : float
        Longest continuous run -- the number that actually sizes a session.
    window : str
        Local ``HH:MM-HH:MM`` of that continuous run.
    alt_max : float
        Peak altitude, degrees.
    moon_sep : float
        Minimum Moon separation across the usable window, degrees.
    moon : str
        The Moon-impact verdict for that night.
    moon_illum : float
        Moon illuminated fraction at dusk, 0-1. Surfaced because it is usually
        the reason one night beats another across a month.
    """

    date: str
    score: float
    hours: float
    cont_hours: float
    window: str
    alt_max: float
    moon_sep: float
    moon: str
    moon_illum: float

    @property
    def usable(self) -> bool:
        """Whether the target cleared the horizon at all on this night."""
        return self.hours > 0.0


def _row_for(rows: list[PlanRow], target_name: str) -> PlanRow | None:
    """The plan row matching ``target_name``, or None if it was filtered out.

    A night on which the target never clears the horizon yields no row at all;
    that is a legitimate answer -- "not that night" -- not an error.
    """
    for r in rows:
        if r.name == target_name:
            return r
    return None


def score_nights(
    site: Site,
    rig: Rig,
    horizon: Horizon,
    target: Target,
    start: str | None = None,
    days: int = 30,
    grid_min: int = 10,
    min_moon_sep: float = 0.0,
) -> list[NightScore]:
    """Score each of ``days`` consecutive nights for one target.

    Returned in DATE order; use :func:`best_nights` for the ranking. Both are
    offered because the two views answer different questions -- "when is it
    best?" versus "what does the month look like?" -- and a caller that wants
    a calendar should not have to re-sort.

    Parameters
    ----------
    site, rig, horizon : Site, Rig, Horizon
        As for :func:`harp.planner.plan_night`.
    target : Target
        The single target to evaluate. Passing one target rather than the
        whole catalogue is what makes a month-long sweep interactive.
    start : str or None
        First night, ``YYYY-MM-DD``. None means today.
    days : int
        How many consecutive nights to evaluate.
    grid_min : int
        Sampling step, minutes. Coarser than ``plan``'s default 5 on purpose:
        a month-long sweep does not need minute precision to tell good nights
        from bad, and 10 halves the work.
    min_moon_sep : float
        Moon-separation cut. Defaults to 0 -- unlike ``plan``, a night where
        the Moon sits close should be REPORTED as poor, not silently dropped,
        or the caller cannot tell "bad night" from "no such night".

    Returns
    -------
    list[NightScore]
        One entry per night, in date order. Nights on which the target never
        rises are included with zero hours, so the calendar has no holes.

    Raises
    ------
    harp.errors.EphemerisError
        If ``days`` is not positive or ``start`` is not a valid date.
    """
    if days <= 0:
        raise EphemerisError(f"days must be positive, got {days}")
    try:
        first = ddate.fromisoformat(start) if start else ddate.today()
    except ValueError as e:
        raise EphemerisError(f"invalid start date {start!r}: {e}") from e

    # Suppress astropy's non-rotation-transformation warning BY CATEGORY, not
    # only via a blanket 'ignore'. A blanket filter still constructs each
    # warning object and formats its message before discarding it -- measurably
    # ~20% of a night's runtime with a few hundred separations.
    from astropy.coordinates.errors import NonRotationTransformationWarning

    out: list[NightScore] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        warnings.filterwarnings("ignore", category=NonRotationTransformationWarning)
        for offset in range(days):
            night = (first + timedelta(days=offset)).isoformat()
            plan = plan_night(
                site=site,
                rig=rig,
                horizon=horizon,
                targets=[target],
                date=night,
                grid_min=grid_min,
                min_moon_sep=min_moon_sep,
                # No usability cuts: this command reports how good each night
                # is, so a poor night must appear as poor rather than vanish.
                min_hours=0.0,
                min_peak_alt=0.0,
            )
            illum = round(float(plan.moon.illumination), 3)
            row = _row_for(plan.rows, target.name)
            if row is None:
                out.append(
                    NightScore(
                        date=night,
                        score=0.0,
                        hours=0.0,
                        cont_hours=0.0,
                        window="--",
                        alt_max=0.0,
                        moon_sep=0.0,
                        moon="n/a",
                        moon_illum=illum,
                    )
                )
                continue
            out.append(
                NightScore(
                    date=night,
                    score=float(row.score),
                    hours=float(row.hours),
                    cont_hours=float(row.cont_hours),
                    window=row.window,
                    alt_max=float(row.alt_max),
                    moon_sep=float(row.moon_sep),
                    moon=row.moon,
                    moon_illum=illum,
                )
            )
    return out


def best_nights(nights: list[NightScore], top: int | None = None) -> list[NightScore]:
    """Rank nights best-first.

    Sorted by score, then by continuous window as the tie-break -- when two
    nights score alike, the one giving the longer uninterrupted run is the one
    worth driving out for. Date breaks any remaining tie so the ordering is
    deterministic, and the earlier night wins, which is what a planner wants.

    Parameters
    ----------
    nights : list[NightScore]
        As returned by :func:`score_nights`.
    top : int or None
        Keep only the best ``top``; None keeps all.
    """
    ranked = sorted(nights, key=lambda n: (-n.score, -n.cont_hours, n.date))
    return ranked if top is None else ranked[:top]
