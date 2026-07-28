"""Tests for :mod:`harp.exposure`."""

from __future__ import annotations

import math

import pytest

from harp.errors import HarpError
from harp.exposure import (
    ExposureError,
    SensorSpec,
    frames_for_integration,
    npf_max_seconds,
    recommend_iso,
    sky_limited_seconds,
)

# The Pixel 7 Pro main camera, the device the Shoot tab targets: 25 mm
# equivalent at f/1.9 with 2.4 um binned pixels, analog gain topping out at 744.
PIXEL7PRO = SensorSpec(
    focal_mm=25.0,
    f_number=1.9,
    pixel_pitch_um=2.4,
    iso_min=48,
    iso_max=1142,
    max_analog_iso=744,
)


class TestSensorSpec:
    def test_rejects_nonpositive_focal(self) -> None:
        with pytest.raises(ExposureError, match="focal length"):
            SensorSpec(focal_mm=0.0, f_number=2.0, pixel_pitch_um=2.4)

    def test_rejects_nonpositive_f_number(self) -> None:
        with pytest.raises(ExposureError, match="f-number"):
            SensorSpec(focal_mm=25.0, f_number=-1.0, pixel_pitch_um=2.4)

    def test_rejects_nonpositive_pitch(self) -> None:
        with pytest.raises(ExposureError, match="pixel pitch"):
            SensorSpec(focal_mm=25.0, f_number=2.0, pixel_pitch_um=0.0)

    def test_rejects_inverted_iso_range(self) -> None:
        with pytest.raises(ExposureError, match="below iso_min"):
            SensorSpec(focal_mm=25.0, f_number=2.0, pixel_pitch_um=2.4, iso_min=800, iso_max=100)

    def test_errors_are_harp_errors(self) -> None:
        # The project contract: every raised type descends from HarpError.
        with pytest.raises(HarpError):
            SensorSpec(focal_mm=-1.0, f_number=2.0, pixel_pitch_um=2.4)

    def test_usable_max_iso_stops_at_analog_ceiling(self) -> None:
        assert PIXEL7PRO.usable_max_iso == 744

    def test_usable_max_iso_without_analog_ceiling(self) -> None:
        s = SensorSpec(focal_mm=25.0, f_number=2.0, pixel_pitch_um=2.4, iso_max=3200)
        assert s.usable_max_iso == 3200

    def test_analog_ceiling_above_iso_max_is_clamped(self) -> None:
        s = SensorSpec(
            focal_mm=25.0,
            f_number=2.0,
            pixel_pitch_um=2.4,
            iso_max=800,
            max_analog_iso=4000,
        )
        assert s.usable_max_iso == 800


class TestNpf:
    def test_matches_hand_computed_value(self) -> None:
        # (35 * 1.9 + 30 * 2.4) / (25 * cos 0) = 138.5 / 25 = 5.54 s
        assert npf_max_seconds(PIXEL7PRO, 0.0) == pytest.approx(5.54, abs=0.01)

    def test_grows_away_from_the_equator(self) -> None:
        # cos(60 deg) = 0.5, so the limit exactly doubles.
        equator = npf_max_seconds(PIXEL7PRO, 0.0)
        assert npf_max_seconds(PIXEL7PRO, 60.0) == pytest.approx(2 * equator, rel=1e-6)

    def test_symmetric_in_declination_sign(self) -> None:
        assert npf_max_seconds(PIXEL7PRO, 45.0) == pytest.approx(npf_max_seconds(PIXEL7PRO, -45.0))

    def test_finite_at_the_pole(self) -> None:
        # cos(90) is zero; without the floor this divides by zero.
        v = npf_max_seconds(PIXEL7PRO, 90.0)
        assert math.isfinite(v)
        assert v > 0

    def test_longer_focal_length_shortens_the_limit(self) -> None:
        short = SensorSpec(focal_mm=25.0, f_number=2.0, pixel_pitch_um=2.4)
        tele = SensorSpec(focal_mm=200.0, f_number=2.0, pixel_pitch_um=2.4)
        assert npf_max_seconds(tele) < npf_max_seconds(short)

    def test_finer_pixels_shorten_the_limit(self) -> None:
        # The whole reason NPF beats the 500 rule on phones.
        coarse = SensorSpec(focal_mm=25.0, f_number=2.0, pixel_pitch_um=6.0)
        fine = SensorSpec(focal_mm=25.0, f_number=2.0, pixel_pitch_um=1.0)
        assert npf_max_seconds(fine) < npf_max_seconds(coarse)

    def test_is_comparable_to_the_pixel_hardware_ceiling(self) -> None:
        # The finding that reshaped the plan: NPF (~5.5 s) and the reachable
        # hardware ceiling (~17 s) are the same order, so an untracked tripod
        # loses far less than it would at longer focal lengths.
        assert 3.0 < npf_max_seconds(PIXEL7PRO, 0.0) < 17.0


