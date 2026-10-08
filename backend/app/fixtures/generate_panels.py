"""Synthetic equipment panels with ground truth.

Every evaluation fixture and every demonstration image in SightOps is drawn
here, from known parameters, so the ground truth is exact rather than
hand-labelled. That matters: a gauge fixture knows the needle is at 87.0 PSI
because it *drew* the needle at that angle, which is what makes the absolute
error reported in ``docs/evaluation/results.md`` meaningful.

Component positions match :mod:`app.vision.profiles` exactly, so the configured
regions and the fixtures agree by construction. Degradations (blur, exposure,
glare, perspective, scale, sensor noise) are applied to the finished panel so a
fixture can be made deliberately hard without moving any component.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.vision.profiles import DISHWASHER_PANEL, INDUSTRIAL_PANEL

PANEL_WIDTH, PANEL_HEIGHT = 1280, 720

# -- palette (BGR) ----------------------------------------------------------
PANEL_BG = (48, 42, 34)
PANEL_EDGE = (86, 78, 66)
DIAL_FACE = (238, 240, 236)
DIAL_RIM = (70, 72, 76)
NEEDLE = (24, 24, 30)
MARKING = (58, 58, 64)
HUB = (40, 42, 46)

LED_ON = {
    "RED": (0, 0, 232),
    "GREEN": (86, 220, 120),
    "AMBER": (0, 168, 255),
    "OFF": (30, 32, 36),
    "UNKNOWN": (30, 32, 36),
}

#: Dial geometry, in pixels, for the industrial gauge region.
GAUGE_RADIUS = 165
GAUGE_CENTRE_LOCAL = (240.0, 187.0)  # inside the gauge region crop


@dataclass
class Degradation:
    """Applied after the panel is drawn, so it never moves a component."""

    blur_sigma: float = 0.0
    brightness: float = 1.0
    glare: float = 0.0
    rotation_deg: float = 0.0
    perspective: float = 0.0
    #: Simulates a distant subject or a coarse sensor: the frame is resampled
    #: down and back up, so components stay where the profile says they are
    #: while the detail that was never captured is genuinely gone.
    resolution_scale: float = 1.0
    noise_sigma: float = 0.0
    jpeg_quality: int | None = None


@dataclass
class PanelScene:
    image: np.ndarray
    ground_truth: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------


def _canvas(width: int, height: int, background: tuple[int, int, int]) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:] = background
    return image


def _gauge_geometry(spec) -> tuple[float, float, float]:
    """Absolute dial centre and radius for the configured gauge region."""
    width, height = PANEL_WIDTH, PANEL_HEIGHT
    x, y, w, h = spec.pixel_box(width, height)
    cx = x + w * (GAUGE_CENTRE_LOCAL[0] / 480.0)
    cy = y + h * (GAUGE_CENTRE_LOCAL[1] / 374.0)
    return cx, cy, float(GAUGE_RADIUS)


def pressure_to_angle(psi: float, spec) -> float:
    """Clock angle (0 deg at 12 o'clock, clockwise) for a pressure reading."""
    span = spec.end_angle_deg - spec.start_angle_deg
    fraction = (psi - spec.scale_min) / (spec.scale_max - spec.scale_min)
    return spec.start_angle_deg + fraction * span


def _polar(cx: float, cy: float, radius: float, angle_deg: float) -> tuple[int, int]:
    radians = math.radians(angle_deg)
    return int(round(cx + math.sin(radians) * radius)), int(round(cy - math.cos(radians) * radius))


def _draw_gauge(image: np.ndarray, pressure_psi: float) -> None:
    spec = INDUSTRIAL_PANEL.gauge
    cx, cy, radius = _gauge_geometry(spec)
    centre = (int(cx), int(cy))

    cv2.circle(image, centre, int(radius) + 8, PANEL_EDGE, -1)
    cv2.circle(image, centre, int(radius), DIAL_FACE, -1)
    cv2.circle(image, centre, int(radius), DIAL_RIM, 3)

    # Ticks and numerals sit outside the 0.28R-0.72R sampling band so the needle
    # stays the only feature the radial scan can see.
    for step in range(0, 11):
        psi = spec.scale_min + (spec.scale_max - spec.scale_min) * step / 10.0
        angle = pressure_to_angle(psi, spec)
        major = step % 2 == 0
        inner = radius * (0.82 if major else 0.86)
        outer = radius * 0.94
        pt1 = _polar(cx, cy, inner, angle)
        pt2 = _polar(cx, cy, outer, angle)
        cv2.line(image, pt1, pt2, MARKING, 3 if major else 1, cv2.LINE_AA)
        if major:
            tx, ty = _polar(cx, cy, radius * 0.70, angle)
            # Push the numeral outward along the same ray by its own width.
            ox, oy = int((tx - cx) * 0.30), int((ty - cy) * 0.30)
            cv2.putText(
                image,
                f"{int(psi)}",
                (tx + ox - 14, ty + oy + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                MARKING,
                1,
                cv2.LINE_AA,
            )

    cv2.putText(
        image,
        "PSI",
        (int(cx) - 20, int(cy) + int(radius * 0.42)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        MARKING,
        1,
        cv2.LINE_AA,
    )

    needle_angle = pressure_to_angle(pressure_psi, spec)
    tip = _polar(cx, cy, radius * 0.80, needle_angle)
    cv2.line(image, centre, tip, NEEDLE, 6, cv2.LINE_AA)
    cv2.circle(image, centre, 15, HUB, -1)
    cv2.circle(image, centre, 7, (150, 150, 155), -1)


def _draw_led(image: np.ndarray, spec, state: str) -> None:
    x, y, w, h = spec.pixel_box(PANEL_WIDTH, PANEL_HEIGHT)
    cx, cy = x + w // 2, y + h // 2
    radius = int(min(w, h) * 0.32)

    cv2.circle(image, (cx, cy), radius + 7, (26, 24, 22), -1)
    colour = LED_ON.get(state, LED_ON["OFF"])
    if state != "OFF":
        # A soft halo makes segmentation realistic rather than a hard-edged disc.
        halo = np.zeros_like(image)
        cv2.circle(halo, (cx, cy), radius + 12, colour, -1)
        image[:] = cv2.addWeighted(image, 1.0, cv2.GaussianBlur(halo, (31, 31), 8), 0.35, 0)
        cv2.circle(image, (cx, cy), radius, colour, -1)
        cv2.circle(image, (cx, cy), max(2, radius // 3), (240, 245, 255), -1)
    else:
        cv2.circle(image, (cx, cy), radius, colour, -1)


def _draw_switch(image: np.ndarray, spec, position: str) -> None:
    x, y, w, h = spec.pixel_box(PANEL_WIDTH, PANEL_HEIGHT)
    cv2.rectangle(image, (x, y), (x + w, y + h), (34, 30, 26), -1)
    cx, cy = x + w // 2, y + h // 2
    lever_length, lever_width = int(h * 0.34), 22

    if position == "UP":
        cv2.rectangle(
            image,
            (cx - lever_width // 2, cy - lever_length),
            (cx + lever_width // 2, cy),
            (196, 200, 205),
            -1,
        )
    elif position == "DOWN":
        cv2.rectangle(
            image,
            (cx - lever_width // 2, cy),
            (cx + lever_width // 2, cy + lever_length),
            (196, 200, 205),
            -1,
        )
    elif position == "RIGHT":
        cv2.rectangle(
            image,
            (cx, cy - lever_width // 2),
            (cx + lever_length, cy + lever_width // 2),
            (196, 200, 205),
            -1,
        )
    else:  # LEFT
        cv2.rectangle(
            image,
            (cx - lever_length, cy - lever_width // 2),
            (cx, cy + lever_width // 2),
            (196, 200, 205),
            -1,
        )
    cv2.circle(image, (cx, cy), lever_width, (150, 154, 160), -1)
    cv2.circle(image, (cx, cy), lever_width - 6, (120, 124, 130), -1)


def _draw_display(image: np.ndarray, spec, lit: bool, glyph: str) -> None:
    x, y, w, h = spec.pixel_box(PANEL_WIDTH, PANEL_HEIGHT)
    cv2.rectangle(image, (x, y), (x + w, y + h), (20, 22, 26), -1)
    if lit:
        for index, char in enumerate(glyph):
            cv2.putText(
                image,
                char,
                (x + 18 + index * 46, y + h - 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.35,
                (170, 220, 235),
                3,
                cv2.LINE_AA,
            )
    cv2.rectangle(image, (x, y), (x + w, y + h), (70, 74, 80), 2)


# --------------------------------------------------------------------------
# scenes
# --------------------------------------------------------------------------


def _apply_degredation(image: np.ndarray, degrade: Degradation, rng: np.random.Generator) -> np.ndarray:
    out = image
    if degrade.perspective > 0:
        height, width = out.shape[:2]
        amount = degrade.perspective
        source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
        destination = np.float32(
            [
                [width * amount * 0.6, height * amount * 0.25],
                [width - 1 - width * amount * 0.2, 0],
                [width - 1, height - 1 - height * amount * 0.3],
                [width * amount * 0.1, height - 1],
            ]
        )
        matrix = cv2.getPerspectiveTransform(source, destination)
        out = cv2.warpPerspective(out, matrix, (width, height), borderValue=PANEL_BG)

    if degrade.rotation_deg:
        height, width = out.shape[:2]
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrade.rotation_deg, 1.0)
        out = cv2.warpAffine(out, matrix, (width, height), borderValue=PANEL_BG)

    if degrade.resolution_scale != 1.0:
        height, width = out.shape[:2]
        small = (
            max(1, int(width * degrade.resolution_scale)),
            max(1, int(height * degrade.resolution_scale)),
        )
        out = cv2.resize(out, small, interpolation=cv2.INTER_AREA)
        out = cv2.resize(out, (width, height), interpolation=cv2.INTER_LINEAR)

    if degrade.glare > 0:
        height, width = out.shape[:2]
        glare = np.zeros((height, width), dtype=np.float32)
        cv2.circle(glare, (int(width * 0.30), int(height * 0.24)), int(width * 0.22), 255, -1)
        glare = cv2.GaussianBlur(glare, (151, 151), 0) / 255.0
        out = np.clip(out.astype(np.float32) + glare[:, :, None] * 255.0 * degrade.glare, 0, 255).astype(np.uint8)

    if degrade.blur_sigma > 0:
        kernel = int(degrade.blur_sigma * 4) | 1
        out = cv2.GaussianBlur(out, (kernel, kernel), degrade.blur_sigma)

    if degrade.brightness != 1.0:
        out = np.clip(out.astype(np.float32) * degrade.brightness, 0, 255).astype(np.uint8)

    if degrade.noise_sigma > 0:
        noise = rng.normal(0.0, degrade.noise_sigma, out.shape).astype(np.float32)
        out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    return out


def render_industrial_panel(
    *,
    pressure_psi: float = 42.0,
    warning: str = "OFF",
    status: str = "GREEN",
    switch: str = "UP",
    degrade: Degradation | None = None,
    seed: int = 7,
) -> PanelScene:
    """Draw the mock pump-station panel and return it with exact ground truth."""
    rng = np.random.default_rng(seed)
    image = _canvas(PANEL_WIDTH, PANEL_HEIGHT, PANEL_BG)

    cv2.rectangle(image, (40, 40), (PANEL_WIDTH - 40, PANEL_HEIGHT - 40), (34, 30, 26), -1)
    cv2.rectangle(image, (40, 40), (PANEL_WIDTH - 40, PANEL_HEIGHT - 40), PANEL_EDGE, 4)

    _draw_gauge(image, pressure_psi)
    _draw_led(image, INDUSTRIAL_PANEL.region("warning_led_01"), warning)
    _draw_led(image, INDUSTRIAL_PANEL.region("status_led_01"), status)
    _draw_switch(image, INDUSTRIAL_PANEL.region("selector_switch_01"), switch)

    cv2.putText(
        image, "PUMP STATION 01", (100, 660), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 154, 160), 2, cv2.LINE_AA
    )
    cv2.putText(
        image, "MOCK PANEL - NOT CONNECTED TO PLANT", (700, 660), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 124, 130), 1, cv2.LINE_AA
    )

    if degrade is not None:
        image = _apply_degredation(image, degrade, rng)

    ground_truth = {
        "profile_id": INDUSTRIAL_PANEL.profile_id,
        "pressure_psi": float(pressure_psi),
        "needle_angle_deg": round(pressure_to_angle(pressure_psi, INDUSTRIAL_PANEL.gauge), 3),
        "warning_led": warning,
        "status_led": status,
        "switch": switch,
        "expected_gauge_state": "HIGH" if pressure_psi > INDUSTRIAL_PANEL.gauge.warn_above else "NORMAL",
        "degradation": _degradation_dict(degrade),
    }
    return PanelScene(image=image, ground_truth=ground_truth)


def render_dishwasher_panel(
    *,
    lit: bool = True,
    glyph: str = "1:42",
    power: str = "GREEN",
    start: str = "OFF",
    degrade: Degradation | None = None,
    seed: int = 11,
) -> PanelScene:
    """Draw the mock dishwasher fascia and return it with ground truth."""
    rng = np.random.default_rng(seed)
    image = _canvas(PANEL_WIDTH, PANEL_HEIGHT, (36, 38, 42))

    cv2.rectangle(image, (0, 190), (PANEL_WIDTH, 530), (58, 60, 66), -1)
    cv2.rectangle(image, (0, 190), (PANEL_WIDTH, 196), (86, 88, 94), -1)
    cv2.rectangle(image, (0, 524), (PANEL_WIDTH, 530), (86, 88, 94), -1)

    _draw_display(image, DISHWASHER_PANEL.region("display_01"), lit, glyph)
    _draw_led(image, DISHWASHER_PANEL.region("power_led_01"), power)
    _draw_led(image, DISHWASHER_PANEL.region("start_led_01"), start)

    cv2.putText(
        image, "DISHWASHER - MOCK CONTROL PANEL", (40, 640), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 154, 160), 1, cv2.LINE_AA
    )

    if degrade is not None:
        image = _apply_degredation(image, degrade, rng)

    ground_truth = {
        "profile_id": DISHWASHER_PANEL.profile_id,
        "display_lit": lit,
        "display_glyph": glyph if lit else "",
        "power_led": power,
        "start_led": start,
        "expected_display_state": "LIT" if lit else "BLANK",
        "degradation": _degradation_dict(degrade),
    }
    return PanelScene(image=image, ground_truth=ground_truth)


def _degradation_dict(degrade: Degradation | None) -> dict:
    if degrade is None:
        return {}
    return {
        "blur_sigma": degrade.blur_sigma,
        "brightness": degrade.brightness,
        "glare": degrade.glare,
        "rotation_deg": degrade.rotation_deg,
        "perspective": degrade.perspective,
        "resolution_scale": degrade.resolution_scale,
        "noise_sigma": degrade.noise_sigma,
        "jpeg_quality": degrade.jpeg_quality,
    }


# --------------------------------------------------------------------------
# named scenarios
# --------------------------------------------------------------------------


def scenario_normal() -> PanelScene:
    return render_industrial_panel(pressure_psi=42.0, warning="OFF", status="GREEN", switch="UP")


def scenario_fault_distant() -> PanelScene:
    """Observation 1 of the industrial demo.

    Photographed from an angle, with a specular reflection across the dial:
    the red warning lamp is large and saturated enough to survive, but the
dial is no longer a circle and the needle is no longer a clean radial line.

    These parameters were selected by sweeping perspective, glare, blur and
    resolution against the vision engine until the gauge genuinely failed its
    own shape validation while the indicator stayed readable — the numbers come
    from that measurement, not from a desire for a particular plot.
    ``scripts/verify_demo_scenarios.py`` re-checks the property on every run.
    """
    return render_industrial_panel(
        pressure_psi=87.0,
        warning="RED",
        status="OFF",
        switch="UP",
        degrade=Degradation(perspective=0.13, glare=0.30, noise_sigma=3.0),
        seed=23,
    )


def scenario_fault_closeup() -> PanelScene:
    """Observation 2: the same fault, framed properly."""
    return render_industrial_panel(
        pressure_psi=87.0, warning="RED", status="OFF", switch="UP", degrade=Degradation(noise_sigma=1.5), seed=24
    )


def scenario_dishwasher_wide() -> PanelScene:
    """Observation 1 of the household demo: the fascia is too far away."""
    return render_dishwasher_panel(
        lit=True,
        glyph="1:42",
        power="GREEN",
        start="OFF",
        degrade=Degradation(blur_sigma=1.3, resolution_scale=0.40, brightness=1.05, noise_sigma=3.0),
        seed=31,
    )


def scenario_dishwasher_closeup() -> PanelScene:
    return render_dishwasher_panel(
        lit=True, glyph="1:42", power="GREEN", start="OFF", degrade=Degradation(noise_sigma=1.2), seed=32
    )


def scenario_dishwasher_unpowered() -> PanelScene:
    return render_dishwasher_panel(
        lit=False, glyph="", power="OFF", start="OFF", degrade=Degradation(noise_sigma=1.2), seed=33
    )


NAMED_SCENARIOS = {
    "industrial_normal": scenario_normal,
    "industrial_fault_distant": scenario_fault_distant,
    "industrial_fault_closeup": scenario_fault_closeup,
    "dishwasher_wide": scenario_dishwasher_wide,
    "dishwasher_closeup": scenario_dishwasher_closeup,
    "dishwasher_unpowered": scenario_dishwasher_unpowered,
}


def write_scenario(name: str, output_dir: Path) -> dict:
    scene = NAMED_SCENARIOS[name]()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}.png"
    cv2.imwrite(str(path), scene.image)
    record = dict(scene.ground_truth)
    record["fixture"] = str(path.name)
    record["scenario"] = name
    return record


def write_demo_scenarios(output_dir: Path) -> list[dict]:
    """Write the fixtures the household and industrial demos rely on."""
    return [write_scenario(name, output_dir) for name in NAMED_SCENARIOS]


def write_manifest(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover - developer entry point
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/fixtures")
    written = write_demo_scenarios(target)
    write_manifest(written, target / "ground_truth.json")
    print(f"wrote {len(written)} fixtures to {target}")
