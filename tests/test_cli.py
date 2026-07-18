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
        header == "object,kind,const,mag,hours,cont,window,altmax,az,peak,moonsep,moon,frame,detail"
    )
    # August night from the balcony: Cygnus/Cepheus nebulae must be in
    assert "IC1396 Elephant Trunk" in result.output
