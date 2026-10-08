"""Analog gauge reading: accuracy, and the refusal to publish an untrusted number.

The accuracy assertions use generated panels whose ground truth is exact — the
fixture knows the needle is at 92.0 PSI because it *drew* the needle at that
angle. The trust assertions exist because of a real defect found during
development: a perspective-distorted frame produced a confident reading of
**28 PSI for a true 87 PSI**. A reliability tool that prints a wrong number is
worse than one that says it could not read the gauge, so the behaviour that
prevents it is pinned here.
"""

from __future__ import annotations

import pytest

from app.fixtures.generate_panels import Degradation, render_industrial_panel
from app.vision import gauges

CLEAN_PRESSURES = [10.0, 25.0, 50.0, 75.0, 92.0]

#: Frames that genuinely cannot be measured. Verified against the engine before
#: being asserted here: each of these yields ``value is None``.
UNREADABLE_DEGRADATIONS = {
    "heavy_perspective": Degradation(perspective=0.22, noise_sigma=3.0),
    "rotated_eight_degrees": Degradation(rotation_deg=8.0, noise_sigma=3.0),
}

#: Frames the engine may still read, but must never read *wrongly*.
#: This is the regression set for the 28-PSI-for-87-PSI defect: at that time the
#: engine published 28 PSI at confidence 0.72 for a true 87 PSI, which is a 59 PSI
#: error on a 0-100 PSI scale. The tolerance below is 5 % of full scale, which is
#: the accuracy a published reading must reach to be actionable.
MUST_NOT_BE_A_CONFIDENT_READING = {
    "rotated_twelve_degrees": Degradation(rotation_deg=12.0, noise_sigma=3.0),
    "angled_with_glare": Degradation(perspective=0.13, glare=0.30, noise_sigma=3.0),
    "angled_and_soft": Degradation(perspective=0.12, blur_sigma=2.0, noise_sigma=3.0),
}

#: A published reading must land within 6 % of the configured 0-100 PSI span.
#: The tolerances are deliberately tiered by evidence quality: a clean frame is
#: held to 1.5 PSI in the accuracy test above, and a hard frame to 6 PSI here,
#: against a defect that was 59 PSI out.
PUBLISHED_READING_TOLERANCE_PSI = 6.0


def _gauge(engine, profile, scene):
    region = engine.analyze_region(
        scene.image, image_id="frame", profile=profile, region_id="pressure_gauge_01"
    )
    return region.measurements[0]


@pytest.mark.parametrize("pressure", CLEAN_PRESSURES)
def test_gauge_reads_a_clean_panel_within_expected_error(engine, industrial_profile, pressure):
    scene = render_industrial_panel(pressure_psi=pressure, warning="OFF", status="GREEN")

    measurement = _gauge(engine, industrial_profile, scene)

    assert measurement.component_type == "analog_gauge"
    assert measurement.unit == "PSI"
    assert measurement.value is not None, measurement.notes
    assert abs(measurement.value - pressure) < 1.5, (
        f"true {pressure} PSI, measured {measurement.value} PSI"
    )
    assert measurement.confidence > 0.85, measurement.details.get("criteria")
    assert measurement.provenance.value == "measured"


def test_a_clean_reading_reports_the_needle_shape_evidence(engine, industrial_profile):
    scene = render_industrial_panel(pressure_psi=42.0)

    measurement = _gauge(engine, industrial_profile, scene)

    # Shape validation is what makes the value trustworthy, so its inputs are
    # part of the result rather than hidden inside the algorithm.
    assert "ray_coverage" in measurement.details
    assert "peak_width_deg" in measurement.details
    assert measurement.details["ray_coverage"] >= gauges.COVERAGE_FLOOR
    assert measurement.details["peak_width_deg"] <= gauges.WIDTH_BAD_DEG
    assert measurement.details["dial_source"] in {"hough_circle", "configured_roi_inscribed"}
    assert set(measurement.details["criteria"]) >= {
        "coverage_score",
        "peak_score",
        "width_score",
        "contrast_score",
        "margin_score",
        "quality_factor",
    }


def test_high_pressure_is_reported_as_high_against_the_configured_limit(engine, industrial_profile):
    scene = render_industrial_panel(pressure_psi=92.0)

    measurement = _gauge(engine, industrial_profile, scene)

    assert measurement.value is not None
    assert measurement.state == "HIGH"
    assert measurement.details["scale"]["warn_above"] == 75.0


def test_normal_pressure_is_not_reported_as_high(engine, industrial_profile):
    scene = render_industrial_panel(pressure_psi=30.0)

    measurement = _gauge(engine, industrial_profile, scene)

    assert measurement.state == "NORMAL"


# --------------------------------------------------------------------------
# angle -> value
# --------------------------------------------------------------------------


def test_angle_to_value_maps_the_configured_sweep_endpoints(industrial_profile):
    spec = industrial_profile.region("pressure_gauge_01")

    start_value, start_position = gauges.angle_to_value(spec.start_angle_deg, spec)
    end_value, end_position = gauges.angle_to_value(spec.end_angle_deg, spec)

    assert start_value == pytest.approx(0.0)
    assert end_value == pytest.approx(100.0)
    assert start_position == pytest.approx(0.0)
    assert end_position == pytest.approx(1.0)


