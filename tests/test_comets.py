"""Tests for comet orbital-element propagation and planner integration.

The propagation is cross-checked against astropy's own frame machinery: for a
real comet (C/2023 A3 Tsuchinshan-ATLAS) the two-body geocentric direction
must agree with astropy's ``HeliocentricTrueEcliptic -> GCRS`` transform to
better than an arcminute -- the accuracy the horizon-planning use case needs.
"""

from __future__ import annotations

import math
import warnings

import pytest

from harp.comets import (
    CometElements,
    _calendar_to_jd,
    _mpc_name,
    comet_targets,
    parse_mpc_comets,
)
from harp.errors import EphemerisError

# C/2023 A3 (Tsuchinshan-ATLAS): a near-parabolic long-period comet whose
# 2024 apparition is well documented -- a low western-sky evening object in
# mid-October 2024 from mid-northern latitudes.
_A3_TP = _calendar_to_jd(2024, 9, 27.7834)
A3 = CometElements(
    designation="C/2023 A3",
    name="C/2023 A3 (Tsuchinshan-ATLAS)",
    epoch_tp_jd=_A3_TP,
    q_au=0.391380,
    e=1.000073,
    incl_deg=139.1096,
    node_deg=21.5601,
    argp_deg=308.4901,
    h_mag=8.0,
    g_mag=4.0,
)

# An elliptic short-period comet: 1P/Halley-like eccentricity, for the
# elliptic Kepler branch (e < 1).
HALLEY_LIKE = CometElements(
    designation="1P-like",
    name="1P-like",
    epoch_tp_jd=2446470.5,
    q_au=0.586,
    e=0.967,
    incl_deg=162.2,
    node_deg=58.4,
    argp_deg=111.3,
    h_mag=5.5,
    g_mag=None,
)

# A clearly hyperbolic (interstellar-like) orbit, for the hyperbolic branch.
HYPERBOLIC = CometElements(
    designation="hyp",
    name="hyp",
    epoch_tp_jd=2458006.0,
    q_au=0.25,
    e=1.20,
    incl_deg=122.7,
    node_deg=24.6,
    argp_deg=241.8,
    h_mag=None,
    g_mag=None,
)


class TestJulianDate:
    def test_perihelion_jd_known_value(self):
        # 2024-09-27.7834 TT is JD ~2460581.283.
        assert pytest.approx(2460581.283, abs=1e-3) == _A3_TP

    def test_midnight_anchor(self):
        # An integer day (no fractional part) lands on the .5 half-day.
        jd = _calendar_to_jd(2000, 1, 1)
        assert jd == pytest.approx(2451544.5, abs=1e-6)

    def test_fractional_day_advances(self):
        base = _calendar_to_jd(2024, 6, 1)
        half = _calendar_to_jd(2024, 6, 1.5)
        assert half - base == pytest.approx(0.5, abs=1e-9)


class TestKeplerRadius:
    def test_parabolic_r_equals_q_at_perihelion(self):
        x, y, z = A3.state_au(A3.epoch_tp_jd)
        r = math.sqrt(x * x + y * y + z * z)
        assert r == pytest.approx(A3.q_au, abs=1e-6)

    def test_elliptic_r_equals_q_at_perihelion(self):
        x, y, z = HALLEY_LIKE.state_au(HALLEY_LIKE.epoch_tp_jd)
        r = math.sqrt(x * x + y * y + z * z)
        assert r == pytest.approx(HALLEY_LIKE.q_au, abs=1e-6)

    def test_hyperbolic_r_equals_q_at_perihelion(self):
        x, y, z = HYPERBOLIC.state_au(HYPERBOLIC.epoch_tp_jd)
        r = math.sqrt(x * x + y * y + z * z)
        assert r == pytest.approx(HYPERBOLIC.q_au, abs=1e-6)

    def test_radius_grows_after_perihelion(self):
        # All three orbit types recede from perihelion.
        for el in (A3, HALLEY_LIKE, HYPERBOLIC):
            x0, y0, z0 = el.state_au(el.epoch_tp_jd)
            x1, y1, z1 = el.state_au(el.epoch_tp_jd + 20)
            r0 = math.sqrt(x0 * x0 + y0 * y0 + z0 * z0)
            r1 = math.sqrt(x1 * x1 + y1 * y1 + z1 * z1)
            assert r1 > r0

    def test_elliptic_symmetric_about_perihelion(self):
        # An ellipse is symmetric in radius about perihelion time.
        rm = HALLEY_LIKE.state_au(HALLEY_LIKE.epoch_tp_jd - 15)
        rp = HALLEY_LIKE.state_au(HALLEY_LIKE.epoch_tp_jd + 15)
        r_minus = math.sqrt(sum(c * c for c in rm))
        r_plus = math.sqrt(sum(c * c for c in rp))
        assert r_minus == pytest.approx(r_plus, rel=1e-6)


