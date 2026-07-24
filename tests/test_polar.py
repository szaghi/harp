"""Tests for polar-alignment geometry.

The position-angle tests deliberately check against astropy's own
``position_angle`` computed in the ``AltAz`` frame rather than against
hand-copied constants. The reticle angle is exactly the kind of quantity that
can be 180 degrees wrong while looking entirely plausible, so the oracle has
to be independent of the implementation's own reasoning.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import astropy.units as u
import pytest
from astropy.coordinates import FK5, AltAz, EarthLocation, SkyCoord
from astropy.time import Time

from harp.errors import EphemerisError
from harp.polar import (
    MOUNTS,
    polaris_hour_angle,
    polaris_pole_separation,
    pole_star,
    refracted_pole_altitude,
    reticle_position,
)

ROME = (41.9, 12.5)
SYDNEY = (-33.9, 151.2)
T2026 = datetime(2026, 7, 23, 22, 0, 0, tzinfo=UTC)
T2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)


def _astropy_reticle_angle(when_utc: datetime, lat: float, lon: float) -> float:
    """Independent oracle: PA of the pole star about the pole, in AltAz."""
    t = Time(when_utc)
    eq = FK5(equinox=t)
    aa = AltAz(obstime=t, location=EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=0 * u.m))
    pole_dec = 90.0 if lat >= 0 else -90.0
    pole = SkyCoord(ra=0 * u.deg, dec=pole_dec * u.deg, frame=eq).transform_to(aa)
    star = pole_star(lat).transform_to(eq).transform_to(aa)
    return float(pole.position_angle(star).deg)


def _angdiff(a: float, b: float) -> float:
    """Smallest absolute difference between two angles, degrees."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


class TestRefraction:
    @pytest.mark.parametrize(
        ("lat", "arcmin"),
        [(20.0, 2.7), (42.0, 1.1), (52.0, 0.8), (65.0, 0.5)],
    )
    def test_bennett_magnitudes(self, lat: float, arcmin: float) -> None:
        """Refraction lifts the pole by the expected arcminutes."""
        lift = (refracted_pole_altitude(lat) - lat) * 60.0
        assert lift == pytest.approx(arcmin, abs=0.05)

    def test_always_lifts(self) -> None:
        """Refraction is one-sided: the apparent pole is never lower."""
        for lat in range(-89, 90, 7):
            assert refracted_pole_altitude(float(lat)) >= abs(float(lat))

    def test_uses_absolute_latitude(self) -> None:
        """Southern latitudes refract like their northern mirror."""
        assert refracted_pole_altitude(-42.0) == pytest.approx(refracted_pole_altitude(42.0))

    def test_vacuum_disables(self) -> None:
        """Zero pressure means no atmosphere, hence the geometric pole."""
        assert refracted_pole_altitude(42.0, pressure_hpa=0.0) == 42.0

    def test_denser_air_refracts_more(self) -> None:
        """Higher pressure and colder air bend light further."""
        warm = refracted_pole_altitude(42.0, pressure_hpa=1010.0, temp_c=30.0)
        cold = refracted_pole_altitude(42.0, pressure_hpa=1010.0, temp_c=-10.0)
        low = refracted_pole_altitude(42.0, pressure_hpa=900.0)
        high = refracted_pole_altitude(42.0, pressure_hpa=1030.0)
        assert cold > warm
        assert high > low

    def test_rejects_impossible_latitude(self) -> None:
        with pytest.raises(EphemerisError, match="latitude out of range"):
            refracted_pole_altitude(91.0)


class TestSeparation:
    def test_apparent_separation_2026(self) -> None:
        """Precessed separation, not the 44.2' J2000 catalogue value."""
        assert polaris_pole_separation(T2026) == pytest.approx(37.6, abs=0.2)

    def test_j2000_separation(self) -> None:
        """At J2000 the apparent value collapses to the catalogue one."""
        assert polaris_pole_separation(T2000) == pytest.approx(44.2, abs=0.2)

    def test_closing_toward_2100(self) -> None:
        """Polaris approaches the pole through the 21st century."""
        seps = [
            polaris_pole_separation(datetime(y, 1, 1, tzinfo=UTC)) for y in (2000, 2026, 2050, 2075)
        ]
        assert seps == sorted(seps, reverse=True)

    def test_southern_star_is_far_worse(self) -> None:
        """Sigma Octantis sits about a degree from the south pole."""
        sep = polaris_pole_separation(T2026, lat_deg=SYDNEY[0])
        assert 50.0 < sep < 75.0

    def test_matches_astropy_separation(self) -> None:
        """Cross-check against astropy's own separation to the pole of date."""
        t = Time(T2026)
        eq = FK5(equinox=t)
        pole = SkyCoord(ra=0 * u.deg, dec=90 * u.deg, frame=eq)
        star = pole_star(ROME[0]).transform_to(eq)
        assert polaris_pole_separation(T2026) == pytest.approx(
            float(pole.separation(star).arcmin), abs=0.05
        )


class TestOfflineIers:
    def test_out_of_range_date_does_not_raise(self) -> None:
        """A date past the bundled IERS table degrades, it does not crash.

        Reproduces the on-device IERSRangeError: the Android build ships an
        IERS-B table that a plan a few months ahead can outrun, and astropy's
        default 'error' policy makes sidereal_time raise. reticle_position must
        flip the policy to 'warn' and compute anyway. Force 'error' first so
        the recovery is what is actually being tested.
        """
        from astropy.utils import iers

        iers.conf.iers_degraded_accuracy = "error"
        try:
            future = datetime(2035, 6, 1, 22, tzinfo=UTC)
            fix = reticle_position(future, *ROME, mount="skywatcher")
            assert 0.0 <= fix.reticle_angle_deg < 360.0
            assert fix.separation_arcmin > 0.0
        finally:
            iers.conf.iers_degraded_accuracy = "error"


