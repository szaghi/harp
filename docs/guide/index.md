# About HARP

HARP — **H**orizon-**A**ware **R**ecommender and **P**lanner — is a CLI tool
that selects targets for an astrophotography night session.

Given the observing date, site location, telescope + camera rig, the site's
free-horizon profile, and the Moon status, HARP ranks the objects best
placed for imaging that night — and hands the result to your capture suite:
mosaic panel coordinates and N.I.N.A.-importable target lists included.

Targets span the deep sky (curated nebulae, Messier/NGC/IC, your own
objects) **and the Solar System** (the Moon and the eight planets, ranked
live alongside them). Each target is classified by nature — nebula, galaxy,
cluster, planetary nebula, star, planet, moon, sun — and can be filtered on
it.

Commands: `harp plan` (rank tonight's targets), `harp mosaic` (per-panel
coordinates), `harp info` (details on one target), `harp horizon` (build the
`.hrz` mask), `harp list` (show configured sites/optics).
