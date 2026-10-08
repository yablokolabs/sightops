"""Automatic region detection.

The demonstrator reads components from *configured* profile regions, which the
profile marks ``source="configured"``. This module adds the complementary
capability the agent needs when the configured geometry does not fit — finding
the panel itself — and reports it as ``detected`` so the distinction survives
into the UI.

Confidence is rectangularity (contour area over convex-hull area) blended with
how much of the frame the panel occupies: a large, clean quadrilateral is a
panel; a small or ragged one is probably a shadow or a bracket.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.vision.preprocess import order_quad


class DetectedPanel:
    def __init__(self, quad: np.ndarray, confidence: float, area_ratio: float, sides: int) -> None:
        self.quad = quad
        self.confidence = confidence
        self.area_ratio = area_ratio
        self.sides = sides

    def normalised_box(self, width: int, height: int) -> dict[str, float]:
        xs = self.quad[:, 0] / width
        ys = self.quad[:, 1] / height
        return {
            "x": round(float(xs.min()), 4),
            "y": round(float(ys.min()), 4),
            "w": round(float(xs.max() - xs.min()), 4),
            "h": round(float(ys.max() - ys.min()), 4),
        }


def detect_panel(bgr: np.ndarray, min_area_ratio: float = 0.08) -> DetectedPanel | None:
    """Find the dominant panel-shaped quadrilateral in a frame."""
    if bgr.size == 0:
        return None

    height, width = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 120)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best: DetectedPanel | None = None
    for contour in contours:
        area = float(cv2.contourArea(contour))
        area_ratio = area / float(height * width)
        if area_ratio < min_area_ratio:
            continue

        hull_area = float(cv2.contourArea(cv2.convexHull(contour)))
        if hull_area <= 0:
            continue
        rectangularity = float(np.clip(area / hull_area, 0.0, 1.0))

        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        sides = len(approx)

        # Prefer a clean quadrilateral; a 4-gon scores full marks, and more
        # complex outlines are penalised only mildly so a panel with a cut-out
        # is still usable as a bounding region.
        shape_score = 1.0 if sides == 4 else max(0.4, 1.0 - abs(sides - 4) * 0.12)
        size_score = float(np.clip(area_ratio / 0.45, 0.0, 1.0))
        confidence = float(
            np.clip(0.5 * rectangularity + 0.25 * shape_score + 0.25 * size_score, 0.0, 1.0)
        )

        if best is None or confidence > best.confidence:
            if sides == 4:
                quad = approx.reshape(4, 2).astype(np.float32)
            else:
                quad = cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float32)
            best = DetectedPanel(order_quad(quad), confidence, area_ratio, sides)

    return best