class TestHourAngle:
    def test_matches_lst_minus_ra(self) -> None:
        """HA is local sidereal time minus the star's apparent RA."""
        lat, lon = ROME
        t = Time(T2026)
        ra = pole_star(lat).transform_to(FK5(equinox=t)).ra.deg
        lst = t.sidereal_time("apparent", longitude=lon * u.deg).deg
        assert polaris_hour_angle(T2026, lon, lat_deg=lat) == pytest.approx((lst - ra) % 360.0)

    def test_in_range(self) -> None:
        for h in range(0, 24, 3):
            ha = polaris_hour_angle(T2026 + timedelta(hours=h), ROME[1])
            assert 0.0 <= ha < 360.0

    def test_advances_with_sidereal_time(self) -> None:
        """One sidereal day returns the star to the same hour angle."""
        a = polaris_hour_angle(T2026, ROME[1])
        b = polaris_hour_angle(T2026 + timedelta(hours=23, minutes=56, seconds=4), ROME[1])
        assert _angdiff(a, b) < 0.2

    def test_eastward_longitude_increases_ha(self) -> None:
        """A site 15 deg east sees the star one hour further west."""
        a = polaris_hour_angle(T2026, 0.0)
        b = polaris_hour_angle(T2026, 15.0)
        assert _angdiff((a + 15.0) % 360.0, b) < 0.01


class TestReticlePosition:
    @pytest.mark.parametrize("hours", [0, 3, 6, 9, 12, 15, 18, 21])
    def test_north_angle_matches_astropy(self, hours: int) -> None:
        """The raw angle tracks astropy's AltAz position angle exactly.

        This is the test that catches a 180-degree reticle error.
        """
        when = T2026 + timedelta(hours=hours)
        lat, lon = ROME
        fix = reticle_position(when, lat, lon, mount="generic")
        assert _angdiff(fix.position_angle_deg, _astropy_reticle_angle(when, lat, lon)) < 0.05

    @pytest.mark.parametrize("hours", [0, 4, 8, 12, 16, 20])
    def test_south_angle_matches_astropy(self, hours: int) -> None:
        """Southern hemisphere reverses the sense; verify, do not assume."""
        when = T2026 + timedelta(hours=hours)
        lat, lon = SYDNEY
        fix = reticle_position(when, lat, lon, mount="generic")
        assert _angdiff(fix.position_angle_deg, _astropy_reticle_angle(when, lat, lon)) < 0.05

    def test_hemispheres_have_opposite_sense(self) -> None:
        """North uses -HA, south +HA -- they must not share a sign."""
        north = reticle_position(T2026, ROME[0], ROME[1])
        south = reticle_position(T2026, SYDNEY[0], SYDNEY[1])
        assert north.position_angle_deg == pytest.approx((-north.hour_angle_deg) % 360.0, abs=1e-6)
        assert south.position_angle_deg == pytest.approx(south.hour_angle_deg % 360.0, abs=1e-6)

    def test_angle_rotates_over_the_night(self) -> None:
        """The mark must move; a constant angle means an equatorial-PA bug."""
        angles = [
            reticle_position(T2026 + timedelta(hours=h), ROME[0], ROME[1]).position_angle_deg
            for h in (0, 2, 4, 6)
        ]
        assert max(_angdiff(a, angles[0]) for a in angles[1:]) > 20.0

    def test_generic_mount_is_untransformed(self) -> None:
        """'generic' reports astronomical truth with no mount convention."""
        fix = reticle_position(T2026, ROME[0], ROME[1], mount="generic")
        assert fix.reticle_angle_deg == pytest.approx(fix.position_angle_deg)

    def test_mirrored_mount_flips_angle(self) -> None:
        """A mirror-reversed field negates the drawn angle."""
        raw = reticle_position(T2026, ROME[0], ROME[1], mount="generic")
        sw = reticle_position(T2026, ROME[0], ROME[1], mount="skywatcher")
        assert sw.reticle_angle_deg == pytest.approx((-raw.position_angle_deg) % 360.0)
        assert sw.mount.mirrored

    def test_carries_refracted_altitude(self) -> None:
        """The altitude to set is the refracted pole, above bare latitude."""
        fix = reticle_position(T2026, ROME[0], ROME[1])
        assert fix.pole_altitude_deg == pytest.approx(refracted_pole_altitude(ROME[0]))
        assert fix.pole_altitude_deg > ROME[0]

    def test_unknown_mount_rejected(self) -> None:
        with pytest.raises(EphemerisError, match="unknown mount convention"):
            reticle_position(T2026, ROME[0], ROME[1], mount="nonesuch")

    def test_only_verified_mounts_claim_verification(self) -> None:
        """Unverified vendor presets stay flagged so the UI can caveat them."""
        assert MOUNTS["generic"].verified
        assert MOUNTS["skywatcher"].verified
        assert not MOUNTS["ioptron"].verified
        assert not MOUNTS["celestron"].verified


class TestClockString:
    def test_clock_matches_angle(self) -> None:
        """12 h maps onto 360 deg; 0 deg reads as 12:00, not 00:00."""
        fix = reticle_position(T2026, ROME[0], ROME[1])
        hh, mm = (int(x) for x in fix.clock.split(":"))
        assert 1 <= hh <= 12
        assert 0 <= mm < 60
        minutes = (hh % 12) * 60 + mm
        assert _angdiff(minutes / 720.0 * 360.0, fix.reticle_angle_deg) < 0.5
