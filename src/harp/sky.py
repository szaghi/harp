"""Sky quality: light pollution, surface brightness, and target contrast.

HARP models the horizon honestly but, until this module, said nothing about
the sky ABOVE it — a magnitude-13 galaxy scored identically from a Bortle 8
balcony and a Bortle 2 mountain. For a planner whose premise is "image the sky
your balcony can actually see", that was the conspicuous gap.

What actually decides whether a deep-sky object is imageable is CONTRAST: the
object's surface brightness against the sky background, not its integrated
magnitude. A compact planetary nebula concentrates its light into a few square
arcseconds and cuts through city glow; a large faint galaxy spreads the same
total flux over hundreds of times the area and drowns in it. That is why M57
is a famous city target and M101 a famous light-pollution casualty despite
being nearly a magnitude BRIGHTER in integrated terms.

Two corrections separate imaging from visual observing, and both matter:

* **Narrowband.** A dual-band filter passes Halpha/OIII and rejects most
  broadband light pollution, so an emission nebula behaves as if the sky were
  far darker. Without this term the model would punish exactly the targets
  imagers deliberately shoot from bad skies.
* **Aperture.** More collecting area means more signal per unit time. The
  effect is weaker than in visual use — an imager can integrate longer — so it
  enters as a gentle logarithmic nudge, not a dominant factor.

Everything here is offline arithmetic; no catalogue, no network.
"""

from __future__ import annotations

import math

__all__ = [
    "BORTLE_SQM",
    "REFERENCE_APERTURE_MM",
    "contrast_score",
    "sky_brightness",
    "surface_brightness",
]

# Bortle class -> approximate zenith sky brightness, mag/arcsec^2.
# The standard published mapping; class 1 is a pristine desert sky, class 9 an
# inner-city one. Values are deliberately coarse: a user estimating their own
# Bortle class is already working to about half a class of precision.
BORTLE_SQM: dict[int, float] = {
    1: 22.0,
    2: 21.7,
    3: 21.4,
    4: 20.9,
    5: 20.3,
    6: 19.5,
    7: 18.9,
    8: 18.4,
    9: 17.8,
}

#: Aperture the contrast model is normalised to, mm. A 200 mm scope scores
#: exactly its surface-brightness contrast; smaller/larger nudge from there.
REFERENCE_APERTURE_MM = 200.0

#: How much darker a dual-band filter makes the effective sky, mag/arcsec^2.
#: Conservative: real dual-band filters on a light-polluted sky are often
#: quoted higher, but overstating this would let narrowband targets ignore
#: light pollution entirely, which is not true of the broadband continuum.
_NARROWBAND_GAIN = 2.5


def sky_brightness(bortle: int | None = None, sqm: float | None = None) -> float | None:
    """Zenith sky brightness in mag/arcsec^2, or None if unspecified.

    Parameters
    ----------
    bortle : int or None
        Bortle class 1-9. Ignored when ``sqm`` is given.
    sqm : float or None
        Measured sky brightness, mag/arcsec^2. Wins over ``bortle`` because it
        is a measurement rather than an estimate.

    Returns
    -------
    float or None
        Sky brightness, or None when the site declares neither — in which case
        callers must leave the ranking unchanged rather than guess.
    """
    if sqm is not None:
        return float(sqm)
    if bortle is None:
        return None
    return BORTLE_SQM.get(round(bortle))


def surface_brightness(
    mag: float | None, maj_arcmin: float | None, min_arcmin: float | None = None
) -> float | None:
    """Mean surface brightness in mag/arcsec^2, or None if underdetermined.

    Spreads the integrated magnitude over the object's apparent ellipse. This
    is the quantity that competes with the sky background; integrated
    magnitude on its own is close to useless for extended objects.

    Parameters
    ----------
    mag : float or None
        Integrated visual magnitude. None for most emission nebulae, which is
        why this returns None rather than inventing a value.
    maj_arcmin : float or None
        Major axis, arcmin.
    min_arcmin : float or None
        Minor axis, arcmin. Defaults to ``maj_arcmin`` (a circular object).

    Returns
    -------
    float or None
        Surface brightness, mag/arcsec^2. Larger numbers are FAINTER, as with
        all magnitudes.
    """
    if mag is None or maj_arcmin is None or maj_arcmin <= 0.0:
        return None
    minor = min_arcmin if (min_arcmin and min_arcmin > 0.0) else maj_arcmin
    # Ellipse area in square arcseconds; axes are full extents, hence /2.
    area = math.pi * (maj_arcmin * 60.0 / 2.0) * (minor * 60.0 / 2.0)
    if area <= 0.0:
        return None
    return float(mag + 2.5 * math.log10(area))


def contrast_score(
    mag: float | None,
    maj_arcmin: float | None,
    min_arcmin: float | None,
    sky_mag: float | None,
    *,
    narrowband: bool = False,
    aperture_mm: float | None = None,
) -> float:
    """How well a target stands out from the sky, in ``[0.30, 1.0]``.

    Returns a neutral ``1.0`` whenever the model cannot be applied — no sky
    brightness declared, or no magnitude/size to derive surface brightness
    from. That neutrality is deliberate: an unknown must not be penalised, or
    adding this term would silently demote every magnitude-less Sharpless
    region the moment a user sets a Bortle class.

    The floor of 0.30 matters just as much. The composite score is a weighted
    geometric mean, so a near-zero factor annihilates a target instead of
    ranking it. A hopeless-from-here object should sink, not vanish.

    Parameters
    ----------
    mag, maj_arcmin, min_arcmin : float or None
        Target photometry and size; see :func:`surface_brightness`.
    sky_mag : float or None
        Sky brightness from :func:`sky_brightness`. None disables the model.
    narrowband : bool
        True for emission targets shot through a dual-band filter, which
        rejects most broadband light pollution.
    aperture_mm : float or None
        Telescope aperture. None uses :data:`REFERENCE_APERTURE_MM`.

    Returns
    -------
    float
        Contrast factor in ``[0.30, 1.0]``.
    """
    if sky_mag is None:
        return 1.0
    sb = surface_brightness(mag, maj_arcmin, min_arcmin)
    if sb is None:
        return 1.0

    # How many mag/arcsec^2 the target sits ABOVE the sky background.
    # Positive = brighter than sky = easy.
    delta = sky_mag - sb
    if narrowband:
        delta += _NARROWBAND_GAIN
    aperture = aperture_mm if (aperture_mm and aperture_mm > 0.0) else REFERENCE_APERTURE_MM
    delta += 1.2 * math.log10(max(aperture, 50.0) / REFERENCE_APERTURE_MM)

    # Logistic roll-off. The +1.2 offset places the half-way point about one
    # magnitude BELOW the sky background: an object slightly fainter than the
    # sky is still very much imageable with integration, which is the whole
    # difference between imaging and visual observing.
    return float(0.30 + 0.70 / (1.0 + math.exp(-(delta + 1.2) * 0.9)))
