"""Change detection between two observations."""

from __future__ import annotations

import numpy as np

from app.fixtures.generate_panels import render_industrial_panel
from app.models.schemas import Severity
from app.vision.change import compare_analyses, pixel_difference


def _analyse(engine, profile, scene, image_id):
    return engine.analyze(scene.image, image_id=image_id, profile=profile)


def test_normal_to_fault_reports_the_lamp_transition_and_the_pressure_rise(engine, industrial_profile):
    normal = render_industrial_panel(pressure_psi=42.0, warning="OFF", status="GREEN", switch="UP")
    fault = render_industrial_panel(pressure_psi=92.0, warning="RED", status="OFF", switch="UP")

    before = _analyse(engine, industrial_profile, normal, "before")
    after = _analyse(engine, industrial_profile, fault, "after")

    report = compare_analyses(before, after, pixel_mean_abs_diff=0.12)
    by_component = {change.component_id: change for change in report.changes}

    assert report.previous_image_id == "before"
    assert report.current_image_id == "after"

    lamp = by_component["warning_led_01"]
    assert lamp.previous == "OFF"
    assert lamp.current == "RED"
    assert lamp.severity is Severity.HIGH

    gauge = by_component["pressure_gauge_01"]
    assert gauge.severity is Severity.CRITICAL
    assert "above" in gauge.description or "moved" in gauge.description

    # The frame-level pixel metric is reported as context, never as component state.
    assert by_component["panel_pixels"].severity is Severity.INFO


def test_status_lamp_turning_off_is_reported(engine, industrial_profile):
    normal = render_industrial_panel(pressure_psi=42.0, warning="OFF", status="GREEN")
    fault = render_industrial_panel(pressure_psi=42.0, warning="OFF", status="OFF")

    report = compare_analyses(
        _analyse(engine, industrial_profile, normal, "a"),
        _analyse(engine, industrial_profile, fault, "b"),
    )
    by_component = {change.component_id: change for change in report.changes}

    assert "status_led_01" in by_component
    assert by_component["status_led_01"].previous == "GREEN"
    assert by_component["status_led_01"].current == "OFF"
    assert by_component["status_led_01"].severity is Severity.MEDIUM


def test_identical_observations_produce_no_component_changes(engine, industrial_profile):
    scene = render_industrial_panel(pressure_psi=42.0, warning="OFF", status="GREEN", switch="UP")

    before = _analyse(engine, industrial_profile, scene, "same-a")
    after = _analyse(engine, industrial_profile, scene, "same-b")

    report = compare_analyses(before, after)

    assert report.changes == []
    assert report.method == "structured_measurement_diff"


def test_identical_observations_with_a_pixel_metric_report_only_that_metric(engine, industrial_profile):
    scene = render_industrial_panel(pressure_psi=42.0)

    report = compare_analyses(
        _analyse(engine, industrial_profile, scene, "same-a"),
        _analyse(engine, industrial_profile, scene, "same-b"),
        pixel_mean_abs_diff=0.0,
    )

    assert [change.component_id for change in report.changes] == ["panel_pixels"]


def test_pixel_difference_returns_none_for_empty_arrays():
    empty = np.zeros((0, 0, 3), dtype=np.uint8)

    assert pixel_difference(empty, empty) == (None, None)


def test_pixel_difference_is_normalised_and_direction_agnostic():
    first = np.zeros((40, 40, 3), dtype=np.uint8)
    second = np.full((40, 40, 3), 255, dtype=np.uint8)

    forward, difference = pixel_difference(first, second)
    backward, _ = pixel_difference(second, first)

    assert forward is not None and backward is not None
    assert 0.0 <= forward <= 1.0
    assert forward == backward  # absolute difference is symmetric
    assert forward > 0.9  # black against white
    assert difference.shape[:2] == (40, 40)


def test_pixel_difference_handles_mismatched_sizes():
    small = np.zeros((20, 20, 3), dtype=np.uint8)
    large = np.zeros((40, 40, 3), dtype=np.uint8)

    value, difference = pixel_difference(small, large)

    assert value == 0.0
    assert difference.shape[:2] == (20, 20)
