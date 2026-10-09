"""Analog gauge reading.

Algorithm
---------
1. **Dial localisation.** ``cv2.HoughCircles`` over the gradient-filled ROI,
   accepted only when the circle is plausibly concentric with the configured
   region; otherwise the inscribed circle of the configured ROI is used and
   ``details.dial_source`` records which path was taken.
2. **Radial scan.** For every angle in :data:`ANGLE_STEP_DEG` increments the
   intensity is sampled along a ray from ``0.28 R`` to ``0.72 R``. The needle is
   the only feature that spans that band — printed ticks live beyond ``0.8 R``
   and the hub sits inside ``0.25 R`` — which is what separates the needle from
   the scale.
3. **Peak selection and shape validation.** The angular median is removed, both
   polarities are tested, and the stronger peak wins. The peak is then *checked*:
   a needle is a narrow feature whose ray is uniformly darker than the dial.

   This check exists because of a failure found during development. When the
   dial centre is wrong — a rotated or perspective-distorted frame whose circle
   Hough could not find — the radial scan still produces a peak, and on the
   original confidence formula it scored 0.72 while reading **28 PSI for a true
   87 PSI**. A confidently wrong pressure reading is the worst possible output
   for a reliability tool, so a peak now has to survive two further tests:

   * ``coverage`` — the share of the ray on the needle's side of the midpoint
     between the ray and the dial. A real needle passes through the whole band;
     a ray from a displaced centre crosses the bezel and is half dial-face.
   * ``width`` — the angular full width at half maximum. A needle is a few
     degrees wide; a misplaced-centre artefact is broad.

   Failing either test yields ``UNKNOWN``/``UNREADABLE`` with a confidence at or
   below :data:`UNREADABLE_CONFIDENCE`, never a number.
4. **Angle → value.** The profile's ``start_angle_deg`` / ``end_angle_deg``
   describe the printed scale; readings outside the sweep are reported as
   ``UNKNOWN`` rather than clamped, because clamping silently invents a value.

Confidence criteria, all reported in ``details.criteria``:

======================  =====  ==================================================
component               weight  meaning
======================  =====  ==================================================
``coverage_score``       0.25  ray consistently on the needle's side (ramps 0.6..1.0)
``peak_score``           0.25  peak prominence over angular noise (saturates at 3)
``width_score``          0.15  angular width at half maximum (3 deg good, 14 deg bad)
``contrast_score``       0.15  peak depth in grey levels (saturates at 60)
``margin_score``         0.10  separation from the rival peak (saturates at 30 deg)
``quality_factor``       0.10  blur/exposure score of the gauge crop
======================  =====  ==================================================
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.models.schemas import GaugeState, ImageQuality, Measurement, RegionSpec

ANGLE_STEP_DEG = 0.5
RADIAL_INNER = 0.28
RADIAL_OUTER = 0.72
RADIAL_SAMPLES = 24
RIVAL_SEPARATION_DEG = 20.0
PEAK_PROMINENCE_FULL = 3.0
MARGIN_FULL_DEG = 30.0
CONTRAST_FULL = 60.0
COVERAGE_FLOOR = 0.60
WIDTH_GOOD_DEG = 3.0
WIDTH_BAD_DEG = 14.0
UNREADABLE_CONFIDENCE = 0.25
#: How far past the printed scale a reading may sit and still be reported.
#:
#: The sub-step refinement resolves a peak to about half an angular step, so a
#: needle resting on the end stop measures a fraction of a degree *beyond* the
#: endpoint. Refusing that reading for pedantry produced a false refusal on a
#: perfectly clean frame at 0 PSI, where the measured -135.4 deg fell 0.4 deg
#: outside a sweep starting at -135 deg. Within this tolerance the reading is
#: clamped to the endpoint; beyond it, the needle is genuinely off-scale and the
#: value is withheld.
SWEEP_TOLERANCE_DEG = 3.0
#: Below this confidence the measured value is withheld entirely. A reliability
#: tool that prints "57 PSI" for a true 87 PSI is worse than one that says it
#: could not read the gauge, so a number is only published when it is trusted.
REPORT_FLOOR = 0.50

_WEIGHTS = {
    "coverage_score": 0.25,
    "peak_score": 0.25,
    "width_score": 0.15,
    "contrast_score": 0.15,
    "margin_score": 0.10,
    "quality_factor": 0.10,
}


def clock_angle(x: float, y: float, cx: float, cy: float) -> float:
    """Angle in degrees clockwise from 12 o'clock, in ``(-180, 180]``.

    Image coordinates put ``y`` downward; the sign of ``dy`` is flipped so that
    0 deg is up and 90 deg is to the right, matching how a gauge face is read.
    """
    return float(np.degrees(np.arctan2(x - cx, -(y - cy))))


@dataclass
class NeedlePeak:
    angle: float
    prominence: float
    depth: float
    margin: float
    coverage: float
    width_deg: float
    polarity: str


def _dial(region_bgr: np.ndarray, gray: np.ndarray) -> tuple[float, float, float, str, float]:
    """Return ``(cx, cy, radius, source, confidence)`` for the dial circle."""
    height, width = gray.shape[:2]
    inscribed = 0.46 * min(width, height)
    fallback = (width / 2.0, height / 2.0, inscribed)

    blurred = cv2.medianBlur(gray, 5)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=min(width, height),
        param1=120,
        param2=40,
        minRadius=int(0.30 * inscribed),
        maxRadius=int(1.25 * inscribed),
    )
    if circles is None or len(circles[0]) == 0:
        return (*fallback, "configured_roi_inscribed", 0.6)

    cx, cy, radius = (float(v) for v in circles[0][0])
    centre_offset = float(np.hypot(cx - width / 2.0, cy - height / 2.0))
    if centre_offset > 0.18 * inscribed or not (0.7 * inscribed <= radius <= 1.3 * inscribed):
        # A circle that is not where the profile says the gauge is may be a
        # fastener or the bezel; the calibrated geometry is the safer answer.
        return (*fallback, "configured_roi_inscribed", 0.6)

    concentricity = 1.0 - min(centre_offset / (0.18 * inscribed), 1.0)
    size_agreement = 1.0 - min(abs(radius - inscribed) / (0.3 * inscribed), 1.0)
    return (
        cx,
        cy,
        radius,
        "hough_circle",
        float(np.clip(0.6 * concentricity + 0.4 * size_agreement, 0.0, 1.0)),
    )


def _radial_samples(
    gray: np.ndarray, cx: float, cy: float, radius: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample along every angle.

    Returns ``(angles, samples, profile)`` where ``samples`` has shape
    ``(n_angles, RADIAL_SAMPLES)`` and ``profile`` is the per-angle mean.
    """
    float_gray = gray.astype(np.float32)
    height, width = gray.shape[:2]
    angles = np.arange(-180.0, 180.0, ANGLE_STEP_DEG)
    radii = np.linspace(RADIAL_INNER * radius, RADIAL_OUTER * radius, RADIAL_SAMPLES)

    radians = np.radians(angles)
    # Clock angle to image offsets: x = sin(theta) * r, y = -cos(theta) * r.
    xs = cx + np.sin(radians)[:, None] * radii[None, :]
    ys = cy - np.cos(radians)[:, None] * radii[None, :]
    sample_x = np.clip(np.rint(xs).astype(np.int32), 0, width - 1)
    sample_y = np.clip(np.rint(ys).astype(np.int32), 0, height - 1)
    samples = float_gray[sample_y, sample_x]
    return angles, samples, samples.mean(axis=1)


