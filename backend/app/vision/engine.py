"""The OpenCV vision engine.

This is the only place that turns pixels into measurements. Every other layer
— the agent, the API, the UI — consumes :class:`~app.models.schemas.Measurement`
objects that carry their method, their confidence and the criteria behind that
confidence.

The engine verifies the OpenCV version at import and refuses to present itself
as OpenCV 5 when it is not, because the competition claims in the README depend
on that being true.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from app.config import Settings, get_settings
from app.models.schemas import (
    AnalysisResult,
    ImageQuality,
    Measurement,
    Provenance,
    RegionAnalysis,
)
from app.vision import indicators, quality as quality_module
from app.vision.gauges import read_gauge
from app.vision.preprocess import gray_of, to_working_copy
from app.vision.profiles import EquipmentProfile

#: The major version SightOps reports on. A mismatch is surfaced, not hidden.
EXPECTED_OPENCV_MAJOR = 5


class ImageValidationError(ValueError):
    """Raised when an upload cannot be trusted as an image."""


def opencv_version() -> str:
    return cv2.__version__


def opencv_major() -> int:
    return int(cv2.__version__.split(".")[0])


class VisionEngine:
    """Stateless apart from configuration; safe to share across requests."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # -- ingestion ----------------------------------------------------------

    def decode(self, data: bytes) -> np.ndarray:
        """Decode uploaded bytes into a BGR array, rejecting hostile input.

        Guards file size, decode failure and pixel count before anything is
        handed to the vision pipeline: a decompression bomb must not be able to
        exhaust the box.
        """
        if not data:
            raise ImageValidationError("the uploaded file is empty")
        if len(data) > self.settings.max_upload_bytes:
            raise ImageValidationError(
                f"the uploaded file is {len(data)} bytes, above the "
                f"{self.settings.max_upload_bytes} byte limit"
            )

        buffer = np.frombuffer(data, dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None:
            raise ImageValidationError("the uploaded file could not be decoded as an image")

        height, width = image.shape[:2]
        if width < 32 or height < 32:
            raise ImageValidationError(f"the image is only {width}x{height} px")
        if width * height > self.settings.max_image_pixels:
            raise ImageValidationError(
                f"the image is {width}x{height} px, above the "
                f"{self.settings.max_image_pixels} pixel limit"
            )
        return image

    # -- analysis -----------------------------------------------------------

    def analyze(
        self,
        image_bgr: np.ndarray,
        *,
        image_id: str,
        profile: EquipmentProfile,
        rectify: bool = False,
    ) -> AnalysisResult:
        """Measure every configured region of ``profile`` in ``image_bgr``."""
        started = time.perf_counter()
        working, ops = to_working_copy(image_bgr)
        if rectify:
            from app.vision.preprocess import auto_perspective

            working, quad, rectified_ops = auto_perspective(working)
            if quad is not None:
                ops.extend(rectified_ops)

        frame_quality = quality_module.assess(
            working,
            blur_threshold=self.settings.blur_threshold,
            dark_threshold=self.settings.dark_exposure_threshold,
            bright_threshold=self.settings.bright_exposure_threshold,
            min_region_pixels=self.settings.min_region_pixels,
        )

        height, width = working.shape[:2]
        regions: list[RegionAnalysis] = []
        measurements: list[Measurement] = []

        for spec in profile.regions:
            box = spec.pixel_box(width, height)
            crop = working[box[1] : box[1] + box[3], box[0] : box[0] + box[2]]
            region_quality = self._region_quality(crop, spec.region_id)
            measurement = self._measure(crop, spec, region_quality)
            regions.append(
                RegionAnalysis(
                    region_id=spec.region_id,
                    kind=spec.kind,
                    label=spec.label,
                    box=box,
                    measurements=[measurement],
                    quality=region_quality,
                )
            )
            measurements.append(measurement)

        low = [m for m in measurements if m.requires_reinspection]
        if low:
            frame_quality.requires_new_view = True
            detail = "; ".join(
                f"{m.component_id} ({m.confidence:.0%})" for m in low
            )
            frame_quality.reason = (
                f"{len(low)} of {len(measurements)} components need a better view: {detail}"
            )

        return AnalysisResult(
            image_id=image_id,
            opencv_version=opencv_version(),
            profile_id=profile.profile_id,
            quality=frame_quality,
            regions=regions,
            measurements=measurements,
            preprocessing=ops,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
        )

    def analyze_region(
        self,
        image_bgr: np.ndarray,
        *,
        image_id: str,
        profile: EquipmentProfile,
        region_id: str,
    ) -> RegionAnalysis:
        """Measure one named region — the ``inspect_region`` tool's workhorse."""
        spec = profile.region(region_id)
        if spec is None:
            raise KeyError(region_id)

        working, _ = to_working_copy(image_bgr)
        height, width = working.shape[:2]
        box = spec.pixel_box(width, height)
        crop = working[box[1] : box[1] + box[3], box[0] : box[0] + box[2]]
        region_quality = self._region_quality(crop, spec.region_id)
        return RegionAnalysis(
            region_id=spec.region_id,
            kind=spec.kind,
            label=spec.label,
            box=box,
            measurements=[self._measure(crop, spec, region_quality)],
            quality=region_quality,
        )

    def _region_quality(self, crop: np.ndarray, region_id: str) -> ImageQuality:
        """Quality of one component crop.

        The frame-level short-edge rule is deliberately replaced by the much
        smaller region bound: a 140x90 px indicator window is a perfectly good
        crop, and judged against the full-frame 480 px rule every indicator
        would be flagged as too small to read.
        """
        return quality_module.assess(
            crop,
            region_id=region_id,
            blur_threshold=self.settings.blur_threshold,
            dark_threshold=self.settings.dark_exposure_threshold,
            bright_threshold=self.settings.bright_exposure_threshold,
            min_region_pixels=self.settings.min_region_pixels,
            min_short_edge=self.settings.min_region_short_edge,
        )

    def check_quality(
        self,
        image_bgr: np.ndarray,
        region_id: str | None = None,
        profile: EquipmentProfile | None = None,
    ) -> ImageQuality:
        working, _ = to_working_copy(image_bgr)
        if region_id is not None and profile is not None:
            spec = profile.region(region_id)
            if spec is not None:
                height, width = working.shape[:2]
                box = spec.pixel_box(width, height)
                crop = working[box[1] : box[1] + box[3], box[0] : box[0] + box[2]]
                return self._region_quality(crop, region_id)
        return quality_module.assess(
            working,
            region_id=region_id,
            blur_threshold=self.settings.blur_threshold,
            dark_threshold=self.settings.dark_exposure_threshold,
            bright_threshold=self.settings.bright_exposure_threshold,
            min_region_pixels=self.settings.min_region_pixels,
        )

    # -- per-region dispatch ------------------------------------------------

    def _measure(
        self, crop: np.ndarray, spec, region_quality: ImageQuality
    ) -> Measurement:
        if spec.kind == "gauge":
            return read_gauge(crop, spec, quality=region_quality)
        if spec.kind == "indicator":
            return indicators.detect_indicator(
                crop, component_id=spec.region_id, quality=region_quality
            )
        if spec.kind == "switch":
            return indicators.classify_switch(crop, component_id=spec.region_id)
        if spec.kind == "display":
            return indicators.classify_display(crop, component_id=spec.region_id)
        return self._panel_measurement(crop, spec, region_quality)

    def _panel_measurement(self, crop, spec, region_quality) -> Measurement:
        from app.vision.regions import detect_panel

        grey = gray_of(crop)
        panel = detect_panel(crop)
        if panel is None:
            confidence = float(np.clip(region_quality.blur_score, 0.0, 1.0))
            return Measurement(
                component_id=spec.region_id,
                component_type="panel",
                state="UNKNOWN",
                confidence=round(min(confidence, 0.4), 4),
                method="opencv_contour_quadrilateral",
                requires_reinspection=True,
                notes=["no panel-shaped region was found"],
                details={"region_mean_luma": round(float(grey.mean()), 2)},
            )
        return Measurement(
            component_id=spec.region_id,
            component_type="panel",
            state="DETECTED",
            confidence=round(panel.confidence, 4),
            method="opencv_contour_quadrilateral",
            provenance=Provenance.MEASURED,
            requires_reinspection=panel.confidence < 0.55,
            notes=[],
            details={
                "area_ratio": round(panel.area_ratio, 4),
                "sides": panel.sides,
                "region_mean_luma": round(float(grey.mean()), 2),
            },
        )


def version_report() -> dict[str, object]:
    """Diagnostics surfaced by ``/api/system/status`` and the README."""
    major = opencv_major()
    return {
        "opencv_version": cv2.__version__,
        "opencv_major": major,
        "is_opencv_5": major >= EXPECTED_OPENCV_MAJOR,
    }
