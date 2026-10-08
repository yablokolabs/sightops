"""Image-quality scoring.

These scores are the evidence behind the agent's decision to ask for another
photograph, so they are tested against images whose quality is known by
construction: a clean generated panel, a Gaussian-blurred copy of it, a black
frame and a mid-grey frame.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.fixtures.generate_panels import Degradation, render_industrial_panel
from app.vision import quality as quality_module
from app.vision.preprocess import gray_of


def test_blur_score_range_and_clean_panel_is_sharp():
    scene = render_industrial_panel(pressure_psi=42.0)
    gray = gray_of(scene.image)

    score, raw = quality_module.blur_score(gray)

    assert 0.0 <= score <= 1.0
    # The reference panel is drawn with hard edges, so it should saturate.
    assert score == 1.0
    assert raw > 0.0


def test_blur_score_falls_strictly_when_the_same_panel_is_blurred():
    sharp = render_industrial_panel(pressure_psi=42.0)
    blurred = render_industrial_panel(
        pressure_psi=42.0, degrade=Degradation(blur_sigma=6.0), seed=8
    )

    sharp_score, sharp_raw = quality_module.blur_score(gray_of(sharp.image))
    blurred_score, blurred_raw = quality_module.blur_score(gray_of(blurred.image))

    assert blurred_score < sharp_score
    assert blurred_raw < sharp_raw


def test_exposure_quality_is_lower_for_a_black_frame_than_mid_grey():
    mid_grey = np.full((240, 320, 3), 128, dtype=np.uint8)
    black = np.zeros((240, 320, 3), dtype=np.uint8)

    grey_quality, grey_luma = quality_module.exposure_quality(gray_of(mid_grey))
    black_quality, black_luma = quality_module.exposure_quality(gray_of(black))

    assert 0.0 <= grey_quality <= 1.0
    assert 0.0 <= black_quality <= 1.0
    assert black_quality < grey_quality
    assert black_luma < grey_luma


def test_assess_requests_a_new_view_for_a_region_too_small_to_measure():
    scene = render_industrial_panel(pressure_psi=42.0)
    tiny = scene.image[0:8, 0:12]

    result = quality_module.assess(scene.image, region=tiny, region_id="tiny_region")

    assert result.requires_new_view is True
    assert result.reason
    assert "tiny_region" == result.region_id
    assert result.resolution_sufficient is False


def test_assess_accepts_a_healthy_region_without_a_reason():
    """A well-exposed, detailed crop must not be flagged.

    The region is a checkerboard so its sharpness and exposure are known by
    construction rather than depending on how much of a generated panel happens
    to fall inside the crop.
    """
    tiles = ((np.indices((240, 320)).sum(axis=0) // 16) % 2).astype(np.uint8)
    checker = np.dstack([tiles, tiles, tiles]) * 80 + 90

    result = quality_module.assess(checker, region=checker, region_id="healthy", min_short_edge=24)

    assert result.resolution_sufficient is True
    assert result.blur_score == 1.0
    assert result.reason is None
    assert result.requires_new_view is False


def test_engine_region_quality_uses_the_small_region_bound_not_the_frame_rule(engine, industrial_profile):
    """A 138x83 indicator window is a good crop, not a too-small one.

    The frame-level rule needs a 480 px short edge; applying it to a component
    crop flagged every indicator as too small to read, which is the bug this
    test pins down.
    """
    scene = render_industrial_panel(pressure_psi=42.0, warning="GREEN")

    region = engine.analyze_region(
        scene.image,
        image_id="frame",
        profile=industrial_profile,
        region_id="warning_led_01",
    )

    assert region.quality is not None
    assert region.quality.resolution_sufficient is True
    assert min(region.quality.width, region.quality.height) < 480


def test_full_frame_blur_score_is_reported_on_the_analysis(engine, industrial_profile):
    scene = render_industrial_panel(pressure_psi=42.0)

    analysis = engine.analyze(
        scene.image, image_id="frame", profile=industrial_profile
    )

    assert analysis.opencv_version.startswith("5.")
    assert 0.0 <= analysis.quality.blur_score <= 1.0
    assert 0.0 <= analysis.quality.exposure_quality <= 1.0
    assert analysis.quality.width > 0 and analysis.quality.height > 0
    # The working copy is bounded, but the original frame is 1280x720.
    assert analysis.quality.width <= 1280


def test_blurred_frame_is_reported_as_lower_quality_than_the_clean_one(engine, industrial_profile):
    clean = render_industrial_panel(pressure_psi=42.0)
    soft = render_industrial_panel(pressure_psi=42.0, degrade=Degradation(blur_sigma=7.0), seed=9)

    clean_analysis = engine.analyze(clean.image, image_id="clean", profile=industrial_profile)
    soft_analysis = engine.analyze(soft.image, image_id="soft", profile=industrial_profile)

    assert soft_analysis.quality.blur_score < clean_analysis.quality.blur_score


def test_gray_input_is_accepted(engine, industrial_profile):
    """A single-channel frame must not crash the pipeline."""
    scene = render_industrial_panel(pressure_psi=42.0)
    gray = cv2.cvtColor(scene.image, cv2.COLOR_BGR2GRAY)

    analysis = engine.analyze(gray, image_id="gray", profile=industrial_profile)

    assert len(analysis.measurements) == len(industrial_profile.regions)