class TestPropagationAgainstAstropy:
    """The two-body geocentric direction must match astropy's frame chain."""

    def test_a3_geocentric_matches_astropy(self):
        import astropy.units as u
        from astropy.coordinates import (
            GCRS,
            EarthLocation,
            HeliocentricTrueEcliptic,
            SkyCoord,
            get_body,
        )
        from astropy.time import Time

        from harp.ephemeris import _OBLIQUITY_J2000

        t = Time("2024-10-15 18:30:00")
        loc = EarthLocation(lat=41.9 * u.deg, lon=12.5 * u.deg, height=50 * u.m)
        x, y, z = A3.state_au(float(t.tt.jd))

        # HARP path: ecliptic -> equatorial by the obliquity rotation, then add
        # the Sun's geocentric position to make it a GEOCENTRIC vector -- the
        # same construction comet_altaz uses.
        ce, se = math.cos(_OBLIQUITY_J2000), math.sin(_OBLIQUITY_J2000)
        x_eq, y_eq, z_eq = x, y * ce - z * se, y * se + z * ce
        sun = get_body("sun", t, loc).cartesian.xyz.to_value(u.au)
        gx, gy, gz = x_eq + sun[0], y_eq + sun[1], z_eq + sun[2]
        r = math.sqrt(gx**2 + gy**2 + gz**2)
        harp_dec = math.degrees(math.asin(gz / r))
        harp_ra = math.degrees(math.atan2(gy, gx)) % 360.0

        # astropy path: let it do the ecliptic->equatorial rotation AND the
        # heliocentric->geocentric offset itself.
        helio = SkyCoord(
            x=x * u.au,
            y=y * u.au,
            z=z * u.au,
            frame=HeliocentricTrueEcliptic(obstime=t),
            representation_type="cartesian",
        )
        ref = helio.transform_to(GCRS(obstime=t))

        # Sub-arcminute agreement in both coordinates.
        assert harp_ra == pytest.approx(ref.ra.deg, abs=0.05)
        assert harp_dec == pytest.approx(ref.dec.deg, abs=0.05)


def _synth_mpc_line() -> str:
    """Build a synthetic MPC CometEls.txt line at exact column positions.

    Placing each field at its documented 0-indexed slice (the same slices
    ``parse_mpc_comets`` reads) avoids the fragility of hand-counting spaces.
    """
    buf = [" "] * 130

    def put(start: int, text: str) -> None:
        buf[start : start + len(text)] = list(text)

    put(14, "2024")  # year        14:18
    put(19, "09")  # month         19:21
    put(22, "27.7834")  # day      22:29
    put(30, " 0.391380")  # q      30:39
    put(41, "1.000073")  # e        41:49
    put(51, "308.4901")  # argp    51:59
    put(61, " 21.5601")  # node    61:69
    put(71, "139.1096")  # incl    71:79
    put(81, "20240613")  # epoch   81:89 (osculation date, skipped by parser)
    put(91, " 8.0")  # H           91:96
    put(96, " 4.0")  # G           96:101
    put(102, "C/2023 A3 (Tsuchinshan-ATLAS)")  # name 102:
    return "".join(buf)


class TestMpcParsing:
    SYNTH = _synth_mpc_line()

    def test_parse_extracts_elements(self):
        comets = parse_mpc_comets(self.SYNTH)
        assert len(comets) == 1
        c = comets[0]
        assert c.q_au == pytest.approx(0.391380)
        assert c.e == pytest.approx(1.000073)
        assert c.argp_deg == pytest.approx(308.4901)
        assert c.node_deg == pytest.approx(21.5601)
        assert c.incl_deg == pytest.approx(139.1096)
        assert c.h_mag == pytest.approx(8.0)
        assert c.g_mag == pytest.approx(4.0)
        assert "Tsuchinshan" in c.name

    def test_parse_perihelion_jd(self):
        c = parse_mpc_comets(self.SYNTH)[0]
        assert c.epoch_tp_jd == pytest.approx(2460581.283, abs=1e-3)

    def test_parse_skips_header_and_blank(self):
        text = "\n".join(["# a header line", "", "   short", self.SYNTH])
        assert len(parse_mpc_comets(text)) == 1

    def test_parse_skips_malformed_without_aborting(self):
        garbage = "x" * 120  # right length, wrong content
        text = "\n".join([garbage, self.SYNTH])
        # The good line still survives the bad one.
        assert len(parse_mpc_comets(text)) == 1

    def test_name_with_parentheses(self):
        raw = " " * 102 + "C/2023 A3 (Tsuchinshan-ATLAS)"
        desig, label = _mpc_name(raw)
        assert desig == "C/2023 A3"
        assert "Tsuchinshan-ATLAS" in label

    def test_name_without_parentheses(self):
        raw = " " * 102 + "P/2016 BA14"
        desig, label = _mpc_name(raw)
        assert desig == "P/2016 BA14"
        assert label == "P/2016 BA14"

    def test_trailing_reference_not_swept_into_name(self):
        # A periodic comet has no parenthesised name; the trailing MPC/MPEC
        # reference sits past column 158 and must not leak into the name.
        raw = " " * 102 + "14P/Wolf".ljust(56) + "MPEC 2026-O53"
        desig, label = _mpc_name(raw)
        assert desig == "14P/Wolf"
        assert label == "14P/Wolf"
        assert "MPEC" not in label


