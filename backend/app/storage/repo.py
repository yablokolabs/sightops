"""Repository over SQLite.

Every method takes and returns Pydantic models from
:mod:`app.models.schemas`. JSON-encoded columns are serialised here so the
schema stays readable in a SQLite browser while callers never touch raw rows.
"""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from app.models.schemas import (
    AnalysisResult,
    Assessment,
    Incident,
    Inspection,
    InspectionMode,
    InspectionState,
    Observation,
    ReinspectionRequest,
    TimelineEntry,
    TimelineKind,
    ToolCallRecord,
)
from app.storage.db import connect


def _dump(model) -> str:
    if hasattr(model, "model_dump_json"):
        return model.model_dump_json()
    return json.dumps(model)


class Repository:
    """Async persistence for inspections, observations, traces and incidents."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    @classmethod
    async def open(cls, db_path: Path) -> Repository:
        return cls(await connect(db_path))

    async def close(self) -> None:
        await self.conn.close()

    # -- inspections --------------------------------------------------------

    async def create_inspection(self, inspection: Inspection) -> Inspection:
        await self.conn.execute(
            """
            INSERT INTO inspections (id, mode, profile_id, state, problem_statement,
                appliance, demo_mode, incident_id, assessment, pending_request, outcome,
                resolved, step_count, tool_call_count, error, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                inspection.id,
                inspection.mode.value,
                inspection.profile_id,
                inspection.state.value,
                inspection.problem_statement,
                inspection.appliance,
                int(inspection.demo_mode),
                inspection.incident_id,
                None,
                None,
                inspection.outcome,
                None if inspection.resolved is None else int(inspection.resolved),
                inspection.step_count,
                inspection.tool_call_count,
                inspection.error,
                inspection.created_at.isoformat(),
                inspection.updated_at.isoformat(),
            ),
        )
        await self.conn.commit()
        return inspection

    async def update_inspection(self, inspection: Inspection) -> None:
        await self.conn.execute(
            """
            UPDATE inspections SET state=?, incident_id=?, assessment=?, pending_request=?,
                outcome=?, resolved=?, step_count=?, tool_call_count=?, error=?,
                problem_statement=?, appliance=?, updated_at=?
            WHERE id=?
            """,
            (
                inspection.state.value,
                inspection.incident_id,
                _dump(inspection.assessment) if inspection.assessment else None,
                _dump(inspection.pending_request) if inspection.pending_request else None,
                inspection.outcome,
                None if inspection.resolved is None else int(inspection.resolved),
                inspection.step_count,
                inspection.tool_call_count,
                inspection.error,
                inspection.problem_statement,
                inspection.appliance,
                inspection.updated_at.isoformat(),
                inspection.id,
            ),
        )
        await self.conn.commit()

    def _inspection_from_row(self, row: aiosqlite.Row) -> Inspection:
        return Inspection(
            id=row["id"],
            mode=InspectionMode(row["mode"]),
            profile_id=row["profile_id"],
            state=InspectionState(row["state"]),
            problem_statement=row["problem_statement"],
            appliance=row["appliance"],
            demo_mode=bool(row["demo_mode"]),
            incident_id=row["incident_id"],
            assessment=Assessment.model_validate_json(row["assessment"]) if row["assessment"] else None,
            pending_request=(
                ReinspectionRequest.model_validate_json(row["pending_request"])
                if row["pending_request"]
                else None
            ),
            outcome=row["outcome"],
            resolved=None if row["resolved"] is None else bool(row["resolved"]),
            step_count=row["step_count"],
            tool_call_count=row["tool_call_count"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get_inspection(self, inspection_id: str) -> Inspection | None:
        async with self.conn.execute(
            "SELECT * FROM inspections WHERE id=?", (inspection_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        inspection = self._inspection_from_row(row)
        inspection.observations = await self.list_observations(inspection_id)
        inspection.observation_count = len(inspection.observations)
        return inspection

    async def list_inspections(self, limit: int = 50) -> list[Inspection]:
        async with self.conn.execute(
            "SELECT * FROM inspections ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._inspection_from_row(row) for row in rows]

    async def observation_count(self, inspection_id: str) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) AS n FROM observations WHERE inspection_id=?", (inspection_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["n"]) if row else 0

    # -- images -------------------------------------------------------------

    async def add_image(
        self,
        *,
        image_id: str,
        inspection_id: str,
        original_name: str | None,
        content_type: str,
        sha256: str,
        width: int,
        height: int,
        stored_path: str,
        role: str,
        sequence: int,
        created_at: str,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO images (id, inspection_id, original_name, content_type, sha256,
                width, height, stored_path, role, sequence, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                image_id,
                inspection_id,
                original_name,
                content_type,
                sha256,
                width,
                height,
                stored_path,
                role,
                sequence,
                created_at,
            ),
        )
        await self.conn.commit()

    async def set_annotated_path(self, image_id: str, path: str) -> None:
        await self.conn.execute(
            "UPDATE images SET annotated_path=? WHERE id=?", (path, image_id)
        )
        await self.conn.commit()

    async def get_image(self, image_id: str) -> dict | None:
        async with self.conn.execute("SELECT * FROM images WHERE id=?", (image_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_images(self, inspection_id: str) -> list[dict]:
        async with self.conn.execute(
            "SELECT * FROM images WHERE inspection_id=? ORDER BY sequence", (inspection_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def next_sequence(self, inspection_id: str) -> int:
        async with self.conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS n FROM images WHERE inspection_id=?",
            (inspection_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["n"]) if row else 1

    # -- observations -------------------------------------------------------

    async def add_observation(
        self,
        observation_id: str,
        inspection_id: str,
        image_id: str,
        analysis: AnalysisResult | None,
        created_at: str,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO observations (id, inspection_id, image_id, analysis, created_at) VALUES (?,?,?,?,?)",
            (
                observation_id,
                inspection_id,
                image_id,
                _dump(analysis) if analysis else None,
                created_at,
            ),
        )
        await self.conn.commit()

    async def update_observation_analysis(self, image_id: str, analysis: AnalysisResult) -> None:
        await self.conn.execute(
            "UPDATE observations SET analysis=? WHERE image_id=?", (_dump(analysis), image_id)
        )
        await self.conn.commit()

    async def list_observations(self, inspection_id: str) -> list[Observation]:
        async with self.conn.execute(
            """
            SELECT o.id, o.inspection_id, o.image_id, o.analysis, o.created_at,
                   i.original_name, i.role, i.sequence
            FROM observations o JOIN images i ON i.id = o.image_id
            WHERE o.inspection_id = ? ORDER BY i.sequence
            """,
            (inspection_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            Observation(
                id=row["id"],
                inspection_id=row["inspection_id"],
                image_id=row["image_id"],
                original_name=row["original_name"],
                role=row["role"],
                sequence=row["sequence"],
                analysis=(
                    AnalysisResult.model_validate_json(row["analysis"]) if row["analysis"] else None
                ),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # -- timeline -----------------------------------------------------------

    async def add_timeline(
        self,
        inspection_id: str,
        kind: TimelineKind,
        title: str,
        detail: str = "",
        state: InspectionState | None = None,
        data: dict | None = None,
        created_at: str | None = None,
    ) -> None:
        from app.models.schemas import utcnow

        await self.conn.execute(
            """
            INSERT INTO timeline (inspection_id, kind, title, detail, state, data, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                inspection_id,
                kind.value,
                title,
                detail,
                state.value if state else None,
                json.dumps(data or {}, default=str),
                created_at or utcnow().isoformat(),
            ),
        )
        await self.conn.commit()

    async def list_timeline(self, inspection_id: str) -> list[TimelineEntry]:
        async with self.conn.execute(
            "SELECT * FROM timeline WHERE inspection_id=? ORDER BY id", (inspection_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            TimelineEntry(
                id=row["id"],
                inspection_id=row["inspection_id"],
                kind=TimelineKind(row["kind"]),
                title=row["title"],
                detail=row["detail"],
                state=InspectionState(row["state"]) if row["state"] else None,
                data=json.loads(row["data"] or "{}"),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # -- tool calls ---------------------------------------------------------

    async def add_tool_call(self, record: ToolCallRecord) -> None:
        await self.conn.execute(
            """
            INSERT INTO tool_calls (inspection_id, step, tool, arguments, ok, result, error,
                duration_ms, source, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record.inspection_id,
                record.step,
                record.tool,
                json.dumps(record.arguments, default=str),
                int(record.ok),
                json.dumps(record.result, default=str),
                record.error,
                record.duration_ms,
                record.source,
                record.created_at.isoformat(),
            ),
        )
        await self.conn.commit()

    async def list_tool_calls(self, inspection_id: str) -> list[ToolCallRecord]:
        async with self.conn.execute(
            "SELECT * FROM tool_calls WHERE inspection_id=? ORDER BY id", (inspection_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            ToolCallRecord(
                id=row["id"],
                inspection_id=row["inspection_id"],
                step=row["step"],
                tool=row["tool"],
                arguments=json.loads(row["arguments"] or "{}"),
                ok=bool(row["ok"]),
                result=json.loads(row["result"] or "{}"),
                error=row["error"],
                duration_ms=row["duration_ms"],
                source=row["source"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # -- incidents ----------------------------------------------------------

    async def create_incident(self, incident: Incident) -> Incident:
        await self.conn.execute(
            """
            INSERT INTO incidents (id, inspection_id, title, summary, severity, status,
                evidence_image_ids, measurements, proposed_action, approval_required,
                resolution_note, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                incident.id,
                incident.inspection_id,
                incident.title,
                incident.summary,
                incident.severity.value,
                incident.status.value,
                json.dumps(incident.evidence_image_ids),
                json.dumps([m.model_dump(mode="json") for m in incident.measurements], default=str),
                incident.proposed_action,
                int(incident.approval_required),
                incident.resolution_note,
                incident.created_at.isoformat(),
                incident.updated_at.isoformat(),
            ),
        )
        await self.conn.commit()
        return incident

    async def update_incident(self, incident: Incident) -> None:
        await self.conn.execute(
            """
            UPDATE incidents SET summary=?, severity=?, status=?, proposed_action=?,
                resolution_note=?, measurements=?, updated_at=? WHERE id=?
            """,
            (
                incident.summary,
                incident.severity.value,
                incident.status.value,
                incident.proposed_action,
                incident.resolution_note,
                json.dumps([m.model_dump(mode="json") for m in incident.measurements], default=str),
                incident.updated_at.isoformat(),
                incident.id,
            ),
        )
        await self.conn.commit()

    def _incident_from_row(self, row: aiosqlite.Row) -> Incident:
        from app.models.schemas import Measurement, Severity

        return Incident(
            id=row["id"],
            inspection_id=row["inspection_id"],
            title=row["title"],
            summary=row["summary"],
            severity=Severity(row["severity"]),
            status=row["status"],
            evidence_image_ids=json.loads(row["evidence_image_ids"] or "[]"),
            measurements=[Measurement.model_validate(m) for m in json.loads(row["measurements"] or "[]")],
            proposed_action=row["proposed_action"],
            approval_required=bool(row["approval_required"]),
            resolution_note=row["resolution_note"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get_incident(self, incident_id: str) -> Incident | None:
        async with self.conn.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)) as cursor:
            row = await cursor.fetchone()
        return self._incident_from_row(row) if row else None

    async def list_incidents(self, limit: int = 100) -> list[Incident]:
        async with self.conn.execute(
            "SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._incident_from_row(r) for r in rows]
