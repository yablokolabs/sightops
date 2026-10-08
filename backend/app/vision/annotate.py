"""Visual evidence overlays.

Annotations are produced by the vision engine, not by the frontend, so the
picture the user sees is derived from the same numbers the agent reasoned over.
Everything is drawn on a copy; the stored original is never modified.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.models.schemas import AnalysisResult, GaugeState, IndicatorState, Measurement

FONT = cv2.FONT_HERSHEY_SIMPLEX

NAVY = (58, 30, 18)
BLUE = (196, 122, 55)
ORANGE = (0, 138, 255)
GREEN = (110, 190, 90)
RED = (60, 60, 230)
GREY = (170, 170, 170)
WHITE = (255, 255, 255)

_STATE_COLOURS = {
    IndicatorState.RED.value: RED,
    IndicatorState.AMBER.value: ORANGE,
    IndicatorState.GREEN.value: GREEN,
    IndicatorState.BLUE.value: BLUE,
    IndicatorState.WHITE.value: WHITE,
    IndicatorState.OFF.value: GREY,
    IndicatorState.UNKNOWN.value: ORANGE,
    GaugeState.HIGH.value: RED,
    GaugeState.NORMAL.value: GREEN,
    GaugeState.LOW.value: ORANGE,
    GaugeState.UNKNOWN.value: ORANGE,
}


def _label(image: np.ndarray, text: str, origin: tuple[int, int], colour: tuple[int, int, int]) -> None:
    """Draw a filled caption so text stays readable over any background."""
    font_scale = 0.46
    thickness = 1
    (text_width, text_height), baseline = cv2.getTextSize(text, FONT, font_scale, thickness)
    x, y = origin
    x = max(0, min(x, image.shape[1] - text_width - 8))
    y = max(text_height + 6, min(y, image.shape[0] - 4))
    cv2.rectangle(
        image,
        (x - 4, y - text_height - 4),
        (x + text_width + 4, y + baseline),
        NAVY,
        thickness=cv2.FILLED,
    )
    cv2.putText(image, text, (x, y), FONT, font_scale, colour, thickness, cv2.LINE_AA)


def _measurement_caption(measurement: Measurement) -> str:
    if measurement.component_type == "analog_gauge":
        if measurement.value is None:
            return f"{measurement.component_id}: UNREADABLE ({measurement.confidence:.0%})"
        return (
            f"{measurement.component_id}: {measurement.value:g} {measurement.unit or ''}"
            f" [{measurement.state}] ({measurement.confidence:.0%})"
        )
    if measurement.component_type == "indicator":
        return f"{measurement.component_id}: {measurement.state} ({measurement.confidence:.0%})"
    if measurement.component_type == "switch":
        return f"{measurement.component_id}: {measurement.state} ({measurement.confidence:.0%})"
    if measurement.component_type == "display":
        return f"{measurement.component_id}: {measurement.state} ({measurement.confidence:.0%})"
    return f"{measurement.component_id} ({measurement.confidence:.0%})"


def draw_analysis(bgr: np.ndarray, analysis: AnalysisResult) -> np.ndarray:
    """Return an annotated copy of ``bgr`` for the given analysis."""
    canvas = bgr.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    height, width = canvas.shape[:2]

    for region in analysis.regions:
        x, y, w, h = region.box
        measurement = region.measurements[0] if region.measurements else None
        colour = GREY
        if measurement is not None:
            colour = _STATE_COLOURS.get((measurement.state or "").upper(), BLUE)

        cv2.rectangle(canvas, (x, y), (x + w, y + h), colour, 2)

        if measurement is not None:
            _label(canvas, _measurement_caption(measurement), (x, max(16, y - 8)), colour)

            if measurement.component_type == "analog_gauge" and measurement.details:
                centre = measurement.details.get("dial_center")
                radius = measurement.details.get("dial_radius")
                angle = measurement.details.get("needle_angle_deg")
                if centre and radius and angle is not None:
                    cx, cy = int(centre[0]) + x, int(centre[1]) + y
                    cv2.circle(canvas, (cx, cy), int(radius), colour, 1)
                    radians = np.radians(float(angle))
                    needle_length = 0.72 * float(radius)
                    tip = (
                        int(cx + np.sin(radians) * needle_length),
                        int(cy - np.cos(radians) * needle_length),
                    )
                    cv2.arrowedLine(canvas, (cx, cy), tip, colour, 2, tipLength=0.18)
                    cv2.circle(canvas, (cx, cy), 3, colour, cv2.FILLED)

            if measurement.component_type == "indicator":
                centre = (x + w // 2, y + h // 2)
                cv2.circle(canvas, centre, max(w, h) // 2, colour, 1)

    header = (
        f"SightOps evidence  |  OpenCV {analysis.opencv_version}  |  "
        f"profile {analysis.profile_id}  |  image {analysis.image_id[:8]}"
    )
    _label(canvas, header, (8, 20), WHITE)

    quality = analysis.quality
    footer = (
        f"blur {quality.blur_score:.2f}  exposure {quality.exposure_quality:.2f}  "
        f"{quality.width}x{quality.height}"
    )
    _label(canvas, footer, (8, height - 10), WHITE)

    if quality.requires_new_view and quality.reason:
        _label(canvas, f"REINSPECTION ADVISED: {quality.reason}", (8, height - 34), ORANGE)

    return canvas


def encode_png(bgr: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".png", bgr)
    if not ok:  # pragma: no cover - imencode only fails on an empty array
        raise RuntimeError("failed to encode annotated evidence as PNG")
    return buffer.tobytes()
