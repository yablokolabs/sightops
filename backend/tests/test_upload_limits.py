"""Upload limits and decode guards.

An image upload endpoint is an attack surface: a decompression bomb or an
oversized body must be refused before anything is written or decoded into a
large array.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.fixtures.generate_panels import scenario_normal
from app.vision.annotate import encode_png
from app.vision.engine import ImageValidationError

PNG = "image/png"


def _png_of(size: tuple[int, int]) -> bytes:
    image = np.full((size[1], size[0], 3), 120, dtype=np.uint8)
    return encode_png(image)


async def _create(client):
    response = await client.http.post(
        "/api/inspections",
        json={"mode": "industrial", "problem_statement": "oversize test", "demo_mode": True},
    )
    assert response.status_code == 201
    return response.json()


async def test_oversized_upload_is_refused_and_stores_nothing(client, settings):
    inspection = await _create(client)
    oversized = b"\x00" * (13 * 1024 * 1024)

    response = await client.http.post(
        f"/api/inspections/{inspection['id']}/images",
        files={"file": ("huge.png", oversized, PNG)},
        data={"run_agent": "false"},
    )

    assert response.status_code in {413, 422}, response.text
    assert "byte limit" in response.json()["detail"]
    assert str(settings.max_upload_bytes) in response.json()["detail"]

    assert await client.context.repo.list_images(inspection["id"]) == []


def test_decode_rejects_empty_bytes(engine):
    with pytest.raises(ImageValidationError) as excinfo:
        engine.decode(b"")

    assert "empty" in str(excinfo.value)


def test_decode_rejects_an_oversized_blob(engine, settings):
    with pytest.raises(ImageValidationError) as excinfo:
        engine.decode(b"\x00" * (settings.max_upload_bytes + 1))

    assert "byte limit" in str(excinfo.value)


def test_decode_rejects_undecodable_bytes(engine):
    with pytest.raises(ImageValidationError) as excinfo:
        engine.decode(b"definitely not an image")

    assert "decoded" in str(excinfo.value)


def test_decode_rejects_an_image_below_the_minimum_size(engine):
    with pytest.raises(ImageValidationError) as excinfo:
        engine.decode(_png_of((16, 16)))

    assert "16x16" in str(excinfo.value)


def test_decode_accepts_a_valid_fixture(engine):
    data = encode_png(scenario_normal().image)

    image = engine.decode(data)

    assert image.shape[:2] == (720, 1280)
    assert image.ndim == 3


def test_decode_accepts_a_jpeg_round_trip(engine):
    ok, buffer = cv2.imencode(".jpg", scenario_normal().image)
    assert ok

    image = engine.decode(buffer.tobytes())

    assert image.shape[:2] == (720, 1280)


def test_a_frame_above_the_configured_pixel_limit_is_refused():
    """A file that decodes to more pixels than allowed is refused before analysis."""
    from app.config import Settings

    strict = Settings(max_image_pixels=10_000)
    from app.vision.engine import VisionEngine

    guarded = VisionEngine(strict)
    data = encode_png(scenario_normal().image)

    with pytest.raises(ImageValidationError) as excinfo:
        guarded.decode(data)

    assert "pixel limit" in str(excinfo.value)
