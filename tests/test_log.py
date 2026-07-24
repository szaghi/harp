"""Tests for the observation log.

Every test writes into pytest's ``tmp_path``; none of them touch the real
``~/.config/harp/observations.yaml``. That isolation matters more than usual
here, because the module under test is the one thing in HARP that persists
user data the user cannot regenerate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harp.cli import app
from harp.errors import ConfigError
from harp.log import (
    LogEntry,
    ObservationLog,
    default_log_path,
    fmt_integration,
)


class TestFormatting:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "--"),
            (-5, "--"),
            (60, "1m"),
            (2700, "45m"),
            (3600, "1h"),
            (18000, "5h"),
            (30000, "8h 20m"),
        ],
    )
    def test_integration_labels(self, seconds: float, expected: str) -> None:
        assert fmt_integration(seconds) == expected


class TestLogEntry:
    def test_integration_is_subs_times_exposure(self) -> None:
        e = LogEntry(target="M42", date="2026-02-15", subs=60, exposure_s=300.0)
        assert e.integration_s == 18000.0
        assert e.integration_label == "5h"

    def test_unrecorded_integration_is_zero_not_an_error(self) -> None:
        """A note-only entry is legitimate: you observed, you measured nothing."""
        e = LogEntry(target="M42", date="2026-02-15", notes="clouded out")
        assert e.integration_s == 0.0
        assert e.integration_label == "--"

    def test_record_omits_empty_fields(self) -> None:
        """A minimal entry must stay minimal, so hand-editing stays pleasant."""
        assert LogEntry(target="M42", date="2026-02-15").to_record() == {
            "target": "M42",
            "date": "2026-02-15",
        }

    def test_round_trip(self) -> None:
        e = LogEntry(
            target="M42",
            date="2026-02-15",
            subs=60,
            exposure_s=300.0,
            filter_name="L-eXtreme",
            site="balcony",
            rig="newton800",
            notes="thin cloud after 01:00",
        )
        assert LogEntry.from_record(e.to_record()) == e

    def test_missing_target_rejected(self) -> None:
        with pytest.raises(ConfigError, match="no target"):
            LogEntry.from_record({"date": "2026-02-15"})

    def test_missing_date_rejected(self) -> None:
        with pytest.raises(ConfigError, match="no date"):
            LogEntry.from_record({"target": "M42"})


class TestObservationLog:
    def test_missing_file_loads_empty(self, tmp_path: Path) -> None:
        """Before the first session there is no file; that is not an error."""
        log = ObservationLog.load(tmp_path / "nope.yaml")
        assert log.entries == []
        assert log.totals() == []

    def test_save_then_load(self, tmp_path: Path) -> None:
        p = tmp_path / "obs.yaml"
        log = ObservationLog.load(p)
        log.add(LogEntry(target="M42", date="2026-02-15", subs=60, exposure_s=300.0))
        log.save()

        again = ObservationLog.load(p)
        assert len(again.entries) == 1
        assert again.entries[0].target == "M42"
        assert again.integration_for("M42") == 18000.0

    def test_save_creates_parent_directory(self, tmp_path: Path) -> None:
        p = tmp_path / "deep" / "nested" / "obs.yaml"
        log = ObservationLog.load(p)
        log.add(LogEntry(target="M31", date="2026-02-18"))
        log.save()
        assert p.exists()

    def test_sessions_accumulate_rather_than_overwrite(self, tmp_path: Path) -> None:
        """Two nights on one target are two records summing to one total."""
        log = ObservationLog.load(tmp_path / "obs.yaml")
        log.add(LogEntry(target="M42", date="2026-02-15", subs=60, exposure_s=300.0))
        log.add(LogEntry(target="M42", date="2026-02-20", subs=40, exposure_s=300.0))
        assert len(log.for_target("M42")) == 2
        assert log.integration_for("M42") == 30000.0

    def test_matching_ignores_case_and_spaces(self, tmp_path: Path) -> None:
        """'M 42' and 'm42' are the same object; a log that misses this is useless."""
        log = ObservationLog.load(tmp_path / "obs.yaml")
        log.add(LogEntry(target="M42", date="2026-02-15", subs=10, exposure_s=60.0))
        log.add(LogEntry(target="M 42", date="2026-02-16", subs=10, exposure_s=60.0))
        assert len(log.for_target("m42")) == 2
        assert len(log.totals()) == 1

    def test_totals_ordered_by_integration(self, tmp_path: Path) -> None:
        log = ObservationLog.load(tmp_path / "obs.yaml")
        log.add(LogEntry(target="faint", date="2026-02-15", subs=10, exposure_s=60.0))
        log.add(LogEntry(target="deep", date="2026-02-16", subs=100, exposure_s=300.0))
        assert [t.target for t in log.totals()] == ["deep", "faint"]

    def test_totals_span_dates_and_collect_filters(self, tmp_path: Path) -> None:
        log = ObservationLog.load(tmp_path / "obs.yaml")
        log.add(LogEntry(target="M42", date="2026-02-20", subs=1, exposure_s=1.0, filter_name="Ha"))
        log.add(
            LogEntry(target="M42", date="2026-02-15", subs=1, exposure_s=1.0, filter_name="OIII")
        )
        (total,) = log.totals()
        # Dates are spanned by value, not by insertion order.
        assert total.first_date == "2026-02-15"
        assert total.last_date == "2026-02-20"
        assert total.filters == ["Ha", "OIII"]
        assert total.sessions == 2

    def test_malformed_file_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "obs.yaml"
        p.write_text("just a string\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="must be a mapping"):
            ObservationLog.load(p)

    def test_observations_must_be_a_list(self, tmp_path: Path) -> None:
        p = tmp_path / "obs.yaml"
        p.write_text("observations: nope\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="must be a list"):
            ObservationLog.load(p)

    def test_default_path_is_beside_the_sites_config(self) -> None:
        """One directory holds everything HARP persists."""
        assert default_log_path().name == "observations.yaml"
        assert default_log_path().parent.name == "harp"


class TestLogCli:
    def test_add_list_show(self, runner: CliRunner, tmp_path: Path) -> None:
        p = str(tmp_path / "obs.yaml")
        add = runner.invoke(
            app,
            [
                "log",
                "add",
                "M42",
                "--date",
                "2026-02-15",
                "--subs",
                "60",
                "--exposure",
                "300",
                "--filter",
                "L-eXtreme",
                "--no-interactive",
                "--path",
                p,
            ],
        )
        assert add.exit_code == 0, add.output
        assert "5h" in add.output

        listing = runner.invoke(app, ["log", "list", "--path", p])
        assert listing.exit_code == 0, listing.output
        assert "M42" in listing.output

        show = runner.invoke(app, ["log", "show", "m42", "--path", p])
        assert show.exit_code == 0, show.output
        assert "2026-02-15" in show.output

    def test_list_json(self, runner: CliRunner, tmp_path: Path) -> None:
        p = str(tmp_path / "obs.yaml")
        runner.invoke(
            app,
            [
                "log",
                "add",
                "M31",
                "--date",
                "2026-02-18",
                "--subs",
                "90",
                "--exposure",
                "180",
                "--no-interactive",
                "--path",
                p,
            ],
        )
        res = runner.invoke(app, ["log", "list", "--json", "--path", p])
        assert res.exit_code == 0, res.output
        data = json.loads(res.output)
        assert data["api_version"] == "5"
        assert data["targets"][0]["target"] == "M31"
        assert data["targets"][0]["integration"] == "4h 30m"

    def test_empty_log_is_not_an_error(self, runner: CliRunner, tmp_path: Path) -> None:
        res = runner.invoke(app, ["log", "list", "--path", str(tmp_path / "none.yaml")])
        assert res.exit_code == 0, res.output
        assert "nothing logged yet" in res.output

    def test_show_unknown_target_is_not_an_error(self, runner: CliRunner, tmp_path: Path) -> None:
        res = runner.invoke(app, ["log", "show", "M999", "--path", str(tmp_path / "n.yaml")])
        assert res.exit_code == 0, res.output
        assert "No sessions logged" in res.output
