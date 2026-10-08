"""Change detection between two observations.

Two layers, both real:

* **Structured diff** — compares the measurements of two analyses component by
  component. This is the layer the agent reasons over, because it is stated in
  engineering units rather than in pixels.
* **Pixel diff** — an absolute-difference metric over the two frames, reported
  as context. It is deliberately *not* used to infer component state: a pixel
  difference cannot say whether a red lamp is a warning or simply a reflection.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.models.schemas import (
    AnalysisResult,
    ChangeEvent,
    ChangeReport,
    GaugeState,
    Provenance,
    Severity,
)

#: Indicator transitions and how serious each one is.
_INDICATOR_TRANSITIONS: dict[tuple[str, str], Severity] = {
    ("GREEN", "RED"): Severity.HIGH,
    ("GREEN", "AMBER"): Severity.MEDIUM,
    ("AMBER", "RED"): Severity.HIGH,
    ("RED", "GREEN"): Severity.INFO,
    ("OFF", "RED"): Severity.HIGH,
    ("OFF", "AMBER"): Severity.MEDIUM,
    ("OFF", "GREEN"): Severity.INFO,
    ("GREEN", "OFF"): Severity.MEDIUM,
    ("RED", "OFF"): Severity.MEDIUM,
}


def pixel_difference(
    previous: np.ndarray, current: np.ndarray
) -> tuple[float, np.ndarray] | tuple[None, None]:
    """Mean absolute grey-level difference and the difference image."""
    if previous is None or current is None or previous.size == 0 or current.size == 0:
        return None, None
    if previous.shape[:2] != current.shape[:2]:
        current = cv2.resize(current, (previous.shape[1], previous.shape[0]), interpolation=cv2.INTER_AREA)
    prev_gray = cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY) if previous.ndim == 3 else previous
    curr_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY) if current.ndim == 3 else current
    difference = cv2.absdiff(prev_gray, curr_gray)
    return float(difference.mean()) / 255.0, difference


def compare_analyses(
    previous: AnalysisResult,
    current: AnalysisResult,
    *,
    pixel_mean_abs_diff: float | None = None,
) -> ChangeReport:
    """Diff two analyses component by component, with severity per change."""
    report = ChangeReport(
        previous_image_id=previous.image_id,
        current_image_id=current.image_id,
    )
    previous_by_id = {m.component_id: m for m in previous.measurements}

    for measurement in current.measurements:
        before = previous_by_id.get(measurement.component_id)
        if before is None or before.provenance != Provenance.MEASURED:
            report.changes.append(
                ChangeEvent(
                    component_id=measurement.component_id,
                    description=(
                        f"{measurement.component_id} was measured for the first time in this "
                        f"observation as {_describe(measurement)}"
                    ),
                    previous=None,
                    current=_describe(measurement),
                    severity=Severity.INFO,
                )
            )
            continue

        if measurement.component_type == "analog_gauge":
            if before.value is None or measurement.value is None:
                if before.value is None and measurement.value is not None:
                    report.changes.append(
                        ChangeEvent(
                            component_id=measurement.component_id,
                            description=(
                                f"{measurement.component_id} became readable: "
                                f"{measurement.value:g} {measurement.unit or ''}"
                            ),
                            previous="UNREADABLE",
                            current=f"{measurement.value:g} {measurement.unit or ''}",
                            severity=Severity.INFO,
                        )
                    )
                continue

            delta = measurement.value - before.value
            if abs(delta) < 1e-6:
                continue
            severity = Severity.INFO
            if measurement.state == GaugeState.HIGH and before.state != GaugeState.HIGH:
                severity = Severity.CRITICAL
            elif abs(delta) > 5.0:
                severity = Severity.MEDIUM
            report.changes.append(
                ChangeEvent(
                    component_id=measurement.component_id,
                    description=(
                        f"{measurement.component_id} moved {delta:+.1f} {measurement.unit or ''} "
                        f"({before.value:g} to {measurement.value:g})"
                    ),
                    previous=f"{before.value:g} {before.unit or ''}",
                    current=f"{measurement.value:g} {measurement.unit or ''}",
                    severity=severity,
                )
            )
            continue

        if before.state != measurement.state:
            severity = _INDICATOR_TRANSITIONS.get(
                (before.state or "", measurement.state or ""), Severity.MEDIUM
            )
            report.changes.append(
                ChangeEvent(
                    component_id=measurement.component_id,
                    description=(
                        f"{measurement.component_id} changed from {before.state} to "
                        f"{measurement.state}"
                    ),
                    previous=before.state,
                    current=measurement.state,
                    severity=severity,
                )
            )

    if pixel_mean_abs_diff is not None:
        report.changes.append(
            ChangeEvent(
                component_id="panel_pixels",
                description=(
                    f"mean absolute pixel difference across the frame is "
                    f"{pixel_mean_abs_diff:.3f} (scale 0..1)"
                ),
                current=f"{pixel_mean_abs_diff:.4f}",
                severity=Severity.INFO,
            )
        )
    return report


def _describe(measurement) -> str:
    if measurement.value is not None:
        return f"{measurement.value:g} {measurement.unit or ''}".strip()
    return str(measurement.state)
