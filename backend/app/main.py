"""FastAPI application for SightOps.

Startup builds one :class:`~app.api.deps.AppContext`; shutdown closes the
database. Every response carries an ``X-Request-ID`` so a log line can be tied
to the request that produced it.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api import demo, inspections, system
from app.api.deps import build_context
from app.config import get_settings
from app.vision.engine import version_report

logger = logging.getLogger("sightops")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    report = version_report()
    if not report["is_opencv_5"]:
        logger.warning(
            "OpenCV %s is running but SightOps requires OpenCV 5; measurements still work, "
            "but any OpenCV 5 claim would be false.",
            report["opencv_version"],
        )

    app = FastAPI(
        title="SightOps API",
        description=(
            "An Agentic Visual Reliability Engineer. SightOps measures equipment from "
            "photographs with OpenCV 5 and investigates the result with a bounded agent loop. "
            "AWS integration is NOT IMPLEMENTED; this build runs entirely on the local VM."
        ),
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 - converted to a 500 with a request id
            logger.exception("unhandled error request_id=%s path=%s", request_id, request.url.path)
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "an unexpected error occurred",
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )
        duration_ms = (time.perf_counter() - started) * 1000.0
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "%s %s -> %s (%.1f ms) request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response

    @app.on_event("startup")
    async def startup() -> None:
        app.state.context = await build_context(settings)
        logger.info(
            "SightOps started: OpenCV %s, model %s, demo_mode=%s",
            report["opencv_version"],
            settings.nebius_model,
            settings.demo_mode,
        )

    @app.on_event("shutdown")
    async def shutdown() -> None:
        context = getattr(app.state, "context", None)
        if context is not None:
            await context.aclose()

    app.include_router(system.health_router)
    app.include_router(system.system_router)
    app.include_router(inspections.router)
    app.include_router(system.incident_router)
    app.include_router(system.voice_router)
    app.include_router(demo.router)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/api/docs")

    return app


app = create_app()
