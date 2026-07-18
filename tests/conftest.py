"""Shared fixtures for the HARP test suite."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    """A Typer CLI runner for invoking ``harp`` commands in-process."""
    return CliRunner()
