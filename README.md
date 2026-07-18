<div align="center">

# HARP

#### *image the sky your balcony can actually see*

### **H**orizon-**A**ware **R**ecommender and **P**lanner

> A CLI planner for deep-sky astrophotography sessions. Given a date, a site, your
> telescope + camera, the **real horizon of your spot** and the Moon, HARP ranks the
> targets you can actually image tonight — usable windows, Moon impact, and mosaic
> framing tailored to your rig.

[![Version](https://img.shields.io/pypi/v/harp?label=version)](https://pypi.org/project/harp/)
[![CI](https://github.com/szaghi/harp/actions/workflows/ci.yml/badge.svg)](https://github.com/szaghi/harp/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![GitHub issues](https://img.shields.io/github/issues/szaghi/harp.svg)](https://github.com/szaghi/harp/issues)

[![License: GPL v3](https://img.shields.io/badge/license-GPL%20v3-blue)](licensing/LICENSE.gpl3.md)
[![License: BSD-2](https://img.shields.io/badge/license-BSD--2--Clause-blue)](licensing/LICENSE.bsd-2.md)
[![License: BSD-3](https://img.shields.io/badge/license-BSD--3--Clause-blue)](licensing/LICENSE.bsd-3.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](licensing/LICENSE.mit.md)

<div>
<table>
<tr>
<td><b>🧱 Horizon-aware visibility</b><br><sub>Measure your site's obstructions once as an azimuth-dependent mask (<code>.hrz</code>, N.I.N.A.-compatible). A target counts as observable only when its altitude clears the ridge/wall <em>in its own direction</em> — not against an idealized flat horizon. <a href="https://szaghi.github.io/harp/guide/usage#build-a-horizon-file">Horizon guide</a></sub></td>
<td><b>⏱️ Continuous imaging windows</b><br><sub>Per target: total usable hours during astronomical darkness plus the longest <em>continuous</em> run before it enters a blocked sector — the number you actually size exposures and mosaic panels on. <a href="https://szaghi.github.io/harp/guide/usage#reading-the-output">Reading the output</a></sub></td>
</tr>
<tr>
<td><b>🌙 Moon impact model</b><br><sub>Phase and minimum separation folded into a per-target verdict — <code>none</code>, <code>ok(NB)</code>, <code>low/med/high</code> — narrowband-aware, because an Hα nebula through a dual-band filter shrugs at a Moon that ruins broadband RGB. </sub></td>
<td><b>🖼️ Rig-aware framing</b><br><sub>Field of view from your focal length + sensor decides <code>1 frame</code> or <code>mosaic NxM</code> (15% overlap) — and for oversized nebulae HARP suggests the interesting single-frame crop (the Cygnus Wall, the Elephant's Trunk, Melotte 15…).</sub></td>
</tr>
<tr>
<td><b>🔭 Offline catalogues</b><br><sub>A curated list of large emission nebulae — deliberately <em>not</em> magnitude-filtered, because surface brightness matters and integrated magnitudes are often absent — plus Messier/NGC/IC via <a href="https://github.com/mattiaverga/PyOngc">pyongc</a>. No network at run time.</sub></td>
<td><b>📈 Table, CSV, charts</b><br><sub>A ranked terminal table, a CSV for your session log, and altitude charts with the horizon obstruction band and the usable window overlaid — one command, three artifacts. </sub></td>
</tr>
</table>
</div>

**[Full documentation](https://szaghi.github.io/harp/)** — installation, usage, horizon measuring, configuration

</div>

---

## What HARP does

```bash
harp plan                                    # tonight, default site/optics from config
harp plan 2026-08-15 --site balcony --optics newton800
harp list                                    # sites and optics defined in the config
harp horizon points.yaml -o balcony.hrz      # measured vertices -> .hrz horizon file
```

```
=== Night 2026-08-15 | Castelli Balcony 41.7380,12.8899 ===
Astronomical darkness: 21:53 -> 04:32 local
Moon: ~12% illuminated  |  above horizon: below horizon all night
Setup: 800 mm + custom 23.5x15.7
Field of view: 101' x 67'  |  horizon: balcony.hrz

 # object                kind       const   hrs cont       window altMx   az moonSep   Moon  frame
--------------------------------------------------------------------------------------------------
 1 Sh2-171 NGC7822       Nebula     Cep     6.7  6.7  21:53-04:28    64    0     117   none  1 frame
 2 IC1805 Heart          Nebula     Cas     6.7  6.7  21:53-04:28    65   28     116   none  mosaic 2x3
 3 IC1848 Soul           Nebula     Cas     6.7  6.7  21:53-04:28    64   34     115   none  mosaic 2x2
 4 NGC281 Pacman         Nebula     Cas     6.7  6.7  21:53-04:28    75    0     127   none  1 frame
 5 IC59/63 Ghost of Cas  Nebula     Cas     6.7  6.7  21:53-04:28    71  360     122   none  1 frame
```

![Altitude charts](examples/altitude_charts.example.png)

The typical flow: **measure the horizon once → generate the `.hrz` → load it in
N.I.N.A. and in HARP** to plan every session from that spot. See
[`examples/`](examples/) for a working config, horizon file, and sample outputs.

## The name

A *harp* is the celestial Lyre — the constellation **Lyra**, home of Vega and the
Ring Nebula. And the acronym leads with the input most planners ignore: your
horizon.

## Installation

```bash
pip install harp
```

From source:

```bash
git clone https://github.com/szaghi/harp
cd harp
make dev
```

## Configuration

Sites (position + `.hrz` + timezone) and optical setups (focal + sensor) live in
`sites.yaml`, searched in the current directory and `~/.config/harp/`.
Precedence: **CLI option > config value > built-in default**. Details in the
[usage guide](https://szaghi.github.io/harp/guide/usage).

## Development

```bash
make dev     # editable install with dev extras into .venv
make test    # pytest with coverage
make lint    # ruff check + format check (read-only)
make fmt     # ruff auto-fix + format
```

Releases: `./release.sh --major|--minor|--patch|X.Y.Z` (trunk model on `main`;
tag push triggers CI → PyPI).

## Authors

**Stefano Zaghi** ([@szaghi](https://github.com/szaghi))
>HPC/CFD researcher by day, balcony astrophotographer by night. Owns a Newton 200/800 f/4 and a balcony whose entire southern hemisphere is a wall. Measured the horizon with a phone compass while fending off a magnetized railing, then wrote a planner rather than accept that M8 belongs to the neighbours.

**Claude** ([Anthropic](https://www.anthropic.com))
>Large language model, second author, zero telescopes. Has never seen the night sky — or anything else — yet computed where the Moon would be at 03:46 and was right. Refactored the whole toolkit between dusk and dawn, no coffee involved; accepts payment in tokens and byte-identical CSVs.

## License

Multi-licensed under GPL-3.0-or-later, BSD-2-Clause, BSD-3-Clause, and MIT —
choose the one that fits your use. See [`licensing/`](licensing/).
