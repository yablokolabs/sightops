"""Image-quality measurement.

These scores are what let the agent say "I cannot read this" with evidence
behind it, so each one is defined precisely and thresholded explicitly rather
than being a magic number at a call site.

**blur_score** (0..1, 1 = sharp)
    Normalised Laplacian variance: ``var(Laplacian(gray)) / std(gray)**2``,
    divided by :data:`BLUR_REFERENCE` and clipped. Dividing by the image's own
    standard deviation makes the metric respond to *detail* rather than to
    contrast, so a low-contrast but sharp frame is not mistaken for a blurry
    one. ``BLUR_REFERENCE`` is calibrated from the labelled fixture set — see
    ``docs/evaluation/methodology.md``; it is not a guess.

**exposure_quality** (0..1, 1 = well exposed)
    Starts at 1.0 and subtracts penalties for the fraction of clipped pixels at
    each end and for the mean luma sitting away from mid-grey.

**resolution_sufficient**
    The shorter edge must be at least :data:`MIN_SHORT_EDGE` px, so the
    configured regions still contain enough pixels to measure.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.models.schemas import ImageQuality

#: Laplacian-variance ratio at or above which an image scores a full 1.0.
#: ``python3 scripts/calibrate_quality.py`` re-derives the separation from the
#: repository's own fixtures and fails if an in-focus fixture no longer clears
#: the frame threshold, or if a frame whose detail has gone no longer falls below
#: it. Regenerating the fixtures and re-running that script is the supported way
#: to change this value.
BLUR_REFERENCE = 0.0022

#: Below this blur score the frame is treated as too soft to measure.
DEFAULT_BLUR_THRESHOLD = 0.35

MIN_SHORT_EDGE = 480
_CLIP_DARK = 8
_CLIP_LIGHT = 247


def blur_score(gray: np.ndarray) -> tuple[float, float]:
    """Return ``(normalised_score, raw_laplacian_variance)``."""
    gray_f = gray.astype(np.float32)
    variance = float(cv2.Laplacian(gray_f, cv2.CV_32F).var())
    contrast = float(gray_f.std()) ** 2
    ratio = variance / (contrast + 1e-6)
    score = float(np.clip(ratio / BLUR_REFERENCE, 0.0, 1.0))
    return score, variance


def exposure_quality(gray: np.ndarray) -> tuple[float, float]:
    """Return ``(quality, mean_luma)`` with luma normalised to 0..1."""
    total = gray.size
    if total == 0:
        return 0.0, 0.0
    dark_fraction = float(np.count_nonzero(gray <= _CLIP_DARK)) / total
    light_fraction = float(np.count_nonzero(gray >= _CLIP_LIGHT)) / total
    mean_luma = float(gray.mean()) / 255.0

    penalty = 0.0
    penalty += 2.2 * dark_fraction
    penalty += 2.2 * light_fraction
    # Distance from mid-grey, saturating at 0.5 (pure black or pure white).
    penalty += 0.6 * min(abs(mean_luma - 0.5) / 0.5, 1.0)
    return float(np.clip(1.0 - penalty, 0.0, 1.0)), mean_luma


def assess(
    bgr: np.ndarray,
    region: np.ndarray | None = None,
    *,
    region_id: str | None = None,
    blur_threshold: float = DEFAULT_BLUR_THRESHOLD,
    dark_threshold: float = 0.20,
    bright_threshold: float = 0.88,
    min_region_pixels: int = 400,
    min_short_edge: int = MIN_SHORT_EDGE,
) -> ImageQuality:
    """Score a frame, or a ``region`` crop of it, and decide if it is usable.

    When ``region`` is supplied the answer describes that crop; the resolution
    test then also requires the crop itself to contain enough pixels, which is
    what stops a correctly-exposed but tiny gauge from being "fine".
    """
    target = region if region is not None else bgr
    if target.ndim == 3:
        gray = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)
    else:
        gray = target

    blur, _ = blur_score(gray)
    exposure, mean_luma = exposure_quality(gray)
    height, width = gray.shape[:2]

    resolution_sufficient = min(width, height) >= min_short_edge and gray.size >= min_region_pixels

    reasons: list[str] = []
    if blur < blur_threshold:
        reasons.append(
            f"image detail is too low to measure reliably (blur score {blur:.2f}, "
            f"needs {blur_threshold:.2f})"
        )
    if mean_luma < dark_threshold:
        reasons.append(f"the frame is underexposed (mean brightness {mean_luma:.2f})")
    elif mean_luma > bright_threshold:
        reasons.append(f"the frame is overexposed (mean brightness {mean_luma:.2f})")
    if not resolution_sufficient:
        reasons.append(
            f"the region is only {width}x{height} px (needs {min_short_edge} px on the short edge "
            f"and {min_region_pixels} px total)"
        )

    return ImageQuality(
        blur_score=round(blur, 4),
        exposure_quality=round(exposure, 4),
        mean_luma=round(mean_luma, 4),
        resolution_sufficient=resolution_sufficient,
        width=width,
        height=height,
        requires_new_view=bool(reasons),
        reason="; ".join(reasons) if reasons else None,
        region_id=region_id,
    )