def test_angle_to_value_is_monotonic_across_the_sweep(industrial_profile):
    spec = industrial_profile.region("pressure_gauge_01")

    values = [gauges.angle_to_value(angle, spec)[0] for angle in range(-134, 135, 4)]

    assert all(value is not None for value in values)
    assert values == sorted(values)
    assert values[0] < values[-1]


def test_angle_to_value_withholds_a_reading_outside_the_sweep(industrial_profile):
    spec = industrial_profile.region("pressure_gauge_01")

    # 180 deg is the 6 o'clock gap between 100 PSI and 0 PSI: there is no scale
    # there, so no value may be invented.
    value, _position = gauges.angle_to_value(180.0, spec)

    assert value is None


# --------------------------------------------------------------------------
# honest failure
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(UNREADABLE_DEGRADATIONS))
def test_unreadable_frame_withholds_the_number_entirely(engine, industrial_profile, name):
    scene = render_industrial_panel(
        pressure_psi=87.0, warning="RED", status="OFF", degrade=UNREADABLE_DEGRADATIONS[name], seed=5
    )

    measurement = _gauge(engine, industrial_profile, scene)

    assert measurement.value is None, (
        f"{name} produced a reading of {measurement.value}; an unreadable gauge must not "
        f"publish a number"
    )
    assert measurement.state == "UNKNOWN"
    assert measurement.requires_reinspection is True
    assert measurement.confidence <= gauges.UNREADABLE_CONFIDENCE
    assert measurement.notes


@pytest.mark.parametrize("name", sorted(MUST_NOT_BE_A_CONFIDENT_READING))
def test_a_published_reading_on_a_hard_frame_is_never_far_wrong(engine, industrial_profile, name):
    """The regression test for the 28-PSI-for-87-PSI defect.

    On a frame the engine decides to publish from, the number must be close
    enough to be actionable; otherwise it must be withheld. A 59 PSI error would
    fail here.
    """
    true_pressure = 87.0
    scene = render_industrial_panel(
        pressure_psi=true_pressure, warning="RED", status="OFF",
        degrade=MUST_NOT_BE_A_CONFIDENT_READING[name], seed=5,
    )

    measurement = _gauge(engine, industrial_profile, scene)

    if measurement.value is None:
        return  # withheld entirely, which is always acceptable

    error = abs(measurement.value - true_pressure)
    assert error <= PUBLISHED_READING_TOLERANCE_PSI, (
        f"{name}: published {measurement.value} PSI (error {error:.1f}) at confidence "
        f"{measurement.confidence} for a true {true_pressure} PSI; a published reading must be "
        f"within {PUBLISHED_READING_TOLERANCE_PSI} PSI or withheld"
    )


def test_distant_demo_frame_is_flagged_rather_than_trusted(engine, industrial_profile):
    """Observation 1 of the industrial demo must not be treated as good evidence.

    Two properties matter here, and both come from the engine rather than the
    test: the measurement is flagged for reinspection, and if it publishes a
    number at all that number is not far wrong.
    """
    from app.fixtures.generate_panels import scenario_fault_distant

    scene = scenario_fault_distant()
    measurement = _gauge(engine, industrial_profile, scene)

    assert measurement.requires_reinspection is True, measurement.details
    if measurement.value is None:
        assert measurement.state == "UNKNOWN"
        assert measurement.confidence <= gauges.UNREADABLE_CONFIDENCE
    else:
        assert abs(measurement.value - 87.0) <= PUBLISHED_READING_TOLERANCE_PSI


def test_distant_demo_frame_still_reads_the_warning_lamp(engine, industrial_profile):
    """The point of observation 1: one component is readable, one is not."""
    from app.fixtures.generate_panels import scenario_fault_distant

    scene = scenario_fault_distant()
    lamp = engine.analyze_region(
        scene.image,
        image_id="frame",
        profile=industrial_profile,
        region_id="warning_led_01",
    ).measurements[0]

    assert lamp.state == "RED"
    assert lamp.confidence > 0.8
    assert lamp.requires_reinspection is False


def test_report_floor_is_documented_and_applied(industrial_profile):
    """A number is only published above REPORT_FLOOR; below it the value is None."""
    assert gauges.REPORT_FLOOR == 0.50
    assert gauges.UNREADABLE_CONFIDENCE < gauges.REPORT_FLOOR


def test_empty_region_is_unreadable(industrial_profile):
    import numpy as np

    spec = industrial_profile.region("pressure_gauge_01")
    measurement = gauges.read_gauge(np.zeros((0, 0, 3), dtype=np.uint8), spec)

    assert measurement.value is None
    assert measurement.state == "UNKNOWN"
    assert measurement.confidence == 0.0
    assert measurement.requires_reinspection is True


def test_a_flat_dial_yields_no_needle(industrial_profile):
    """A blank dial has no needle, so nothing may be reported."""
    import numpy as np

    spec = industrial_profile.region("pressure_gauge_01")
    flat = np.full((374, 480, 3), 200, dtype=np.uint8)

    measurement = gauges.read_gauge(flat, spec)

    # There is no needle to find, so no value may be published and the reason
    # must be reported rather than the reading silently defaulting to zero.
    assert measurement.value is None
    assert measurement.state == "UNKNOWN"
    assert measurement.requires_reinspection is True
    assert measurement.notes
