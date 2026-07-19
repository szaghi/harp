"""HARP - Horizon-Aware Recommender and Planner.

A CLI planner that selects deep-sky targets for an astrophotography session
from the observing date, site location, telescope+camera rig, the site's free
horizon profile, and the Moon status.
"""

from __future__ import annotations

# Version mirror — pyproject.toml is the canonical source; release.sh keeps
# both in sync.
__version__ = "0.1.5"
