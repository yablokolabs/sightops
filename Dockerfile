# syntax=docker/dockerfile:1
#
# SightOps backend — FastAPI, OpenCV 5, the bounded agent loop and SQLite.
#
# The image is CPU-only and self-contained: the vision pipeline, the model
# clients and the storage layer all run inside it, so the host needs nothing but
# Docker. No cloud service is required. AWS integration is NOT IMPLEMENTED (see
# docs/architecture/aws.md); the provider interfaces are the only seam that
# would change.

FROM python:3.12-slim

# OpenCV's published wheel links against system libraries that python:3.12-slim
# does not ship. `libgl1` and `libglib2.0-0` are cv2's load-time dependencies —
# without them `import cv2` fails outright, headless use included — and
# `libgomp1` provides the OpenMP runtime the wheel's parallel loops link
# against. Installed in one layer with the apt lists removed in the same step so
# they do not stay in the image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Unbuffered stdout so `docker logs` shows the request log and the agent's
# tool-call trace as they happen rather than when the process exits, and no
# .pyc files, since the layer is read-only in normal operation.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies are read out of pyproject.toml rather than duplicated in a second
# requirements file, so the pinned versions the verified test run used stay in
# one place.
COPY backend/pyproject.toml /app/pyproject.toml
RUN python - <<'PY'
import pathlib
import tomllib

project = tomllib.loads(pathlib.Path("/app/pyproject.toml").read_text())["project"]
pathlib.Path("/tmp/requirements.txt").write_text("\n".join(project["dependencies"]) + "\n")
PY

# The scientific stack is the slow layer (opencv + numpy + scipy). Keeping it
# separate from the application code means editing a vision module reuses it.
RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt

# Application code last, because it changes far more often than the pinned
# dependencies above. The editable install means the modules under /app are the
# ones that run, so the source in the image and the source on disk cannot drift.
COPY backend/app /app/app
COPY backend/scripts /app/scripts
RUN pip install --no-deps -e .

# The non-root user cannot read ~/.hermes/.env, which is deliberate: it has no
# home directory copy of the credential store. `app.config.load_secrets` then
# falls back to the environment, which is how the three keys arrive.
RUN useradd --create-home --shell /usr/sbin/nologin sightops \
    && mkdir -p /data \
    && chown -R sightops:sightops /app /data

USER sightops

# Runtime state — the SQLite database and the evidence blobs — lives on one
# volume at the real `Settings.data_dir`, so `docker compose down && up` keeps
# the inspection history. Declared after the chown so a freshly created named
# volume inherits the ownership the process needs.
ENV SIGHTOPS_DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 8000

# Fails when the API answers but its database does not, which is what
# /health reports as "degraded" while still returning 200.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c 'import json,sys,urllib.request as u; sys.exit(0 if json.loads(u.urlopen("http://127.0.0.1:8000/health", timeout=4).read()).get("status") == "ok" else 1)'

# A single worker is intentional: the agent loop and its SQLite connection are
# per-process, and the vision work is CPU-bound. `--proxy-headers` makes uvicorn
# honour the X-Forwarded-* headers nginx sets, so the log and the request id
# reflect the client rather than the proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
