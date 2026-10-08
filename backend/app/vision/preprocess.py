"""Image preprocessing and region extraction.

Preprocessing here is deliberately non-destructive: the original upload is kept
byte-for-byte, every operation returns a new array, and the caller records which
operations ran in ``AnalysisResult.preprocessing`` so a measurement can always
be traced back to the pixels it came from.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.models.schemas import RegionSpec

#: Longest edge the working copy is reduced to before analysis. Larger uploads
#: are downscaled (INTER_AREA) so that a phone photo and a screen capture end up
#: in the same working range; the original is untouched on disk.
WORKING_LONG_EDGE = 1280


def to_working_copy(bgr: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Downscale oversized frames and normalise the channel layout."""
    ops: list[str] = []
    image = bgr
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        ops.append("gray_to_bgr")
    elif image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        ops.append("bgra_to_bgr")

    height, width = image.shape[:2]
    longest = max(height, width)
    if longest > WORKING_LONG_EDGE:
        scale = WORKING_LONG_EDGE / longest
        image = cv2.resize(
            image,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
        ops.append(f"downscale_{longest}_to_{WORKING_LONG_EDGE}")
    return image, ops


def denoise(bgr: np.ndarray) -> np.ndarray:
    """Edge-preserving denoise that keeps LED and needle edges intact."""
    return cv2.bilateralFilter(bgr, d=5, sigmaColor=40, sigmaSpace=40)


def clahe_luminance(bgr: np.ndarray, clip_limit: float = 2.0) -> np.ndarray:
    """Contrast-limited adaptive histogram equalisation on the L channel."""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    merged = cv2.merge((clahe.apply(l_channel), a_channel, b_channel))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def gray_of(bgr: np.ndarray) -> np.ndarray:
    return bgr if bgr.ndim == 2 else cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def crop_region(bgr: np.ndarray, spec: RegionSpec) -> np.ndarray:
    """Crop a normalised region spec out of a frame."""
    height, width = bgr.shape[:2]
    x, y, w, h = spec.pixel_box(width, height)
    return bgr[y : y + h, x : x + w]


def upscale_for_measurement(region: np.ndarray, target_short_edge: int = 240) -> np.ndarray:
    """Magnify a small region so sub-pixel needle geometry is workable.

    Upscaling cannot recover detail that was never captured — the quality
    assessment is what reports that — but it does let the gauge geometry code
    operate at a consistent scale.
    """
    if region.size == 0:
        return region
    height, width = region.shape[:2]
    short = min(height, width)
    if short >= target_short_edge:
        return region
    scale = target_short_edge / short
    return cv2.resize(
        region,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_CUBIC,
    )


def order_quad(points: np.ndarray) -> np.ndarray:
    """Order four points as top-left, top-right, bottom-right, bottom-left."""
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    ordered = np.zeros((4, 2), dtype=np.float32)
    total = points.sum(axis=1)
    diff = np.diff(points, axis=1).ravel()
    ordered[0] = points[np.argmin(total)]
    ordered[2] = points[np.argmax(total)]
    ordered[1] = points[np.argmin(diff)]
    ordered[3] = points[np.argmax(diff)]
    return ordered


def warp_quad(
    bgr: np.ndarray, quad: np.ndarray, output_size: tuple[int, int]
) -> np.ndarray:
    """Perspective-correct a quadrilateral into an axis-aligned rectangle."""
    source = order_quad(quad)
    width, height = output_size
    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
    )
    matrix = cv2.getPerspectiveTransform(source, destination)
    return cv2.warpPerspective(bgr, matrix, (width, height), flags=cv2.INTER_LINEAR)


def auto_perspective(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray | None, list[str]]:
    """Detect the dominant bright quadrilateral and rectify it.

    Returns the (possibly rectified) frame, the quadrilateral used, and the list
    of operations applied. When nothing convincing is found the frame is
    returned unchanged — an unrectified frame with an honest quality score is
    more useful than a badly warped one.
    """
    height, width = bgr.shape[:2]
    gray = gray_of(bgr)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 120)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best: np.ndarray | None = None
    best_area = 0.0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 0.15 * height * width:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        if area > best_area:
            best_area = area
            best = approx.reshape(4, 2).astype(np.float32)

    if best is None:
        return bgr, None, []

    quad = order_quad(best)
    out_width = int(max(np.linalg.norm(quad[1] - quad[0]), np.linalg.norm(quad[2] - quad[3])))
    out_height = int(max(np.linalg.norm(quad[3] - quad[0]), np.linalg.norm(quad[2] - quad[1])))
    if out_width < 64 or out_height < 64:
        return bgr, None, []
    rectified = warp_quad(bgr, quad, (out_width, out_height))
    return rectified, quad, ["perspective_rectified"]
