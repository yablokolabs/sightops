"""Indicator (LED) state classification.

Method: HSV segmentation of the lamp blob, contour selection, then hue-band
classification. Confidence is a weighted sum of four independently meaningful
quality criteria, all of which are reported in ``details`` so a low confidence
can be read back to the criterion that caused it:

======================  =====  ==================================================
component               weight  meaning
======================  =====  ==================================================
``hue_purity``           0.40  share of lamp pixels inside the winning hue band
``area_score``           0.20  lamp area relative to the ROI (ramps to 1.0 at 3 %)
``saturation_score``     0.20  mean saturation of the lamp relative to a lit LED
``value_score``          0.15  mean brightness of the lamp
``quality_factor``       0.05  blur/exposure score of the lamp crop
======================  =====  ==================================================

A dark ROI yields ``OFF``; a ROI whose blob is too small or too desaturated to
place in a hue band yields ``UNKNOWN`` with a low confidence, which is what
drives the agent to ask for a better view.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.models.schemas import ImageQuality, IndicatorState, Measurement

#: Inclusive-exclusive hue bands in OpenCV's 0..179 scale.
HUE_BANDS: list[tuple[str, int, int]] = [
    ("RED_LOW", 0, 10),
    ("AMBER", 10, 28),
    ("GREEN", 35, 85),
    ("BLUE", 85, 135),
    ("VIOLET", 135, 160),
    ("RED_HIGH", 160, 180),
]

_WEIGHTS = {
    "hue_purity": 0.40,
    "area_score": 0.20,
    "saturation_score": 0.20,
    "value_score": 0.15,
    "quality_factor": 0.05,
}

AREA_FULL_SCORE = 0.03
SATURATION_REFERENCE = 120.0
VALUE_FLOOR = 60.0
VALUE_SATURATION = 120.0
MIN_BLOB_AREA_RATIO = 0.0015

#: Hue and saturation below these are treated as an unlit (dark) lamp.
OFF_VALUE = 70.0
OFF_SATURATION = 45.0
#: Levels a lit lamp reaches; the OFF decision is scored as the gap from these.
LIT_MIN_VALUE = 170.0
LIT_MIN_SATURATION = 120.0


def _band_of(hue: float) -> str | None:
    for name, low, high in HUE_BANDS:
        if low <= hue < high:
            return name
    return None


#: Hue-band winner mapped onto the reported indicator state. RED's two bands
#: are pooled before this lookup, and VIOLET has no state of its own, so it is
#: reported as UNKNOWN rather than squeezed into a neighbouring colour.
_STATE_BY_WINNER: dict[str, IndicatorState] = {
    "RED": IndicatorState.RED,
    "AMBER": IndicatorState.AMBER,
    "GREEN": IndicatorState.GREEN,
    "BLUE": IndicatorState.BLUE,
}


def _lamp_blob(region_bgr: np.ndarray) -> tuple[np.ndarray | None, float]:
    """Segment the lamp and return ``(mask, area_ratio)`` for the largest blob."""
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    height, width = region_bgr.shape[:2]
    roi_pixels = float(height * width)

    value = hsv[:, :, 2]
    saturation = hsv[:, :, 1]
    # A lit lamp is brighter than the surrounding bezel; threshold relative to
    # the ROI's own brightness so this works on a bright or a dark panel.
    value_floor = max(VALUE_FLOOR, 0.65 * float(np.percentile(value, 99)))
    mask = ((value >= value_floor) & (saturation >= 35)).astype(np.uint8) * 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, 0.0
    largest = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(largest))
    if area <= 1.0:
        return None, 0.0
    clean = np.zeros_like(mask)
    cv2.drawContours(clean, [largest], -1, 255, thickness=cv2.FILLED)
    return clean, area / roi_pixels


def detect_indicator(
    region_bgr: np.ndarray,
    *,
    component_id: str,
    quality: ImageQuality | None = None,
    background_weight: float = 1.0,
) -> Measurement:
    """Classify a single indicator lamp.

    ``background_weight`` scales the final confidence when brightness comes from
    a bleed/diffusion path rather than from the lamp itself, giving the agent a
    way to compare the same lamp seen by different sensors.
    """
    if region_bgr.size == 0:
        return Measurement(
            component_id=component_id,
            component_type="indicator",
            state=IndicatorState.UNKNOWN.value,
            confidence=0.0,
            method="opencv_hsv_roi",
            requires_reinspection=True,
            notes=["the configured indicator region falls outside the image"],
        )

    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    mask, area_ratio = _lamp_blob(region_bgr)

    mean_value = float(hsv[:, :, 2].mean())
    mean_saturation = float(hsv[:, :, 1].mean())

    if mask is None or area_ratio < MIN_BLOB_AREA_RATIO:
        # No distinct lamp: this is a genuinely unlit indicator *if* the crop is
        # dark and unsaturated, otherwise we simply cannot tell.
        if mean_value < OFF_VALUE or mean_saturation < OFF_SATURATION:
            # An unlit lamp is evidenced by the region having *no lamp-like
            # pixels at all*, which is a different question from the one the
            # lit-lamp criteria ask. It is scored as the gap between the
            # brightest, most saturated part of the window and the levels a lit
            # lamp would produce. Reusing the lit-lamp formula here reported a
            # confident OFF as unsure merely because a uniform dark crop has
            # little detail for the blur metric to measure.
            peak_value = float(np.percentile(hsv[:, :, 2], 99.5))
            peak_saturation = float(np.percentile(hsv[:, :, 1], 99.5))
            brightness_gap = float(np.clip((LIT_MIN_VALUE - peak_value) / LIT_MIN_VALUE, 0.0, 1.0))
            saturation_gap = float(
                np.clip((LIT_MIN_SATURATION - peak_saturation) / LIT_MIN_SATURATION, 0.0, 1.0)
            )
            exposure = 1.0 if quality is None else float(quality.exposure_quality)
            confidence = float(
                np.clip(0.55 * brightness_gap + 0.25 * saturation_gap + 0.20 * exposure, 0.0, 1.0)
            )
            return Measurement(
                component_id=component_id,
                component_type="indicator",
                state=IndicatorState.OFF.value,
                confidence=round(confidence, 4),
                method="opencv_hsv_roi",
                requires_reinspection=confidence < 0.55
                or (quality is not None and quality.exposure_quality < 0.3),
                notes=["no lamp-like pixels in this region: indicator reads as unlit"],
                details={
                    "mean_value": round(mean_value, 2),
                    "mean_saturation": round(mean_saturation, 2),
                    "peak_value": round(peak_value, 2),
                    "peak_saturation": round(peak_saturation, 2),
                    "area_ratio": round(area_ratio, 5),
                    "criteria": {
                        "brightness_gap": round(brightness_gap, 4),
                        "saturation_gap": round(saturation_gap, 4),
                        "exposure": round(exposure, 4),
                    },
                },
            )
        return Measurement(
            component_id=component_id,
            component_type="indicator",
            state=IndicatorState.UNKNOWN.value,
            confidence=0.0,
            method="opencv_hsv_roi",
            requires_reinspection=True,
            notes=["no lamp blob could be segmented in this region"],
            details={
                "mean_value": round(mean_value, 2),
                "mean_saturation": round(mean_saturation, 2),
                "area_ratio": round(area_ratio, 5),
            },
        )

    hue = hsv[:, :, 0][mask > 0]
    saturation = hsv[:, :, 1][mask > 0]
    value = hsv[:, :, 2][mask > 0]
    total = float(hue.size)

    histogram = np.bincount(hue.astype(np.int32), minlength=180).astype(np.float64) / total
    band_counts: dict[str, float] = {}
    for name, low, high in HUE_BANDS:
        band_counts[name] = float(histogram[low:high].sum())

    # RED is reported as one state; its two hue bands are pooled before the
    # winner is chosen so a lamp straddling 0/179 is not split.
    pooled = {
        "RED": band_counts["RED_LOW"] + band_counts["RED_HIGH"],
        "AMBER": band_counts["AMBER"],
        "GREEN": band_counts["GREEN"],
        "BLUE": band_counts["BLUE"],
        "VIOLET": band_counts["VIOLET"],
    }
    winner = max(pooled, key=pooled.get)
    hue_purity = pooled[winner]

    blob_saturation = float(saturation.mean())
    blob_value = float(value.mean())
    quality_factor = 1.0
    if quality is not None:
        quality_factor = float(np.clip(0.5 * quality.blur_score + 0.5 * quality.exposure_quality, 0.0, 1.0))

    confidence = _confidence(
        hue_purity=hue_purity,
        area_ratio=area_ratio,
        mean_saturation=blob_saturation,
        mean_value=blob_value,
        quality=quality,
    )
    confidence = float(np.clip(confidence * background_weight, 0.0, 1.0))

    if blob_saturation < 45.0 and blob_value > 170.0:
        state = IndicatorState.WHITE
    else:
        state = _STATE_BY_WINNER.get(winner, IndicatorState.UNKNOWN)

    notes: list[str] = []
    if hue_purity < 0.55:
        notes.append(
            f"only {hue_purity:.0%} of the lamp pixels sit in the {winner} hue band"
        )
    if area_ratio < AREA_FULL_SCORE:
        notes.append(f"the lamp covers just {area_ratio:.1%} of the region")
    if quality and quality.requires_new_view and quality.reason:
        notes.append(quality.reason)

    return Measurement(
        component_id=component_id,
        component_type="indicator",
        state=state.value,
        confidence=round(confidence, 4),
        method="opencv_hsv_roi",
        # A strong colour reading survives a marginal quality flag; a marginal
        # one does not, which is where the agent's reinspection decision comes
        # from.
        requires_reinspection=bool(
            confidence < 0.55
            or (quality is not None and quality.requires_new_view and confidence < 0.85)
        ),
        notes=notes,
        details={
            "hue_bands": {k: round(v, 4) for k, v in pooled.items()},
            "hue_purity": round(hue_purity, 4),
            "area_ratio": round(area_ratio, 5),
            "blob_saturation": round(blob_saturation, 2),
            "blob_value": round(blob_value, 2),
            "criteria": _criteria(
                hue_purity, area_ratio, blob_saturation, blob_value, quality_factor
            ),
        },
    )


def _criteria(
    hue_purity: float,
    area_ratio: float,
    mean_saturation: float,
    mean_value: float,
    quality_factor: float,
) -> dict[str, float]:
    return {
        "hue_purity": round(hue_purity, 4),
        "area_score": round(float(np.clip(area_ratio / AREA_FULL_SCORE, 0.0, 1.0)), 4),
        "saturation_score": round(float(np.clip(mean_saturation / SATURATION_REFERENCE, 0.0, 1.0)), 4),
        "value_score": round(
            float(np.clip((mean_value - VALUE_FLOOR) / VALUE_SATURATION, 0.0, 1.0)), 4
        ),
        "quality_factor": round(quality_factor, 4),
    }


def _confidence(
    *,
    hue_purity: float,
    area_ratio: float,
    mean_saturation: float,
    mean_value: float,
    quality: ImageQuality | None,
) -> float:
    quality_factor = 1.0
    if quality is not None:
        quality_factor = float(np.clip(0.5 * quality.blur_score + 0.5 * quality.exposure_quality, 0.0, 1.0))
    criteria = _criteria(hue_purity, area_ratio, mean_saturation, mean_value, quality_factor)
    return float(np.clip(sum(criteria[k] * _WEIGHTS[k] for k in _WEIGHTS), 0.0, 1.0))


def classify_switch(region_bgr: np.ndarray, *, component_id: str) -> Measurement:
    """Read a two-position selector from the orientation of its lever.

    The lever is segmented as the brightest elongated blob and its principal
    axis is found by PCA over the blob pixels. The lever is reported as ``UP``
    or ``DOWN`` when the axis is within 30 deg of vertical, ``LEFT`` or
    ``RIGHT`` when it is within 30 deg of horizontal, and ``UNKNOWN`` in
    between, because a two-position switch has no mid position to report.
    """
    if region_bgr.size == 0:
        return Measurement(
            component_id=component_id,
            component_type="switch",
            state="UNKNOWN",
            confidence=0.0,
            method="opencv_lever_orientation",
            requires_reinspection=True,
            notes=["the configured switch region falls outside the image"],
        )

    gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return Measurement(
            component_id=component_id,
            component_type="switch",
            state="UNKNOWN",
            confidence=0.0,
            method="opencv_lever_orientation",
            requires_reinspection=True,
            notes=["no lever blob found"],
        )

    largest = max(contours, key=cv2.contourArea)
    if len(largest) < 5 or cv2.contourArea(largest) < 25:
        return Measurement(
            component_id=component_id,
            component_type="switch",
            state="UNKNOWN",
            confidence=0.0,
            method="opencv_lever_orientation",
            requires_reinspection=True,
            notes=["lever blob is too small to measure an orientation"],
        )

    # PCA over the blob pixels gives the lever's principal axis unambiguously;
    # fitEllipse's reported angle convention is version-dependent.
    ys, xs = np.nonzero(mask == 255)
    if ys.size < 30:
        return Measurement(
            component_id=component_id,
            component_type="switch",
            state="UNKNOWN",
            confidence=0.0,
            method="opencv_lever_orientation",
            requires_reinspection=True,
            notes=["lever blob has too few pixels to measure an orientation"],
        )
    points = np.column_stack((ys, xs)).astype(np.float32)
    _, eigenvectors, eigenvalues = cv2.PCACompute2(points, mean=None)
    dy, dx = float(eigenvectors[0][0]), float(eigenvectors[0][1])
    norm = float(np.hypot(dx, dy)) + 1e-9
    dx, dy = dx / norm, dy / norm
    elongation = float(np.sqrt(eigenvalues[0][0] / (eigenvalues[1][0] + 1e-6)))

    # 0 deg = lever upright, 90 deg = lever horizontal.
    deviation = float(np.degrees(np.arccos(np.clip(abs(dy), 0.0, 1.0))))
    alignment = min(deviation, 90.0 - deviation)

    # Which way the lever points, from the blob centroid to its far end.
    centroid_y, centroid_x = float(ys.mean()), float(xs.mean())
    projections = (xs - centroid_x) * dx + (ys - centroid_y) * dy
    tip = projections[int(np.argmax(np.abs(projections)))]
    tip_y = np.sign(tip) * dy
    tip_x = np.sign(tip) * dx

    if alignment <= 30.0:
        if deviation <= 45.0:
            state = "UP" if tip_y < 0 else "DOWN"
        else:
            state = "RIGHT" if tip_x > 0 else "LEFT"
    else:
        state = "UNKNOWN"

    layout_score = float(np.clip((elongation - 1.2) / 1.8, 0.0, 1.0))
    angle_score = float(np.clip(1.0 - alignment / 30.0, 0.0, 1.0))
    confidence = float(np.clip(0.6 * layout_score + 0.4 * angle_score, 0.0, 1.0))
    if state == "UNKNOWN":
        confidence = min(confidence, 0.35)

    return Measurement(
        component_id=component_id,
        component_type="switch",
        state=state,
        confidence=round(confidence, 4),
        method="opencv_lever_orientation",
        requires_reinspection=confidence < 0.55,
        notes=[] if state != "UNKNOWN" else ["the lever is not aligned with either position"],
        details={
            "axis_deviation_from_vertical_deg": round(deviation, 2),
            "elongation": round(elongation, 3),
            "lever_blob_pixels": int(ys.size),
        },
    )


def classify_display(region_bgr: np.ndarray, *, component_id: str) -> Measurement:
    """Report whether a display region is lit, and how bright its segments are.

    This deliberately does not attempt optical character recognition: the
    profile documentation states the display's *meaning*, and the honest
    measurement available from OpenCV here is whether the panel is energised.
    Reading digits is left to the vision-language model, whose output is tagged
    with :data:`~app.models.schemas.Provenance.INFERRED`.
    """
    if region_bgr.size == 0:
        return Measurement(
            component_id=component_id,
            component_type="display",
            state="UNKNOWN",
            confidence=0.0,
            method="opencv_display_luminance",
            requires_reinspection=True,
            notes=["the configured display region falls outside the image"],
        )

    gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
    mean_luma = float(gray.mean())
    # A seven-segment glyph covers a few percent of the display window, so a
    # fixed high percentile (p95) reports the dark background and calls a lit
    # display blank. p98 tracks the glyph strokes, and the lit fraction is
    # bounded on both sides so sensor noise cannot masquerade as segments.
    # Glyph strokes cover roughly 1-3 % of the window, so p99 lands on them
    # while p95 still reports the dark background.
    hi = float(np.percentile(gray, 99))
    lo = float(np.percentile(gray, 50))
    dynamic_range = hi - lo
    stroke_level = 0.6 * hi
    lit_fraction = float(np.count_nonzero(gray > stroke_level)) / float(gray.size)

    lit = hi > 110.0 and dynamic_range > 60.0 and 0.002 <= lit_fraction <= 0.60
    state = "LIT" if lit else "BLANK"
    stroke_score = float(np.clip((hi - 90.0) / 130.0, 0.0, 1.0))
    coverage_score = float(np.clip(lit_fraction / 0.02, 0.0, 1.0))
    confidence = float(np.clip(0.6 * stroke_score + 0.4 * coverage_score, 0.0, 1.0))
    if not lit:
        # A uniformly dark window is strong evidence of a blank display.
        confidence = float(np.clip(0.5 + 0.5 * (1.0 - min(hi / 110.0, 1.0)), 0.5, 1.0))

    return Measurement(
        component_id=component_id,
        component_type="display",
        state=state,
        value=round(mean_luma, 2),
        unit="mean_luma_0_255",
        confidence=round(confidence, 4),
        method="opencv_display_luminance",
        requires_reinspection=confidence < 0.55,
        notes=[] if lit else ["the display area is uniformly dark: no lit segments detected"],
        details={
            "mean_luma": round(mean_luma, 2),
            "p50_luma": round(lo, 2),
            "p98_luma": round(hi, 2),
            "dynamic_range": round(dynamic_range, 2),
            "lit_fraction": round(lit_fraction, 5),
            "criteria": {
                "stroke_score": round(stroke_score, 4),
                "coverage_score": round(coverage_score, 4),
            },
            "provenance_note": "segment and digit interpretation is not performed by OpenCV",
        },
    )


__all__ = [
    "detect_indicator",
    "classify_switch",
    "classify_display",
]
