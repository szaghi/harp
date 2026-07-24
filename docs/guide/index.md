# About HARP

HARP — **H**orizon-**A**ware **R**ecommender and **P**lanner — is a CLI tool
that selects targets for an astrophotography night session.

Given the observing date, site location, telescope + camera rig, the site's
free-horizon profile, and the Moon status, HARP ranks the objects best
placed for imaging that night — and hands the result to your capture suite:
mosaic panel coordinates and N.I.N.A.-importable target lists included.

Targets span the deep sky (Messier/NGC/IC, the Sharpless H II regions, your
own objects) **and the Solar System** (the Moon and the eight planets, ranked
live alongside them). Each target is classified by nature — nebula, galaxy,
cluster, planetary nebula, star, planet, moon, sun — and can be filtered on
it.

Commands: `harp plan` (rank tonight's targets), `harp mosaic` (per-panel
coordinates), `harp info` (details on one target), `harp horizon` (build the
`.hrz` mask), `harp sites` (manage saved observing sites), `harp list` (show
configured sites/optics).

Tell HARP your sky as well as your horizon (`--bortle`, or a measured
`--sqm`) and the ranking accounts for [light
pollution](/guide/usage#light-pollution-and-target-contrast) too: it switches
from magnitude to *contrast*, so the big faint galaxies that drown in city
glow sink, while compact objects and narrowband nebulae hold their place.

Everything runs **offline** — catalogues and ephemerides ship with the
package. The only exception is `--ss-moons`, which fetches a JPL ephemeris
for the major planetary moons.

There is also an [Android companion app](/guide/android) built on the same
core, which adds two things the CLI cannot do: capturing your horizon profile
by pointing the phone at the skyline, and a
[polar-alignment assistant](/guide/usage#polar-alignment) for rough-aligning
the mount in twilight.
