"""End-to-end tests for the HARP CLI."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from harp import __version__
from harp.cli import app

EXAMPLES = Path(__file__).parents[1] / "examples"


def test_version_flag(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_version_matches_pyproject(runner: CliRunner) -> None:
    import tomllib

    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    if not pyproject.exists():  # installed from wheel — mirror check not applicable
        return
    with pyproject.open("rb") as fh:
        canonical = tomllib.load(fh)["project"]["version"]
    assert __version__ == canonical


def test_no_args_shows_help(runner: CliRunner) -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_list_reads_example_config(runner: CliRunner) -> None:
    result = runner.invoke(app, ["list", "--config", str(EXAMPLES / "sites.yaml")])
    assert result.exit_code == 0
    assert "balcony" in result.output
    assert "newton800" in result.output


def test_list_missing_config_fails(runner: CliRunner) -> None:
    result = runner.invoke(app, ["list", "--config", "no_such.yaml"])
    assert result.exit_code == 1


def test_horizon_builds_reference_hrz(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "balcony.hrz"
    result = runner.invoke(
        app,
        ["horizon", str(EXAMPLES / "balcony_points.yaml"), "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    generated = [line for line in out.read_text().splitlines() if not line.startswith("#")]
    expected = [
        line
        for line in (EXAMPLES / "balcony.hrz").read_text().splitlines()
        if not line.startswith("#")
    ]
    assert generated == expected


def test_plan_smoke(runner: CliRunner, tmp_path: Path) -> None:
    """Full planning run: curated catalogue only, example site, fixed night."""
    csv_out = tmp_path / "targets.csv"
    result = runner.invoke(
        app,
        [
            "plan",
            "2026-08-15",
            "--config",
            str(EXAMPLES / "sites.yaml"),
            "--no-pyongc",
            "--no-plot",
            "--csv",
            str(csv_out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Astronomical darkness" in result.output
    assert csv_out.exists()
    header = csv_out.read_text().splitlines()[0]
    assert (
        header
        == "object,score,kind,const,mag,hours,cont,window,altmax,az,peak,moonsep,moon,frame,detail,link"
    )
    assert "simbad.cds.unistra.fr" in csv_out.read_text()
    # August night from the balcony: Cygnus/Cepheus nebulae must be in
    assert "IC1396 Elephant Trunk" in result.output


def test_plan_sort_hours_restores_hours_ranking(runner: CliRunner, tmp_path: Path) -> None:
    import csv as csv_mod

    outputs = {}
    for mode in ("score", "hours"):
        out = tmp_path / f"{mode}.csv"
        result = runner.invoke(
            app,
            [
                "plan",
                "2026-08-15",
                "--config",
                str(EXAMPLES / "sites.yaml"),
                "--no-pyongc",
                "--no-plot",
                "--sort",
                mode,
                "--csv",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        with out.open() as f:
            outputs[mode] = list(csv_mod.DictReader(f))
    hours = [float(r["hours"]) for r in outputs["hours"]]
    assert hours == sorted(hours, reverse=True)
    scores = [float(r["score"]) for r in outputs["score"]]
    assert scores == sorted(scores, reverse=True)


def test_plan_bad_sort_fails(runner: CliRunner) -> None:
    result = runner.invoke(app, ["plan", "--sort", "vibes"])
    assert result.exit_code == 1
    assert "unknown sort" in result.output


def test_plan_filter_and_sort_name(runner: CliRunner, tmp_path: Path) -> None:
    import csv as csv_mod

    out = tmp_path / "f.csv"
    result = runner.invoke(
        app,
        [
            "plan",
            "2026-08-15",
            "--config",
            str(EXAMPLES / "sites.yaml"),
            "--filter",
            "emission,nebula",
            "--sort",
            "name",
            "--no-plot",
            "--csv",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    with out.open() as f:
        rows = list(csv_mod.DictReader(f))
    assert rows
    # emission nebulae only: every row narrowband-friendly kinds
    assert all("Galaxy" not in r["kind"] and "Cluster" not in r["kind"] for r in rows)
    names = [r["object"].lower() for r in rows]
    assert names == sorted(names)  # --sort name is alphabetical ascending


def test_plan_filter_galaxy_excludes_nebulae(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "g.csv"
    result = runner.invoke(
        app,
        [
            "plan",
            "2026-08-15",
            "--config",
            str(EXAMPLES / "sites.yaml"),
            "--filter",
            "galaxy",
            "--no-plot",
            "--csv",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    content = out.read_text()
    assert "IC1396" not in content  # the nebulae are gone


def test_plan_bad_filter_fails(runner: CliRunner) -> None:
    result = runner.invoke(app, ["plan", "--filter", "quasar"])
    assert result.exit_code == 1
    assert "unknown filter" in result.output


def test_plan_with_user_targets(runner: CliRunner, tmp_path: Path) -> None:
    f = tmp_path / "my.yaml"
    f.write_text(
        "targets:\n"
        "  - name: 'My Cygnus Field'\n"
        "    ra: '20h30m00s'\n"
        "    dec: '+45d00m00s'\n"
        "    maj: 30\n"
        "    min: 20\n"
        "    narrowband: true\n"
    )
    result = runner.invoke(
        app,
        [
            "plan",
            "2026-08-15",
            "--config",
            str(EXAMPLES / "sites.yaml"),
            "--targets",
            str(f),
            "--no-pyongc",
            "--no-plot",
            "--csv",
            str(tmp_path / "out.csv"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "My Cygnus Field" in result.output


def test_plan_link_site_wikipedia(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "t.csv"
    result = runner.invoke(
        app,
        [
            "plan",
            "2026-08-15",
            "--config",
            str(EXAMPLES / "sites.yaml"),
            "--no-pyongc",
            "--no-plot",
            "--link-site",
            "wikipedia",
            "--csv",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "en.wikipedia.org" in out.read_text()


def test_plan_bad_link_site_fails(runner: CliRunner) -> None:
    result = runner.invoke(app, ["plan", "--link-site", "myspace"])
    assert result.exit_code == 1
    assert "unknown link site" in result.output


def test_info_command(runner: CliRunner) -> None:
    result = runner.invoke(app, ["info", "IC1396", "--config", str(EXAMPLES / "sites.yaml")])
    assert result.exit_code == 0, result.output
    assert "IC1396 Elephant Trunk" in result.output
    assert "narrowband-friendly" in result.output
    assert "mosaic 2x3" in result.output
    assert "simbad.cds.unistra.fr" in result.output
    assert "aladin.cds.unistra.fr" in result.output


def test_mosaic_command(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "panels.csv"
    result = runner.invoke(
        app,
        ["mosaic", "IC1396", "--config", str(EXAMPLES / "sites.yaml"), "--csv", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert "Grid: 2 x 3 panels" in result.output
    assert result.output.count("r1c") == 2  # 2 columns in row 1
    lines = out.read_text().splitlines()
    assert lines[0] == "panel,ra_hms,dec_dms,ra_deg,dec_deg"
    assert len(lines) == 7  # header + 6 panels


def test_mosaic_single_frame_target(runner: CliRunner) -> None:
    result = runner.invoke(app, ["mosaic", "NGC6888", "--config", str(EXAMPLES / "sites.yaml")])
    assert result.exit_code == 0, result.output
    assert "single frame" in result.output


def test_mosaic_ambiguous_query(runner: CliRunner) -> None:
    result = runner.invoke(app, ["mosaic", "Veil", "--config", str(EXAMPLES / "sites.yaml")])
    assert result.exit_code == 1
    assert "ambiguous" in result.output


def test_plan_bad_catalogs_fails(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "plan",
            "2026-08-15",
            "--config",
            str(EXAMPLES / "sites.yaml"),
            "--catalogs",
            "SHARPLESS",
            "--no-plot",
            "--csv",
            str(tmp_path / "o.csv"),
        ],
    )
    assert result.exit_code == 1
    assert "unknown catalog" in result.output


def test_sites_add_list_setdefault_remove(runner: CliRunner, tmp_path: Path) -> None:
    cfg = str(tmp_path / "sites.yaml")
    r = runner.invoke(
        app,
        ["sites", "add", "Balcony", "--lat", "41.7", "--lon", "12.9",
         "--tz", "Europe/Rome", "--config", cfg, "--default"],
    )
    assert r.exit_code == 0, r.output
    assert "balcony" in r.output  # slugified

    r = runner.invoke(
        app,
        ["sites", "add", "Mountain", "--lat", "46.5", "--lon", "11.35", "--config", cfg],
    )
    assert r.exit_code == 0, r.output

    r = runner.invoke(app, ["sites", "list", "--config", cfg])
    assert r.exit_code == 0, r.output
    assert "* balcony" in r.output  # default marked
    assert "mountain" in r.output

    r = runner.invoke(app, ["sites", "set-default", "mountain", "--config", cfg])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["sites", "list", "--config", cfg])
    assert "* mountain" in r.output

    r = runner.invoke(app, ["sites", "remove", "mountain", "--config", cfg])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["sites", "list", "--config", cfg])
    assert "* balcony" in r.output  # default fell back


def test_sites_remove_unknown_fails(runner: CliRunner, tmp_path: Path) -> None:
    cfg = str(tmp_path / "sites.yaml")
    runner.invoke(app, ["sites", "add", "a", "--lat", "1", "--lon", "2", "--config", cfg])
    r = runner.invoke(app, ["sites", "remove", "ghost", "--config", cfg])
    assert r.exit_code == 1
    assert "not found" in r.output


def test_horizon_save_site(runner: CliRunner, tmp_path: Path) -> None:
    pts = tmp_path / "pts.yaml"
    pts.write_text("declination: 0.0\npoints:\n  - [90, 20]\n  - [180, 35]\n  - [270, 15]\n")
    cfg = str(tmp_path / "sites.yaml")
    r = runner.invoke(
        app,
        ["horizon", str(pts), "--save-site", "Balcony", "--config", cfg,
         "--lat", "41.7", "--lon", "12.9", "--tz", "Europe/Rome", "--default"],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "balcony.hrz").exists()
    r = runner.invoke(app, ["sites", "list", "--config", cfg])
    assert "* balcony" in r.output
    assert "[hrz]" in r.output


def test_horizon_save_new_site_needs_coords(runner: CliRunner, tmp_path: Path) -> None:
    pts = tmp_path / "pts.yaml"
    pts.write_text("points:\n  - [90, 20]\n  - [270, 15]\n")
    cfg = str(tmp_path / "sites.yaml")
    r = runner.invoke(app, ["horizon", str(pts), "--save-site", "New", "--config", cfg])
    assert r.exit_code == 1
    assert "needs --lat and --lon" in r.output
