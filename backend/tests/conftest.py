"""Shared fixtures.

Three guarantees this file exists to provide:

1. **Nothing touches the real ``data/`` directory.** Every test gets its own
   ``tmp_path``, and the session fixture redirects ``SIGHTOPS_DATA_DIR`` before
   ``app.main`` is imported, because importing that module builds an application
   (and therefore a ``Settings``) as a side effect.
2. **Nothing touches the network.** The API fixture forces the agent's model
   provider to ``None``, which is the documented "provider unavailable" path:
   the run continues with the deterministic policy and says so in the timeline.
   Any accidental live call would therefore fail loudly rather than silently
   reaching Nebius.
3. **Nothing is mocked.** OpenCV, the vision engine, the repository, the agent
   loop and the FastAPI application are all the real implementations.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

import pytest

from app.fixtures.generate_panels import PanelScene


# --------------------------------------------------------------------------
# session-level isolation
# --------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def isolated_data_dir(tmp_path_factory):
    """Point the process at a throwaway data directory for the whole session."""
    path = tmp_path_factory.mktemp("sightops-session-data")
    previous = os.environ.get("SIGHTOPS_DATA_DIR")
    os.environ["SIGHTOPS_DATA_DIR"] = str(path)

    from app.config import get_settings

    get_settings.cache_clear()
    try:
        yield path
    finally:
        if previous is None:
            os.environ.pop("SIGHTOPS_DATA_DIR", None)
        else:
            os.environ["SIGHTOPS_DATA_DIR"] = previous
        get_settings.cache_clear()


# --------------------------------------------------------------------------
# core fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path):
    from app.config import Settings

    value = Settings(data_dir=tmp_path / "sightops-data")
    value.ensure_dirs()
    return value


@pytest.fixture
def engine(settings):
    from app.vision.engine import VisionEngine

    return VisionEngine(settings)


@pytest.fixture
async def repo(settings):
    from app.storage.repo import Repository

    instance = await Repository.open(settings.db_path)
    try:
        yield instance
    finally:
        await instance.close()


@pytest.fixture
def industrial_profile():
    from app.vision.profiles import INDUSTRIAL_PANEL

    return INDUSTRIAL_PANEL


@pytest.fixture
def dishwasher_profile():
    from app.vision.profiles import DISHWASHER_PANEL

    return DISHWASHER_PANEL


@pytest.fixture
def png_bytes():
    """Encode a generated scene to PNG bytes, as an upload would arrive."""
    from app.vision.annotate import encode_png

    def _encode(scene: PanelScene) -> bytes:
        return encode_png(scene.image)

    return _encode


@pytest.fixture
def make_inspection(repo):
    """Create a real persisted inspection row."""
    import app.models.schemas as schemas

    async def _make(
        *,
        mode=schemas.InspectionMode.INDUSTRIAL,
        profile_id: str | None = None,
        problem: str = "test inspection",
        demo_mode: bool = True,
    ):
        from app.vision.profiles import get_profile

        resolved = profile_id or (
            "industrial_panel_v1" if mode is schemas.InspectionMode.INDUSTRIAL else "dishwasher_panel_v1"
        )
        get_profile(resolved)  # fail loudly on a typo rather than at agent time
        inspection = schemas.Inspection(
            id=uuid.uuid4().hex,
            mode=mode,
            profile_id=resolved,
            problem_statement=problem,
            demo_mode=demo_mode,
        )
        await repo.create_inspection(inspection)
        return inspection

    return _make


@pytest.fixture
def attach_image(settings, repo):
    """Store a generated scene as evidence and register it as an observation."""
    from app.models.schemas import utcnow
    from app.storage.evidence import LocalEvidenceStorage, sha256_of
    from app.vision.annotate import encode_png

    storage = LocalEvidenceStorage(settings.evidence_dir)

    async def _attach(inspection, scene: PanelScene) -> str:
        image_id = uuid.uuid4().hex
        data = encode_png(scene.image)
        key = storage.put(inspection.id, image_id, "png", data)
        height, width = scene.image.shape[:2]
        sequence = await repo.next_sequence(inspection.id)
        await repo.add_image(
            image_id=image_id,
            inspection_id=inspection.id,
            original_name=f"observation-{sequence}.png",
            content_type="image/png",
            sha256=sha256_of(data),
            width=width,
            height=height,
            stored_path=key,
            role="primary" if sequence == 1 else "follow_up",
            sequence=sequence,
            created_at=utcnow().isoformat(),
        )
        await repo.add_observation(
            uuid.uuid4().hex, inspection.id, image_id, None, utcnow().isoformat()
        )
        return image_id

    return _attach


@pytest.fixture
def analyze_all(engine):
    """Run the full vision pass over a scene and return the measurements by id."""
    def _analyze(scene: PanelScene, profile, image_id: str = "test-image"):
        result = engine.analyze(scene.image, image_id=image_id, profile=profile)
        return result, {m.component_id: m for m in result.measurements}

    return _analyze


# --------------------------------------------------------------------------
# API fixture
# --------------------------------------------------------------------------


@dataclass
class ApiHandle:
    """The real ASGI app plus an isolated httpx client bound to it."""

    http: object
    app: object
    context: object


@pytest.fixture
async def client(tmp_path, monkeypatch):
    import httpx

    monkeypatch.setenv("SIGHTOPS_DATA_DIR", str(tmp_path / "api-data"))

    from app.api.deps import build_context
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        from app.main import create_app

        app = create_app()
        resolved = get_settings()
        context = await build_context(resolved)
        # See the module docstring: this is the documented degraded path, and it
        # is what keeps a stray live-mode test from calling Nebius.
        context.agent.provider = None
        app.state.context = context

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://sightops.test"
        ) as http:
            yield ApiHandle(http=http, app=app, context=context)
    finally:
        if "context" in locals():
            await context.aclose()
        get_settings.cache_clear()
