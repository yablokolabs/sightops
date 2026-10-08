"""Persistence.

SQLite holds inspection state; image bytes live on disk behind
:class:`~app.storage.evidence.EvidenceStorage`. Nothing in the vision, agent or
API layer opens the database directly — they go through
:class:`~app.storage.repo.Repository`, so the DynamoDB/S3 adapters described in
``docs/architecture/aws.md`` can be added later without touching callers.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS inspections (
    id                TEXT PRIMARY KEY,
    mode              TEXT NOT NULL,
    profile_id        TEXT NOT NULL,
    state             TEXT NOT NULL,
    problem_statement TEXT NOT NULL DEFAULT '',
    appliance         TEXT,
    demo_mode         INTEGER NOT NULL DEFAULT 0,
    incident_id       TEXT,
    assessment        TEXT,
    pending_request   TEXT,
    outcome           TEXT,
    resolved          INTEGER,
    step_count        INTEGER NOT NULL DEFAULT 0,
    tool_call_count   INTEGER NOT NULL DEFAULT 0,
    error             TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS images (
    id            TEXT PRIMARY KEY,
    inspection_id TEXT NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    original_name TEXT,
    content_type  TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    width         INTEGER NOT NULL,
    height        INTEGER NOT NULL,
    stored_path   TEXT NOT NULL,
    annotated_path TEXT,
    role          TEXT NOT NULL DEFAULT 'primary',
    sequence      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_images_inspection ON images(inspection_id, sequence);

CREATE TABLE IF NOT EXISTS observations (
    id            TEXT PRIMARY KEY,
    inspection_id TEXT NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    image_id      TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    analysis      TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS timeline (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id TEXT NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    detail        TEXT NOT NULL DEFAULT '',
    state         TEXT,
    data          TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_timeline_inspection ON timeline(inspection_id, id);

CREATE TABLE IF NOT EXISTS tool_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id TEXT NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    step          INTEGER NOT NULL,
    tool          TEXT NOT NULL,
    arguments     TEXT NOT NULL DEFAULT '{}',
    ok            INTEGER NOT NULL,
    result        TEXT NOT NULL DEFAULT '{}',
    error         TEXT,
    duration_ms   REAL NOT NULL DEFAULT 0,
    source        TEXT NOT NULL DEFAULT 'model',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_inspection ON tool_calls(inspection_id, id);

CREATE TABLE IF NOT EXISTS incidents (
    id                 TEXT PRIMARY KEY,
    inspection_id      TEXT NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    title              TEXT NOT NULL,
    summary            TEXT NOT NULL,
    severity           TEXT NOT NULL,
    status             TEXT NOT NULL,
    evidence_image_ids TEXT NOT NULL DEFAULT '[]',
    measurements       TEXT NOT NULL DEFAULT '[]',
    proposed_action    TEXT,
    approval_required  INTEGER NOT NULL DEFAULT 1,
    resolution_note    TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_inspection ON incidents(inspection_id);
"""


async def connect(db_path: Path) -> aiosqlite.Connection:
    """Open a connection with the schema applied and rows returned as dicts."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.executescript(SCHEMA)
    await conn.commit()
    return conn
