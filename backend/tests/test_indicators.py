"""Indicator, switch and display classification.

Every fixture is drawn with a known lamp colour, so a misclassification is a
real defect rather than a labelling disagreement.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.fixtures.generate_panels import render_dishwasher_panel, render_industrial_panel
from app.vision import indicators

LIT_STATES = ["RED", "GREEN", "AMBER"]


@pytest.mark.parametrize("state", ["RED", "GREEN", "AMBER", "OFF"])
def test_warning_lamp_state_matches_ground_truth(engine, industrial_profile, state):
    scene = render_industrial_panel(pressure_psi=42.0, warning=state, status="OFF")

    region = engine.analyze_region(
        scene.image,
        image_id="frame",
        profile=industrial_profile,
        region_id="warning_led_01",
    )
    measurement = region.measurements[0]

    assert measurement.component_type == "indicator"
    assert measurement.state == state
    assert measurement.method == "opencv_hsv_roi"


@pytest.mark.parametrize("state", LIT_STATES)
def test_lit_lamps_are_reported_with_high_confidence(engine, industrial_profile, state):
    scene = render_industrial_panel(pressure_psi=42.0, warning=state, status="OFF")

    region = engine.analyze_region(
        scene.image,
        image_id="frame",
        profile=industrial_profile,
        region_id="warning_led_01",
    )
    measurement = region.measurements[0]

    assert measurement.state == state
    assert measurement.confidence > 0.7
    criteria = measurement.details["criteria"]
    assert set(criteria) >= {
        "hue_purity",
        "area_score",
        "saturation_score",
        "value_score",
        "quality_factor",
    }


def test_clean_red_lamp_does_not_ask_for_reinspection(engine, industrial_profile):
    scene = render_industrial_panel(pressure_psi=42.0, warning="RED", status="OFF")

    region = engine.analyze_region(
        scene.image,
        image_id="frame",
        profile=industrial_profile,
        region_id="warning_led_01",
    )
    measurement = region.measurements[0]

    assert measurement.state == "RED"
    assert measurement.confidence > 0.85
    assert measurement.requires_reinspection is False


def test_unlit_region_is_reported_as_off_with_a_reason(engine, industrial_profile):
    scene = render_industrial_panel(pressure_psi=42.0, warning="OFF", status="OFF")

    region = engine.analyze_region(
        scene.image,
        image_id="frame",
        profile=industrial_profile,
        region_id="warning_led_01",
    )
    measurement = region.measurements[0]

    assert measurement.state == "OFF"
    # An unlit lamp is evidenced by the absence of lamp-like pixels, and that
    # evidence is reported rather than left implicit.
    assert measurement.details["criteria"]["brightness_gap"] > 0.5
    assert measurement.notes


def test_indicator_outside_the_image_is_unknown_not_a_guess():
    empty = np.zeros((0, 0, 3), dtype=np.uint8)

    measurement = indicators.detect_indicator(empty, component_id="warning_led_01")

    assert measurement.state == "UNKNOWN"
    assert measurement.confidence == 0.0
    assert measurement.requires_reinspection is True
    assert measurement.notes


@pytest.mark.parametrize("position", ["UP", "RIGHT"])
def test_switch_position_matches_ground_truth(engine, industrial_profile, position):
    scene = render_industrial_panel(pressure_psi=42.0, switch=position)

    region = engine.analyze_region(
        scene.image,
        image_id="frame",
        profile=industrial_profile,
        region_id="selector_switch_01",
    )
    measurement = region.measurements[0]

    assert measurement.component_type == "switch"
    assert measurement.state == position
    assert measurement.method == "opencv_lever_orientation"
    assert measurement.confidence > 0.5
    assert 0.0 <= measurement.details["axis_deviation_from_vertical_deg"] <= 90.0


def test_switch_outside_the_image_is_unknown():
    empty = np.zeros((0, 0, 3), dtype=np.uint8)

    measurement = indicators.classify_switch(empty, component_id="selector_switch_01")

    assert measurement.state == "UNKNOWN"
    assert measurement.confidence == 0.0
    assert measurement.requires_reinspection is True


def test_lit_display_is_reported_as_lit(engine, dishwasher_profile):
    scene = render_dishwasher_panel(lit=True, glyph="1:42")

    region = engine.analyze_region(
        scene.image, image_id="frame", profile=dishwasher_profile, region_id="display_01"
    )
    measurement = region.measurements[0]

    assert measurement.component_type == "display"
    assert measurement.state == "LIT"
    # Glyph strokes cover only a few percent of the window, so p95 reports the
    # dark background; the detector uses p99 for exactly that reason.
    assert measurement.details["lit_fraction"] < 0.2
    assert measurement.details["dynamic_range"] > 60.0


def test_unlit_display_is_reported_as_blank(engine, dishwasher_profile):
    scene = render_dishwasher_panel(lit=False, glyph="", power="OFF")

    region = engine.analyze_region(
        scene.image, image_id="frame", profile=dishwasher_profile, region_id="display_01"
    )
    measurement = region.measurements[0]

    assert measurement.state == "BLANK"
    assert measurement.notes


def test_display_does_not_claim_to_read_characters(engine, dishwasher_profile):
    """OpenCV reports lit/blank; digit interpretation is explicitly not claimed."""
    scene = render_dishwasher_panel(lit=True, glyph="1:42")

    region = engine.analyze_region(
        scene.image, image_id="frame", profile=dishwasher_profile, region_id="display_01"
    )

    assert "not performed by OpenCV" in region.measurements[0].details["provenance_note"]


def test_hue_bands_do_not_overlap_and_only_yellow_is_unclassified():
    """The bands partition 0..179 except for the yellow gap.

    Yellow (28..34) is deliberately absent: it has no indicator state of its own,
    so a yellow lamp must not be forced into AMBER or GREEN.
    """
    covered: set[int] = set()
    for _name, low, high in indicators.HUE_BANDS:
        assert low < high
        assert not (covered & set(range(low, high))), "hue bands must not overlap"
        covered |= set(range(low, high))

    assert covered <= set(range(180))
    assert set(range(180)) - covered == set(range(28, 35))


def test_only_known_hue_winners_map_to_a_state():
    """VIOLET has no state: it must fall through to UNKNOWN, not be guessed."""
    assert set(indicators._STATE_BY_WINNER) == {"RED", "AMBER", "GREEN", "BLUE"}
    assert "VIOLET" not in indicators._STATE_BY_WINNER

    assert indicators.IndicatorState.UNKNOWN is indicators._STATE_BY_WINNER.get(
        "VIOLET", indicators.IndicatorState.UNKNOWN
    )


def test_a_bright_unsaturated_lamp_is_reported_as_white():
    """A white lamp must read WHITE, not OFF.

    Regression test for a real defect: a fully unsaturated lamp (S == 0) forms no
    HSV blob because the blob mask requires S >= 35, and the old OFF test then
    fired on that low saturation alone — reporting a clearly lit white indicator
    as unlit. ``detect_indicator`` now checks for a bright, hue-less lamp before
    the OFF branch. Measuring the lamp's saturation anywhere other than in its
    own bright pixels is what made this fail the first time: a dark bezel has a
    high HSV saturation, so a region-wide percentile hid the lamp's colour.
    """
    region = np.full((80, 80, 3), 30, dtype=np.uint8)
    # BGR 245,245,245 -> V=245, S=0: a lit white lamp.
    region[20:60, 20:60] = (245, 245, 245)

    measurement = indicators.detect_indicator(region, component_id="lamp")

    assert measurement.state == "WHITE"
    assert measurement.confidence > 0.5


def test_a_bright_saturated_lamp_with_a_white_core_still_reads_white():
    """The reachable white path: a saturated bezel around an unsaturated core."""
    region = np.full((80, 80, 3), 30, dtype=np.uint8)
    # A warm, moderately saturated ring with a bright white centre.
    region[18:62, 18:62] = (60, 120, 200)
    region[30:50, 30:50] = (235, 240, 245)

    measurement = indicators.detect_indicator(region, component_id="lamp")

    assert measurement.state in {"WHITE", "AMBER"}
    assert measurement.confidence > 0.4
