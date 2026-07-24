"""Tests for the sky-quality contrast model.

The assertions that matter most here are the NEUTRALITY ones. This term was
added to an existing scoring function, so the contract is that a config which
says nothing about its sky must rank exactly as it did before the term
existed. A regression there would silently reshuffle every user's plan.
"""

from __future__ import annotations

import pytest

from harp.sky import (
    BORTLE_SQM,
    contrast_score,
    sky_brightness,
    surface_brightness,
)

# Real catalogue values, chosen because their behaviour is well known to
# observers: M57 is a famous city target, M101 a famous light-pollution
# casualty, despite M101 being nearly a magnitude brighter integrated.
M57 = (8.8, 1.4, 1.0)  # compact planetary, very high surface brightness
M101 = (7.9, 29.0, 27.0)  # large face-on spiral, very low surface brightness
M42 = (4.0, 85.0, 60.0)
HEART = (6.5, 150.0, 150.0)  # Sharpless-class emission, narrowband showpiece


class TestSkyBrightness:
    def test_bortle_maps_to_sqm(self) -> None:
        assert sky_brightness(bortle=1) == BORTLE_SQM[1]
        assert sky_brightness(bortle=9) == BORTLE_SQM[9]

    def test_darker_class_is_numerically_larger(self) -> None:
        """Magnitudes run backwards: a darker sky is a BIGGER number."""
        dark = sky_brightness(bortle=1)
        bright = sky_brightness(bortle=9)
        assert dark is not None
        assert bright is not None
        assert dark > bright

    def test_sqm_wins_over_bortle(self) -> None:
        """A measurement beats an estimate."""
        assert sky_brightness(bortle=9, sqm=21.5) == 21.5

    def test_nothing_declared_is_none(self) -> None:
        assert sky_brightness() is None
        assert sky_brightness(bortle=None, sqm=None) is None

    def test_out_of_range_bortle_is_none(self) -> None:
        """An impossible class must not silently become a real sky."""
        assert sky_brightness(bortle=12) is None


class TestSurfaceBrightness:
    def test_compact_object_is_brighter_per_area(self) -> None:
        """M57 concentrates its light; M101 spreads it. This is the whole model."""
        sb57 = surface_brightness(*M57)
        sb101 = surface_brightness(*M101)
        assert sb57 is not None
        assert sb101 is not None
        assert sb57 < sb101

    def test_known_values(self) -> None:
        # mag + 2.5*log10(area in arcsec^2), checked by hand
        assert surface_brightness(*M57) == pytest.approx(17.79, abs=0.05)
        assert surface_brightness(*M101) == pytest.approx(23.76, abs=0.05)

    def test_missing_inputs_give_none(self) -> None:
        assert surface_brightness(None, 30.0, 30.0) is None
        assert surface_brightness(8.0, None, None) is None
        assert surface_brightness(8.0, 0.0, 0.0) is None

    def test_minor_axis_defaults_to_major(self) -> None:
        assert surface_brightness(8.0, 10.0) == surface_brightness(8.0, 10.0, 10.0)


class TestNeutrality:
    """The term must be exactly 1.0 whenever the model cannot be applied."""

    def test_no_sky_declared_is_neutral(self) -> None:
        assert contrast_score(*M101, None) == 1.0

    def test_no_magnitude_is_neutral(self) -> None:
        """Magnitude-less Sharpless regions must not be demoted by default."""
        assert contrast_score(None, 150.0, 150.0, BORTLE_SQM[8]) == 1.0

    def test_no_size_is_neutral(self) -> None:
        assert contrast_score(8.0, None, None, BORTLE_SQM[8]) == 1.0


class TestContrast:
    def test_bounded(self) -> None:
        """Never zero: the composite score is a geometric mean, so a zero
        factor would annihilate a target rather than rank it low."""
        for b in BORTLE_SQM:
            for obj in (M57, M101, M42, HEART):
                assert 0.30 <= contrast_score(*obj, BORTLE_SQM[b]) <= 1.0

    def test_darker_sky_never_scores_worse(self) -> None:
        for obj in (M57, M101, M42):
            assert contrast_score(*obj, BORTLE_SQM[2]) >= contrast_score(*obj, BORTLE_SQM[8])

    def test_light_pollution_hits_low_surface_brightness_hardest(self) -> None:
        """M101 should collapse from dark to city sky; M57 should barely move.

        This is the model's central claim, and the reason integrated
        magnitude alone is the wrong basis for ranking.
        """
        m101_drop = contrast_score(*M101, BORTLE_SQM[2]) - contrast_score(*M101, BORTLE_SQM[8])
        m57_drop = contrast_score(*M57, BORTLE_SQM[2]) - contrast_score(*M57, BORTLE_SQM[8])
        assert m101_drop > m57_drop

    def test_compact_bright_target_survives_a_city(self) -> None:
        assert contrast_score(*M57, BORTLE_SQM[9]) > 0.8

    def test_narrowband_resists_light_pollution(self) -> None:
        """A dual-band filter is why imagers shoot emission targets downtown."""
        broad = contrast_score(*HEART, BORTLE_SQM[7])
        narrow = contrast_score(*HEART, BORTLE_SQM[7], narrowband=True)
        assert narrow > broad

    def test_aperture_helps_but_gently(self) -> None:
        small = contrast_score(*M101, BORTLE_SQM[6], aperture_mm=80.0)
        large = contrast_score(*M101, BORTLE_SQM[6], aperture_mm=400.0)
        assert large > small
        # An imager integrates longer; aperture must not dominate sky quality.
        sky_effect = contrast_score(*M101, BORTLE_SQM[2]) - contrast_score(*M101, BORTLE_SQM[8])
        assert (large - small) < sky_effect

    def test_missing_aperture_uses_reference(self) -> None:
        assert contrast_score(*M101, BORTLE_SQM[5]) == contrast_score(
            *M101, BORTLE_SQM[5], aperture_mm=200.0
        )
