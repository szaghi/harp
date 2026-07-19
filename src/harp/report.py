"""Reporting: terminal table, CSV export, altitude charts."""

from __future__ import annotations

import csv
import logging
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np

from harp.ephemeris import fmt_hm
from harp.planner import NightPlan, PlanRow

log = logging.getLogger(__name__)

__all__ = ["plot_charts", "print_notes", "print_report", "write_csv"]

_CSV_FIELDS = [
    "object",
    "score",
    "kind",
    "const",
    "mag",
    "hours",
    "cont",
    "window",
    "altmax",
    "az",
    "peak",
    "moonsep",
    "moon",
    "frame",
    "detail",
]


def _row_record(r: PlanRow) -> dict[str, object]:
    """Map a PlanRow onto the historical CSV/table column names."""
    d = asdict(r)
    return {
        "object": d["name"],
        "score": d["score"],
        "kind": d["kind"],
        "const": d["const"],
        "mag": d["mag"] if d["mag"] is not None else "",
        "hours": d["hours"],
        "cont": d["cont_hours"],
        "window": d["window"],
        "altmax": d["alt_max"],
        "az": d["az_peak"],
        "peak": d["peak_time"],
        "moonsep": d["moon_sep"],
        "moon": d["moon"],
        "frame": d["frame"],
        "detail": d["detail"],
    }


def print_report(plan: NightPlan, top: int) -> None:
    """Print the night summary and the ranked target table."""
    w, tz = plan.window, plan.window.tz
    print(f"\n=== Night {w.day} | {plan.site.label} {plan.site.lat:.4f},{plan.site.lon:.4f} ===")
    print(f"Astronomical darkness: {fmt_hm(w.dusk, tz)} -> {fmt_hm(w.dawn, tz)} local")
    print(
        f"Moon: ~{plan.moon.illumination * 100:.0f}% illuminated  |  "
        f"above horizon: {plan.moon.up_str}"
    )
    print(f"Setup: {plan.rig.focal_mm:.0f} mm + {plan.rig.sensor_name}")
    print(
        f"Field of view: {plan.rig.fov_w:.0f}' x {plan.rig.fov_h:.0f}'  |  "
        f"horizon: {plan.horizon_label}\n"
    )

    hdr = (
        f"{'#':>2} {'object':<22}{'score':>6} {'kind':<10}{'const':<6}{'hrs':>5}{'cont':>5}"
        f"{'window':>13}{'altMx':>6}{'az':>5}{'moonSep':>8}{'Moon':>7}  frame"
    )
    print(hdr)
    print("-" * len(hdr))
    for k, r in enumerate(plan.rows[:top], 1):
        print(
            f"{k:>2} {r.name:<22}{r.score:>6.0f} {r.kind[:9]:<10}{r.const:<6}"
            f"{r.hours:>5}{r.cont_hours:>5}{r.window:>13}{r.alt_max:>6.0f}"
            f"{r.az_peak:>5.0f}{r.moon_sep:>8.0f}{r.moon:>7}  {r.frame}"
        )


def print_notes(plan: NightPlan, top: int) -> None:
    """Print the column legend and the mosaic single-frame suggestions."""
    print(
        "cont/window = longest CONTINUOUS run above your horizon "
        "(before the object enters the wall)."
    )
    print(
        "Moon: none=below horizon while imaging | ok(NB)=negligible in narrowband | "
        "low/med/high=broadband (RGB) impact."
    )

    mosaics = [r for r in plan.rows[:top] if r.frame.startswith("mosaic")]
    if mosaics:
        print("\nIf you do NOT want a mosaic, single-frame detail suggestion:")
        for r in mosaics:
            print(f"  - {r.name:<22} ({r.frame}) -> {r.detail}")


def write_csv(plan: NightPlan, path: str | Path) -> None:
    """Write all ranked rows to a CSV file (historical column layout)."""
    path = Path(path)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for r in plan.rows:
            writer.writerow(_row_record(r))
    print(f"\nCandidates: {len(plan.rows)} -> {path}")


def plot_charts(plan: NightPlan, path: str | Path, n_plot: int = 12) -> None:
    """Chart the best targets: altitude, Moon, obstruction, usable window."""
    if not plan.rows:
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    tz = plan.window.tz
    tt = [t.to_datetime(timezone=tz) for t in plan.window.times]
    sel = plan.rows[:n_plot]
    ncol = 3
    nrow = math.ceil(len(sel) / ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(4.2 * ncol, 2.6 * nrow), sharex=True, sharey=True)
    axes = np.array(axes).reshape(-1)
    for ax, r in zip(axes, sel, strict=False):
        i = r.index
        hor_i = plan.horizon.altitude(plan.az[i])
        ax.fill_between(tt, 0, hor_i, color="0.75", zorder=1)  # wall/ridge
        ax.fill_between(
            tt, hor_i, 90, where=plan.vis[i], color="#2e8b57", alpha=0.18, zorder=2
        )  # usable window
        ax.plot(tt, plan.alt[i], color="#1f4fd8", lw=1.8, zorder=4)  # target
        ax.plot(tt, plan.moon.alt, color="#e39a00", lw=1.0, ls="--", alpha=0.8, zorder=3)  # Moon
        ax.set_ylim(0, 90)
        ax.set_xlim(tt[0], tt[-1])
        ax.set_title(f"{r.name}  |  {r.hours}h  |  {r.frame}", fontsize=8.5)
        ax.tick_params(labelsize=7)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H", tz=tz))
        ax.grid(alpha=0.25)
    for ax in axes[len(sel) :]:
        ax.axis("off")
    fig.suptitle(
        f"Target altitude - night {plan.window.day}  "
        f"(blue=object, orange=Moon, grey=obstruction, green=usable window)",
        fontsize=10,
        y=1.005,
    )
    fig.supxlabel("local time", fontsize=9)
    fig.supylabel("altitude (deg)", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Chart saved: {path}")