class TestSkyLimited:
    def test_none_when_sky_unknown(self) -> None:
        # Neutrality: no sky declared means no recommendation, not a guess.
        assert sky_limited_seconds(PIXEL7PRO, 800, None) is None

    def test_reference_point_reproduces_reference_exposure(self) -> None:
        # The anchor: SQM 21.0, f/2.0, ISO 800 -> 15 s on a phone-scale sensor.
        ref = SensorSpec(focal_mm=25.0, f_number=2.0, pixel_pitch_um=2.4)
        assert sky_limited_seconds(ref, 800, 21.0) == pytest.approx(15.0)

    def test_recommendation_varies_across_realistic_skies(self) -> None:
        # Regression guard for the anchor. A DSLR-scale anchor made every
        # phone-length sub demand a four-figure ISO, pinning the advice at the
        # analog ceiling for the whole usable range -- advice that never varies
        # is not advice. Hitting the ceiling under a genuinely dark sky is
        # correct; hitting it everywhere is the bug.
        isos = [recommend_iso(PIXEL7PRO, 17.0, sqm) for sqm in (21.7, 20.9, 19.5)]
        assert all(i is not None for i in isos)
        assert len(set(isos)) == len(isos)
        # Brighter sky, less gain needed to reach the same background level.
        assert isos == sorted(isos, reverse=True)

    def test_darker_sky_allows_longer_exposure(self) -> None:
        dark = sky_limited_seconds(PIXEL7PRO, 800, 21.7)
        bright = sky_limited_seconds(PIXEL7PRO, 800, 18.9)
        assert dark is not None
        assert bright is not None
        assert dark > bright

    def test_one_magnitude_is_a_factor_of_ten_to_the_zero_four(self) -> None:
        a = sky_limited_seconds(PIXEL7PRO, 800, 20.0)
        b = sky_limited_seconds(PIXEL7PRO, 800, 21.0)
        assert a is not None
        assert b is not None
        assert b / a == pytest.approx(10.0**0.4, rel=1e-9)

    def test_higher_iso_shortens_exposure_linearly(self) -> None:
        low = sky_limited_seconds(PIXEL7PRO, 400, 21.0)
        high = sky_limited_seconds(PIXEL7PRO, 800, 21.0)
        assert low is not None
        assert high is not None
        assert low == pytest.approx(2 * high)

    def test_faster_optics_shorten_exposure_as_inverse_square(self) -> None:
        slow = SensorSpec(focal_mm=25.0, f_number=4.0, pixel_pitch_um=2.4)
        fast = SensorSpec(focal_mm=25.0, f_number=2.0, pixel_pitch_um=2.4)
        s = sky_limited_seconds(slow, 800, 21.0)
        f = sky_limited_seconds(fast, 800, 21.0)
        assert s is not None
        assert f is not None
        assert s / f == pytest.approx(4.0)

    def test_rejects_nonpositive_iso(self) -> None:
        with pytest.raises(ExposureError, match="iso must be positive"):
            sky_limited_seconds(PIXEL7PRO, 0, 21.0)

    def test_rejects_nonpositive_target_fraction(self) -> None:
        with pytest.raises(ExposureError, match="target fraction"):
            sky_limited_seconds(PIXEL7PRO, 800, 21.0, target_fraction=0.0)