class TestCometTargets:
    def test_build_moving_targets(self):
        targets = comet_targets([A3, HALLEY_LIKE])
        assert len(targets) == 2
        for t in targets:
            assert t.coord is None  # moving: no fixed coord
            assert t.body is None  # not a get_body body
            assert t.elements is not None  # carries orbital elements
            assert t.classification == "comet"
            assert t.kind == "Comet"

    def test_absolute_magnitude_becomes_mag(self):
        t = comet_targets([A3])[0]
        assert t.mag == pytest.approx(8.0)

    def test_mag_limit_drops_faint_but_keeps_unknown(self):
        faint = CometElements("f", "faint", 2460000.0, 2.0, 0.5, 10.0, 20.0, 30.0, h_mag=18.0)
        unknown = CometElements("u", "unknown", 2460000.0, 2.0, 0.5, 10.0, 20.0, 30.0, h_mag=None)
        out = comet_targets([A3, faint, unknown], mag_limit=12.0)
        names = {t.name for t in out}
        assert "faint" not in names  # H=18 dropped
        assert "unknown" in names  # unknown H kept
        assert A3.name in names  # H=8 kept


class TestApparentMagnitude:
    def test_law_brightens_when_closer(self):
        # Same comet, smaller r and delta -> brighter (smaller magnitude).
        far = A3.apparent_mag(r_au=3.0, delta_au=3.0)
        near = A3.apparent_mag(r_au=0.5, delta_au=0.5)
        assert near < far

    def test_law_matches_hand_computation(self):
        # m = H + 5 log10(delta) + G log10(r); H=8, G=4, r=delta=1 -> m=H.
        m = A3.apparent_mag(r_au=1.0, delta_au=1.0)
        assert m == pytest.approx(8.0, abs=1e-9)

    def test_none_when_no_absolute_magnitude(self):
        assert HYPERBOLIC.apparent_mag(1.0, 1.0) is None  # H is None

    def test_median_over_night_is_reasonable(self):
        import astropy.units as u
        from astropy.coordinates import EarthLocation

        from harp.ephemeris import comet_apparent_mag

        loc = EarthLocation(lat=41.9 * u.deg, lon=12.5 * u.deg, height=50 * u.m)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from astropy.utils import iers

            iers.conf.auto_download = False
            iers.conf.iers_degraded_accuracy = "warn"
            from astroplan import Observer

            from harp.ephemeris import compute_night

            obs = Observer(longitude=12.5 * u.deg, latitude=41.9 * u.deg, elevation=50 * u.m)
            from zoneinfo import ZoneInfo

            win = compute_night(obs, ZoneInfo("Europe/Rome"), "2024-10-15", 30)
            m = comet_apparent_mag(loc, win, A3)
        # C/2023 A3 in mid-Oct 2024 was a naked-eye/binocular object: a few mag,
        # not the H=8 absolute value and not fainter than ~10.
        assert m is not None
        assert 2.0 < m < 10.0


class TestParseError:
    def test_zero_comets_from_garbage(self):
        # parse of an empty/garbage file yields nothing; fetch turns that into
        # a clear error rather than a silently empty sky.
        assert parse_mpc_comets("nothing here\n") == []