def _coverage(ray: np.ndarray, dial_level: float, *, darker: bool) -> float:
    """Share of the ray that sits on the needle's side of the midpoint."""
    ray_level = float(ray.mean())
    midpoint = 0.5 * (dial_level + ray_level)
    if darker:
        return float(np.count_nonzero(ray < midpoint)) / float(ray.size)
    return float(np.count_nonzero(ray > midpoint)) / float(ray.size)


def _angular_width(normalised: np.ndarray, index: int, peak: float) -> float:
    """Full width at half maximum around ``index``, walking circularly."""
    half = peak / 2.0
    count = len(normalised)
    left = 0
    while left < 60 and normalised[(index - left - 1) % count] > half:
        left += 1
    right = 0
    while right < 60 and normalised[(index + right + 1) % count] > half:
        right += 1
    return float(left + right) * ANGLE_STEP_DEG


def _find_peak(
    angles: np.ndarray, samples: np.ndarray, profile: np.ndarray, *, darker: bool
) -> NeedlePeak:
    """Locate and characterise the strongest needle peak for one polarity."""
    residual = np.median(profile) - profile if darker else profile - np.median(profile)
    baseline = float(np.median(np.abs(residual - np.median(residual)))) + 1e-3
    normalised = residual / baseline

    index = int(np.argmax(normalised))
    prominence = float(normalised[index])
    depth = float(residual[index])

    masked = normalised.copy()
    offsets = np.abs(((angles - angles[index]) + 180.0) % 360.0 - 180.0)
    masked[offsets < RIVAL_SEPARATION_DEG] = -np.inf
    rival = float(np.max(masked)) if np.isfinite(masked).any() else 0.0
    margin = prominence - rival

    # Sub-step refinement: a parabolic fit through the peak and its neighbours
    # recovers roughly half a step of angular resolution.
    count = len(normalised)
    left = normalised[(index - 1) % count]
    centre = normalised[index]
    right = normalised[(index + 1) % count]
    denominator = left - 2.0 * centre + right
    shift = 0.0 if abs(denominator) < 1e-9 else 0.5 * (left - right) / denominator
    shift = float(np.clip(shift, -1.0, 1.0))
    refined = float(angles[index] + shift * ANGLE_STEP_DEG)

    return NeedlePeak(
        angle=refined,
        prominence=prominence,
        depth=depth,
        margin=margin,
        coverage=_coverage(samples[index], float(np.median(profile)), darker=darker),
        width_deg=_angular_width(normalised, index, prominence),
        polarity="dark_needle" if darker else "light_needle",
    )


