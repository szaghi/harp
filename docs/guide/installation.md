# Installation

From PyPI:

```bash
pip install harp-astro
```

The distribution is `harp-astro`; the installed package and the CLI command
are plain `harp`.

From source:

```bash
git clone https://github.com/szaghi/harp
cd harp
make dev
```

## Network

HARP runs fully offline: the catalogues (Messier/NGC/IC, the Sharpless H II
regions and their size concordance), the Solar System ephemeris for the Moon
and planets, and the target web links are all built on disk with no run-time
queries.

The one exception is `harp plan --ss-moons` (major natural satellites like
Titan and the Galilean moons): it downloads a JPL satellite ephemeris on
first use and therefore needs network access. It is off by default; the
Moon-and-planets set requires nothing extra.

The vendored Sharpless data is regenerated from VizieR/SIMBAD only by the
maintainer (`pip install -e ".[catalog-build]"`, then `tools/build_*.py`) —
never at run time or on install.
