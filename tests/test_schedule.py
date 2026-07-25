"""Tests for multi-night scheduling.

The load-bearing assertion here is that the Moon drives the ranking for a
BROADBAND target: that is the whole reason to ask "which night" rather than
"which target", and if it ever stops holding, the command has no purpose.
Narrowband targets are deliberately checked NOT to swing, because a dual-band
filter really is near-immune to moonlight.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from harp.api import Horizon, Rig, Site, build_targets, find_targets
from harp.cli import app
from harp.errors import EphemerisError
from harp.schedule import NightScore, best_nights, score_nights

SITE = Site(label="test", lat=41.9, lon=12.5, elev=100.0, tz="Europe/Rome")
RIG = Rig(focal_mm=800.0, sensor_name="APS-C", sensor_w_mm=23.5, sensor_h_mm=15.7)
# Tromso. Used only for the never-visible case: from 69.6 N nothing below
# dec -20.4 ever rises, which the mid-latitude site cannot demonstrate.
ARCTIC = Site(label="arctic", lat=69.6, lon=18.9, elev=10.0, tz="Europe/Oslo")


@pytest.fixture(scope="module")
def catalogue() -> list:
    """Messier once for the whole module: building it per test dominates runtime."""
    return build_targets(pyongc_catalogs=["M"], use_solar_system=False)


def _target(catalogue: list, name: str):
    return find_targets(name, catalogue)[0]


class TestScoreNights:
    def test_one_entry_per_night_in_date_order(self, catalogue: list) -> None:
        nights = score_nights(
            SITE,
            RIG,
            Horizon.flat(0.0),
            _target(catalogue, "M51"),
            start="2026-02-01",
            days=7,
        )
        assert len(nights) == 7
        assert [n.date for n in nights] == sorted(n.date for n in nights)
        assert nights[0].date == "2026-02-01"
        assert nights[-1].date == "2026-02-07"

    def test_rejects_nonpositive_days(self, catalogue: list) -> None:
        with pytest.raises(EphemerisError, match="days must be positive"):
            score_nights(SITE, RIG, Horizon.flat(0.0), _target(catalogue, "M51"), days=0)

    def test_rejects_bad_start_date(self, catalogue: list) -> None:
        with pytest.raises(EphemerisError, match="invalid start date"):
            score_nights(
                SITE, RIG, Horizon.flat(0.0), _target(catalogue, "M51"), start="not-a-date"
            )

    def test_unusable_nights_are_reported_not_dropped(self, catalogue: list) -> None:
        """A target below the horizon must leave a hole-free calendar.

        Dropping such nights would make "bad night" indistinguishable from
        "no such night" in the output.

        Uses an ARCTIC site rather than the shared one: from latitude 41.9 even
        M7 (dec -34.8) scrapes above the horizon for a few minutes, so the
        never-visible case has to be built where it is unambiguously true —
        from 69.6 N nothing below dec -20.4 ever rises.
        """
        nights = score_nights(
            ARCTIC,
            RIG,
            Horizon.flat(0.0),
            _target(catalogue, "M7"),
            start="2026-02-01",
            days=4,
        )
        assert len(nights) == 4
        assert not any(n.usable for n in nights)
        assert all(n.hours == 0.0 for n in nights)

    def test_moon_illumination_is_reported(self, catalogue: list) -> None:
        nights = score_nights(
            SITE,
            RIG,
            Horizon.flat(0.0),
            _target(catalogue, "M51"),
            start="2026-02-01",
            days=20,
        )
        illums = [n.moon_illum for n in nights]
        assert all(0.0 <= i <= 1.0 for i in illums)
        # Across 20 nights the Moon must visibly wax or wane.
        assert max(illums) - min(illums) > 0.5


class TestMoonDrivesTheRanking:
    def test_broadband_target_prefers_a_dark_moon(self, catalogue: list) -> None:
        """The central claim: for a galaxy, the best nights are near new Moon.

        M51 is high and long-visible all February from this site, so altitude
        and hours barely vary — the Moon is what is left to decide.
        """
        nights = score_nights(
            SITE,
            RIG,
            Horizon.flat(0.0),
            _target(catalogue, "M51"),
            start="2026-02-01",
            days=28,
        )
        ranked = best_nights(nights)
        mean_best = sum(n.moon_illum for n in ranked[:5]) / 5
        mean_worst = sum(n.moon_illum for n in ranked[-5:]) / 5
        assert mean_best < mean_worst, "best nights should have a darker Moon"
        assert mean_best < 0.5, "best nights should cluster near new Moon"

    def test_narrowband_target_barely_swings(self, catalogue: list) -> None:
        """A dual-band filter really is near-immune; a flat month is correct.

        The counterpart to the test above: if narrowband scores DID swing with
        the Moon, the Moon model would be wrong, not this command.
        """
        nights = score_nights(
            SITE,
            RIG,
            Horizon.flat(0.0),
            _target(catalogue, "M42"),
            start="2026-02-01",
            days=28,
        )
        spread = max(n.score for n in nights) - min(n.score for n in nights)
        assert spread < 2.0


class TestBestNights:
    def _mk(self, date: str, score: float, cont: float = 1.0) -> NightScore:
        return NightScore(
            date=date,
            score=score,
            hours=cont,
            cont_hours=cont,
            window="--",
            alt_max=50.0,
            moon_sep=90.0,
            moon="none",
            moon_illum=0.1,
        )

    def test_ranks_by_score_descending(self) -> None:
        got = best_nights([self._mk("2026-02-01", 50.0), self._mk("2026-02-02", 90.0)])
        assert [n.date for n in got] == ["2026-02-02", "2026-02-01"]

    def test_ties_break_on_continuous_window(self) -> None:
        """Equal scores: the night giving the longer uninterrupted run wins."""
        got = best_nights(
            [self._mk("2026-02-01", 90.0, cont=3.0), self._mk("2026-02-02", 90.0, cont=7.0)]
        )
        assert got[0].date == "2026-02-02"

    def test_remaining_ties_break_on_date_earliest_first(self) -> None:
        got = best_nights(
            [self._mk("2026-02-05", 90.0, cont=5.0), self._mk("2026-02-02", 90.0, cont=5.0)]
        )
        assert got[0].date == "2026-02-02"

    def test_top_limits_without_reordering(self) -> None:
        nights = [self._mk(f"2026-02-{d:02d}", float(d)) for d in range(1, 6)]
        got = best_nights(nights, top=2)
        assert len(got) == 2
        assert [n.date for n in got] == ["2026-02-05", "2026-02-04"]


class TestWhenCli:
    def test_table_output(self, runner: CliRunner) -> None:
        res = runner.invoke(
            app,
            [
                "when",
                "M51",
                "--config",
                "examples/sites.yaml",
                "--start",
                "2026-02-01",
                "--days",
                "5",
                "--top",
                "3",
            ],
        )
        assert res.exit_code == 0, res.output
        assert "M51" in res.output
        assert "2026-02" in res.output

    def test_json_output(self, runner: CliRunner) -> None:
        res = runner.invoke(
            app,
            [
                "when",
                "M51",
                "--config",
                "examples/sites.yaml",
                "--start",
                "2026-02-01",
                "--days",
                "3",
                "--json",
            ],
        )
        assert res.exit_code == 0, res.output
        data = json.loads(res.output)
        assert data["api_version"] == "7"
        assert data["target"].startswith("M51")
        assert len(data["nights"]) == 3
        assert {"date", "score", "cont_hours", "moon_illum"} <= set(data["nights"][0])

    def test_never_visible_target_explains_itself(self, runner: CliRunner) -> None:
        """A target that never rises gets an explanation, not an empty table.

        The site is overridden to the Arctic rather than using the example
        config's: from latitude 41.9 even M7 scrapes the horizon on some
        nights, so asserting on the example site would be testing a
        coincidence of the chosen date window rather than the behaviour.
        """
        res = runner.invoke(
            app,
            [
                "when",
                "M7",
                "--config",
                "examples/sites.yaml",
                "--lat",
                "69.6",
                "--lon",
                "18.9",
                "--tz",
                "Europe/Oslo",
                "--start",
                "2026-02-01",
                "--days",
                "3",
            ],
        )
        assert res.exit_code == 0, res.output
        assert "never clears the horizon" in res.output

    def test_unknown_target_fails_cleanly(self, runner: CliRunner) -> None:
        res = runner.invoke(app, ["when", "NGC99999", "--config", "examples/sites.yaml"])
        assert res.exit_code == 1