def _confidence(
    peak: NeedlePeak, quality: ImageQuality | None
) -> tuple[float, dict[str, float]]:
    quality_factor = 1.0
    if quality is not None:
        quality_factor = float(
            np.clip(0.6 * quality.blur_score + 0.4 * quality.exposure_quality, 0.0, 1.0)
        )
    criteria = {
        "coverage_score": round(
            float(np.clip((peak.coverage - COVERAGE_FLOOR) / (1.0 - COVERAGE_FLOOR), 0.0, 1.0)), 4
        ),
        "peak_score": round(float(np.clip(peak.prominence / PEAK_PROMINENCE_FULL, 0.0, 1.0)), 4),
        "width_score": round(
            float(np.clip(1.0 - (peak.width_deg - WIDTH_GOOD_DEG) / (WIDTH_BAD_DEG - WIDTH_GOOD_DEG), 0.0, 1.0)),
            4,
        ),
        "contrast_score": round(float(np.clip(abs(peak.depth) / CONTRAST_FULL, 0.0, 1.0)), 4),
        "margin_score": round(float(np.clip(peak.margin / MARGIN_FULL_DEG, 0.0, 1.0)), 4),
        "quality_factor": round(quality_factor, 4),
    }
    return float(np.clip(sum(criteria[k] * _WEIGHTS[k] for k in _WEIGHTS), 0.0, 1.0)), criteria


def angle_to_value(angle: float, spec: RegionSpec) -> tuple[float | None, float]:
    """Map a clock angle onto the configured scale.

    Returns ``(value, position)`` where ``position`` is the normalised ``0..1``
    position on the sweep, or ``(None, ...)`` when the reading falls further
    outside it than :data:`SWEEP_TOLERANCE_DEG`.
    """
    start = spec.start_angle_deg if spec.start_angle_deg is not None else -135.0
    end = spec.end_angle_deg if spec.end_angle_deg is not None else 135.0
    scale_min = spec.scale_min if spec.scale_min is not None else 0.0
    scale_max = spec.scale_max if spec.scale_max is not None else 100.0

    sweep = end - start
    if sweep <= 0:
        sweep += 360.0
    relative = (angle - start) % 360.0
    if relative > sweep:
        # Modulo wraps a needle that sits a fraction of a degree *before* the
        # start of the sweep round to just under 360, so both ends are tested
        # before deciding the reading is off-scale.
        if relative > 360.0 - SWEEP_TOLERANCE_DEG:
            relative = 0.0
        elif relative <= sweep + SWEEP_TOLERANCE_DEG:
            pass
        else:
            return None, relative / 360.0

    position = min(max(relative / sweep, 0.0), 1.0)
    return scale_min + position * (scale_max - scale_min), position


def _unreadable(
    region_bgr: np.ndarray, spec: RegionSpec, reason: str, confidence: float
) -> Measurement:
    return Measurement(
        component_id=spec.region_id,
        component_type="analog_gauge",
        state=GaugeState.UNKNOWN.value,
        value=None,
        unit=spec.unit or "",
        confidence=round(float(np.clip(confidence, 0.0, UNREADABLE_CONFIDENCE)), 4),
        method="opencv_needle_geometry",
        requires_reinspection=True,
        notes=[reason],
        details={"region_pixels": int(region_bgr.size)},
    )