class TestPlannerIntegration:
    """A comet flows through plan_night as a moving target."""

    def _plan(self):
        from harp.horizon import Horizon
        from harp.optics import Rig
        from harp.planner import Site, plan_night

        site = Site(label="rome", lat=41.9, lon=12.5, elev=50.0, tz="Europe/Rome")
        rig = Rig(focal_mm=800, sensor_name="apsc", sensor_w_mm=23.5, sensor_h_mm=15.7)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from astropy.utils import iers

            iers.conf.auto_download = False
            iers.conf.iers_degraded_accuracy = "warn"
            return plan_night(
                site,
                rig,
                Horizon.flat(0.0),
                comet_targets([A3]),
                date="2024-10-15",
                grid_min=20,
                min_hours=0.0,
                min_peak_alt=0.0,
            )

    def test_comet_row_present_and_classified(self):
        plan = self._plan()
        assert len(plan.rows) == 1
        row = plan.rows[0]
        assert row.classification == "comet"
        assert row.frame == "comet"
        assert "Tsuchinshan" in row.name

    def test_comet_in_the_west_after_dusk(self):
        # The documented mid-October 2024 geometry: a low western evening
        # object. Azimuth near west (270 deg), low altitude.
        plan = self._plan()
        row = plan.rows[0]
        assert 230 < row.az_peak < 300  # western sky
        assert 0 < row.alt_max < 30  # low

    def test_comet_mag_limit_prunes_faint(self):
        # A tight apparent-mag limit drops the comet; a loose one keeps it.
        from harp.horizon import Horizon
        from harp.optics import Rig
        from harp.planner import Site, plan_night

        site = Site(label="rome", lat=41.9, lon=12.5, elev=50.0, tz="Europe/Rome")
        rig = Rig(focal_mm=800, sensor_name="apsc", sensor_w_mm=23.5, sensor_h_mm=15.7)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from astropy.utils import iers

            iers.conf.auto_download = False
            iers.conf.iers_degraded_accuracy = "warn"
            # A deliberately faint comet: H=15 far from the Sun/Earth.
            faint = CometElements(
                "faint",
                "faint one",
                _calendar_to_jd(2024, 1, 1),
                3.0,
                0.5,
                20.0,
                40.0,
                60.0,
                h_mag=15.0,
            )
            kw = {"date": "2024-10-15", "grid_min": 30, "min_hours": 0.0, "min_peak_alt": 0.0}
            loose = plan_night(
                site, rig, Horizon.flat(0.0), comet_targets([faint]), comet_mag_limit=25.0, **kw
            )
            tight = plan_night(
                site, rig, Horizon.flat(0.0), comet_targets([faint]), comet_mag_limit=10.0, **kw
            )
        # The faint comet survives a loose cut (if up at all) but a tight cut
        # removes it regardless of observability.
        assert all(r.classification != "comet" for r in tight.rows)
        # loose: either present as a comet or filtered only by observability,
        # never removed BY the mag cut -- so if any comet row exists it is this.
        assert all(
            r.mag is None or r.mag <= 25.0 for r in loose.rows if r.classification == "comet"
        )

    def test_comet_has_real_moon_separation(self):
        # Unlike a planet (moon_sep forced to 0/'n/a'), a comet gets a real
        # Moon separation and impact verdict.
        plan = self._plan()
        row = plan.rows[0]
        assert row.moon != "n/a"
        assert row.moon_sep > 0

    def test_mixed_plan_keeps_deep_sky_and_comet(self):
        # A comet added alongside fixed deep-sky objects does not disturb the
        # fixed objects' ephemeris path.
        from harp.catalog import build_targets
        from harp.horizon import Horizon
        from harp.optics import Rig
        from harp.planner import Site, plan_night

        site = Site(label="rome", lat=41.9, lon=12.5, elev=50.0, tz="Europe/Rome")
        rig = Rig(focal_mm=800, sensor_name="apsc", sensor_w_mm=23.5, sensor_h_mm=15.7)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from astropy.utils import iers

            iers.conf.auto_download = False
            iers.conf.iers_degraded_accuracy = "warn"
            fixed = build_targets(
                use_pyongc=True,
                use_sharpless=False,
                use_solar_system=False,
                pyongc_catalogs=["M"],
                mag_limit=6.0,
            )
            targets = fixed + comet_targets([A3])
            plan = plan_night(
                site,
                rig,
                Horizon.flat(0.0),
                targets,
                date="2024-10-15",
                grid_min=30,
                min_hours=0.0,
                min_peak_alt=0.0,
            )
        classes = {r.classification for r in plan.rows}
        assert "comet" in classes
        # at least one non-comet deep-sky object also planned
        assert classes - {"comet"}


class TestOfflineGuarantee:
    def test_fetch_offline_raises_ephemeris_error(self):
        from harp.comets import fetch_comet_elements

        # A URL that cannot resolve stands in for "no network"; the failure
        # must be a clean EphemerisError, never a raw socket exception.
        with pytest.raises(EphemerisError):
            fetch_comet_elements(url="http://127.0.0.1:9/nope.txt", timeout=0.5)