class TestRecommendIso:
    def test_none_when_sky_unknown(self) -> None:
        assert recommend_iso(PIXEL7PRO, 8.3, None) is None

    def test_never_exceeds_the_analog_ceiling(self) -> None:
        # A very short sub under a dark sky wants an enormous ISO; the analog
        # ceiling is the point past which more gain only adds noise.
        assert recommend_iso(PIXEL7PRO, 0.5, 21.7) == 744

    def test_never_below_sensor_minimum(self) -> None:
        assert recommend_iso(PIXEL7PRO, 3600.0, 17.8) == 48

    def test_shorter_exposure_wants_more_gain(self) -> None:
        short = recommend_iso(PIXEL7PRO, 4.0, 21.0)
        long_sub = recommend_iso(PIXEL7PRO, 30.0, 21.0)
        assert short is not None
        assert long_sub is not None
        assert short > long_sub

    def test_round_trips_against_sky_limited_seconds(self) -> None:
        # The two functions are inverses; an ISO inside the sensor range must
        # reproduce the exposure that generated it.
        exposure = 17.0
        iso = recommend_iso(PIXEL7PRO, exposure, 21.0)
        assert iso is not None
        back = sky_limited_seconds(PIXEL7PRO, iso, 21.0)
        assert back is not None
        assert back == pytest.approx(exposure, rel=0.01)

    def test_rejects_nonpositive_exposure(self) -> None:
        with pytest.raises(ExposureError, match="exposure must be positive"):
            recommend_iso(PIXEL7PRO, 0.0, 21.0)


class TestFramesForIntegration:
    def test_one_hour_at_the_pixel_ceiling(self) -> None:
        # The headline number from the plan: ~17 s subs, one hour of light.
        plan = frames_for_integration(1.0, 17.0)
        assert plan.frames == 212
        assert plan.integration_s == pytest.approx(212 * 17.0)

    def test_one_hour_at_the_advertised_ceiling(self) -> None:
        # And the un-extended case, which the design is sized against.
        assert frames_for_integration(1.0, 8.3).frames == 434

    def test_extension_roughly_halves_the_frame_count(self) -> None:
        short = frames_for_integration(2.0, 8.3)
        long_sub = frames_for_integration(2.0, 17.0)
        assert long_sub.frames < short.frames
        assert short.frames / long_sub.frames == pytest.approx(2.0, rel=0.05)

    def test_rounds_up_to_reach_the_requested_integration(self) -> None:
        # 100 s wanted with 30 s subs: 3 frames is only 90 s, so it must be 4.
        plan = frames_for_integration(100.0 / 3600.0, 30.0)
        assert plan.frames == 4
        assert plan.integration_s >= 100.0

    def test_wall_clock_exceeds_integration_by_write_overhead(self) -> None:
        plan = frames_for_integration(1.0, 17.0, write_overhead_s=2.0)
        assert plan.wall_clock_s == pytest.approx(plan.frames * 19.0)
        assert plan.wall_clock_s > plan.integration_s

    def test_storage_estimate_scales_with_frames(self) -> None:
        plan = frames_for_integration(2.0, 17.0, bytes_per_frame=20 * 1024 * 1024)
        gib = plan.bytes_estimate / 1024**3
        # ~425 frames at 20 MB is ~8.3 GB -- the number that decides the night.
        assert 7.0 < gib < 10.0

    def test_window_verdict_absent_when_no_window_given(self) -> None:
        assert frames_for_integration(1.0, 17.0).fits_window is None

    def test_window_verdict_true_when_it_fits(self) -> None:
        assert frames_for_integration(1.0, 17.0, window_hours=3.0).fits_window is True

    def test_window_verdict_false_when_it_does_not(self) -> None:
        assert frames_for_integration(3.0, 17.0, window_hours=1.0).fits_window is False

    def test_summary_flags_an_overrunning_window(self) -> None:
        plan = frames_for_integration(3.0, 17.0, window_hours=1.0)
        assert "LONGER THAN THE REMAINING WINDOW" in plan.summary()

    def test_summary_is_quiet_when_it_fits(self) -> None:
        plan = frames_for_integration(1.0, 17.0, window_hours=5.0)
        assert "LONGER" not in plan.summary()

    def test_rejects_nonpositive_integration(self) -> None:
        with pytest.raises(ExposureError, match="integration must be positive"):
            frames_for_integration(0.0, 17.0)

    def test_rejects_nonpositive_exposure(self) -> None:
        with pytest.raises(ExposureError, match="exposure must be positive"):
            frames_for_integration(1.0, 0.0)

    def test_always_at_least_one_frame(self) -> None:
        assert frames_for_integration(0.0001, 17.0).frames == 1