def read_gauge(
    region_bgr: np.ndarray,
    spec: RegionSpec,
    *,
    quality: ImageQuality | None = None,
) -> Measurement:
    """Measure one analog gauge, or report that it cannot be measured."""
    unit = spec.unit or ""

    if region_bgr.size == 0:
        return _unreadable(region_bgr, spec, "the configured gauge region falls outside the image", 0.0)

    gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    gray = cv2.bilateralFilter(gray, 7, 40, 40)

    cx, cy, radius, dial_source, dial_confidence = _dial(region_bgr, gray)
    if radius < 8:
        return _unreadable(
            region_bgr,
            spec,
            f"the gauge region is only {region_bgr.shape[1]}x{region_bgr.shape[0]} px",
            0.0,
        )

    angles, samples, profile = _radial_samples(gray, cx, cy, radius)
    dark = _find_peak(angles, samples, profile, darker=True)
    light = _find_peak(angles, samples, profile, darker=False)
    peak = dark if dark.prominence >= light.prominence else light

    confidence, criteria = _confidence(peak, quality)
    if dial_source == "configured_roi_inscribed":
        # The dial centre came from the profile rather than the image, so
        # geometric agreement is weaker evidence than it looks.
        confidence *= 0.85
    confidence = float(np.clip(confidence * (0.85 + 0.15 * dial_confidence), 0.0, 1.0))

    value, position = angle_to_value(peak.angle, spec)
    details = {
        "needle_angle_deg": round(peak.angle, 3),
        "sweep_position": round(position, 4),
        "dial_center": [round(cx, 2), round(cy, 2)],
        "dial_radius": round(radius, 2),
        "dial_source": dial_source,
        "dial_confidence": round(dial_confidence, 4),
        "polarity": peak.polarity,
        "prominence": round(peak.prominence, 3),
        "rival_margin": round(peak.margin, 3),
        "peak_depth_grey": round(peak.depth, 3),
        "ray_coverage": round(peak.coverage, 4),
        "peak_width_deg": round(peak.width_deg, 3),
        "scale": {
            "min": spec.scale_min,
            "max": spec.scale_max,
            "unit": spec.unit,
            "start_angle_deg": spec.start_angle_deg,
            "end_angle_deg": spec.end_angle_deg,
            "warn_above": spec.warn_above,
        },
        "criteria": criteria,
    }

    # Shape validation: this is what stops a displaced-centre artefact from
    # being reported as a measurement.
    if peak.coverage < COVERAGE_FLOOR:
        return _unreadable(
            region_bgr,
            spec,
            (
                f"only {peak.coverage:.0%} of the sampled ray lies on one side of the dial "
                f"level, which is not the profile of a needle (a real needle covers at least "
                f"{COVERAGE_FLOOR:.0%})"
            ),
            confidence,
        ).model_copy(update={"details": details})
    if peak.width_deg > WIDTH_BAD_DEG:
        return _unreadable(
            region_bgr,
            spec,
            (
                f"the angular peak is {peak.width_deg:.0f} deg wide, which is a smear rather "
                f"than a needle (needs to be under {WIDTH_BAD_DEG:.0f} deg)"
            ),
            confidence,
        ).model_copy(update={"details": details})
    if value is None:
        return _unreadable(
            region_bgr,
            spec,
            (
                f"the needle sits at {peak.angle:.1f} deg, outside the configured sweep of "
                f"{spec.start_angle_deg:.0f} to {spec.end_angle_deg:.0f} deg"
            ),
            confidence,
        ).model_copy(update={"details": details})
    if confidence < REPORT_FLOOR:
        return _unreadable(
            region_bgr,
            spec,
            (
                f"confidence in this reading is {confidence:.0%}, below the "
                f"{REPORT_FLOOR:.0%} needed to publish a value"
            ),
            confidence,
        ).model_copy(update={"details": details})

    notes: list[str] = []
    if dial_source == "configured_roi_inscribed":
        notes.append(
            "the dial circle could not be detected in this frame, so the configured region "
            "geometry was used"
        )
    if peak.coverage < 0.9:
        notes.append(f"the needle covers {peak.coverage:.0%} of the sampled radial band")
    if quality is not None and quality.requires_new_view and quality.reason:
        notes.append(quality.reason)

    state = GaugeState.NORMAL
    if spec.warn_above is not None and value > spec.warn_above:
        state = GaugeState.HIGH
    elif spec.scale_min is not None and value < spec.scale_min:
        state = GaugeState.LOW

    marginal = (
        confidence < 0.60
        or peak.prominence < PEAK_PROMINENCE_FULL
        or (quality is not None and quality.requires_new_view and confidence < 0.85)
    )
    if marginal and not notes:
        notes.append("the reading is close to the reliability threshold for this gauge")

    return Measurement(
        component_id=spec.region_id,
        component_type="analog_gauge",
        state=state.value,
        value=round(value, 2),
        unit=unit,
        confidence=round(confidence, 4),
        method="opencv_needle_geometry",
        requires_reinspection=bool(marginal),
        notes=notes,
        details=details,
    )
