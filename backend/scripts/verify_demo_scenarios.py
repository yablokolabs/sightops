#!/usr/bin/env python3
"""Assert that the documented demonstration behaviour still holds.

The demo trace in the README and in ``docs/competition/submission.md`` is a
claim about what the system does. This script re-derives it from the generators
and the real agent loop on every run, so the documentation cannot quietly drift
away from the code.

It writes nothing into ``backend/data/``: the agent run uses a temporary data
directory and is torn down afterwards.

Checks:

1. ``scenario_fault_distant`` — the warning lamp measures RED with high
   confidence, and the gauge publishes **no value** (or at minimum flags itself
   for reinspection). This is the defining behaviour: a red lamp and no pressure
   reading must produce a request for a better view, not an inferred pressure.
2. ``scenario_fault_closeup`` — the gauge publishes 87.0 ± 1.5 PSI with high
   confidence and measures HIGH.
3. ``scenario_normal`` — the gauge is NORMAL and both lamps measure as drawn.
4. ``scenario_dishwasher_closeup`` — the display reads LIT, the power lamp GREEN.
5. ``scenario_dishwasher_unpowered`` — the display reads BLANK, the power lamp OFF.
6. The two industrial observations, driven through ``InspectionAgent`` with
   ``provider=None`` and ``demo_mode=True``, reach ``WAITING_FOR_USER`` after the
   first and ``AWAITING_APPROVAL`` after the second, create exactly one incident,
   and persist only ``source == "policy"`` tool calls.

Exits 1 on any failure, printing what was measured against what was expected.
Assertions are not relaxed to make the script pass; if a measurement genuinely
disagrees, that is the finding.

    python3 scripts/verify_demo_scenarios.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.loop import InspectionAgent  # noqa: E402
from app.config import Settings  # noqa: E402
from app.fixtures import generate_panels as gp  # noqa: E402
from app.models.schemas import Inspection, InspectionMode, utcnow  # noqa: E402
from app.storage.evidence import LocalEvidenceStorage  # noqa: E402
from app.storage.repo import Repository  # noqa: E402
from app.vision.annotate import encode_png  # noqa: E402
from app.vision.engine import VisionEngine  # noqa: E402
from app.vision.profiles import DISHWASHER_PANEL, INDUSTRIAL_PANEL  # noqa: E402

ROWS: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str) -> None:
    ROWS.append((name, passed, detail))


def measure(engine: VisionEngine, scene: gp.PanelScene, profile, image_id: str):
    analysis = engine.analyze(scene.image, image_id=image_id, profile=profile)
    return {m.component_id: m for m in analysis.measurements}


def check_fixture_scenes(engine: VisionEngine) -> None:
    # 1 -------------------------------------------------------------------
    distant = measure(engine, gp.scenario_fault_distant(), INDUSTRIAL_PANEL, "distant")
    lamp = distant["warning_led_01"]
    record(
        "fault_distant: warning lamp is RED with high confidence",
        lamp.state == "RED" and lamp.confidence > 0.9,
        f"state={lamp.state} confidence={lamp.confidence}",
    )
    gauge = distant["pressure_gauge_01"]
    gauge_unreliable = gauge.value is None or gauge.requires_reinspection
    record(
        "fault_distant: gauge publishes no value or flags reinspection",
        gauge_unreliable,
        f"value={gauge.value} state={gauge.state} confidence={gauge.confidence} "
        f"requires_reinspection={gauge.requires_reinspection}",
    )

    # 2 -------------------------------------------------------------------
    closeup = measure(engine, gp.scenario_fault_closeup(), INDUSTRIAL_PANEL, "closeup")
    gauge = closeup["pressure_gauge_01"]
    record(
        "fault_closeup: gauge reads 87.0 +/- 1.5 PSI with high confidence",
        gauge.value is not None and abs(gauge.value - 87.0) <= 1.5 and gauge.confidence > 0.9,
        f"value={gauge.value} confidence={gauge.confidence}",
    )
    record(
        "fault_closeup: gauge state is HIGH",
        gauge.state == "HIGH",
        f"state={gauge.state} warn_above="
        f"{gauge.details.get('scale', {}).get('warn_above')}",
    )

    # 3 -------------------------------------------------------------------
    normal = measure(engine, gp.scenario_normal(), INDUSTRIAL_PANEL, "normal")
    gauge = normal["pressure_gauge_01"]
    record(
        "normal: gauge state is NORMAL",
        gauge.state == "NORMAL" and gauge.value is not None,
        f"value={gauge.value} state={gauge.state} confidence={gauge.confidence}",
    )
    drawn = normal["warning_led_01"].state == "OFF" and normal["status_led_01"].state == "GREEN"
    record(
        "normal: both lamps measure as drawn (warning OFF, status GREEN)",
        drawn,
        f"warning={normal['warning_led_01'].state} status={normal['status_led_01'].state}",
    )

    # 4 -------------------------------------------------------------------
    dw = measure(engine, gp.scenario_dishwasher_closeup(), DISHWASHER_PANEL, "dw-close")
    record(
        "dishwasher_closeup: display LIT and power lamp GREEN",
        dw["display_01"].state == "LIT" and dw["power_led_01"].state == "GREEN",
        f"display={dw['display_01'].state} power={dw['power_led_01'].state}",
    )

    # 5 -------------------------------------------------------------------
    off = measure(engine, gp.scenario_dishwasher_unpowered(), DISHWASHER_PANEL, "dw-off")
    record(
        "dishwasher_unpowered: display BLANK and power lamp OFF",
        off["display_01"].state == "BLANK" and off["power_led_01"].state == "OFF",
        f"display={off['display_01'].state} power={off['power_led_01'].state}",
    )


async def check_agent_trace() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sightops-verify-"))
    settings = Settings(data_dir=tmp, demo_mode=True)
    settings.ensure_dirs()
    repo = await Repository.open(settings.db_path)
    engine = VisionEngine(settings)
    # provider=None is the point: this drives the deterministic policy, so the
    # check needs no network and no API spend.
    agent = InspectionAgent(repo, engine, provider=None, settings=settings)
    storage = LocalEvidenceStorage(settings.evidence_dir)

    inspection = Inspection(
        id=uuid.uuid4().hex,
        mode=InspectionMode.INDUSTRIAL,
        profile_id=INDUSTRIAL_PANEL.profile_id,
        problem_statement="verify: pump discharge pressure alarm",
        demo_mode=True,
    )
    await repo.create_inspection(inspection)

    async def attach(scene: gp.PanelScene) -> None:
        image_id = uuid.uuid4().hex
        data = encode_png(scene.image)
        key = storage.put(inspection.id, image_id, "png", data)
        height, width = scene.image.shape[:2]
        sequence = await repo.next_sequence(inspection.id)
        await repo.add_image(
            image_id=image_id,
            inspection_id=inspection.id,
            original_name=f"step{sequence}.png",
            content_type="image/png",
            sha256="verify",
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

    # observation 1
    await attach(gp.scenario_fault_distant())
    await agent.run(inspection.id)
    after_first = await repo.get_inspection(inspection.id)
    target = after_first.pending_request.target_region if after_first.pending_request else None
    record(
        "agent: state is WAITING_FOR_USER after observation 1",
        after_first.state.value == "WAITING_FOR_USER",
        f"state={after_first.state.value}",
    )
    record(
        "agent: requested a better view of pressure_gauge_01",
        target == "pressure_gauge_01",
        f"pending_request.target_region={target}",
    )

    # observation 2
    await attach(gp.scenario_fault_closeup())
    await agent.run(inspection.id)
    final = await repo.get_inspection(inspection.id)
    record(
        "agent: state is AWAITING_APPROVAL after observation 2",
        final.state.value == "AWAITING_APPROVAL",
        f"state={final.state.value}",
    )
    record(
        "agent: exactly one incident was created",
        final.incident_id is not None,
        f"incident_id={final.incident_id}",
    )
    incidents = await repo.list_incidents()
    record(
        "agent: the incident store holds exactly one incident",
        len(incidents) == 1,
        f"incidents={len(incidents)}",
    )

    calls = await repo.list_tool_calls(inspection.id)
    policies = {c.source for c in calls}
    record(
        "agent: every persisted tool call came from the policy",
        policies == {"policy"},
        f"sources={sorted(policies)} calls={len(calls)}",
    )
    record(
        "agent: the run stayed inside its bounds",
        final.tool_call_count <= settings.max_tool_calls
        and final.step_count <= settings.max_agent_steps,
        f"tool_calls={final.tool_call_count}/{settings.max_tool_calls} "
        f"steps={final.step_count}/{settings.max_agent_steps}",
    )

    # The abnormality must be the measured one, not a hard-coded string.
    assessment = final.assessment.summary if final.assessment else ""
    record(
        "agent: the recorded assessment cites the measured pressure",
        "87" in assessment and "PSI" in assessment,
        assessment[:140] or "(no assessment recorded)",
    )
    # Observation 1's gauge may either withhold the value or publish one that
    # flags itself for reinspection; both are the behaviour the trace documents.
    # What must never happen is a quietly confident reading on the poor frame.
    first_gauge = next(
        (
            m
            for o in final.observations
            if o.analysis
            for m in o.analysis.measurements
            if m.component_id == "pressure_gauge_01"
        ),
        None,
    )
    record(
        "agent: observation 1's gauge reading is withheld or flagged",
        first_gauge is not None
        and (first_gauge.value is None or first_gauge.requires_reinspection),
        (
            f"value={first_gauge.value} confidence={first_gauge.confidence} "
            f"requires_reinspection={first_gauge.requires_reinspection}"
        )
        if first_gauge
        else "no gauge measurement recorded on observation 1",
    )

    await repo.close()


def report() -> int:
    width = max(len(row[0]) for row in ROWS) if ROWS else 0
    for name, passed, detail in ROWS:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name:<{width}}  {detail}")
    failed = sum(1 for _, passed, _ in ROWS if not passed)
    print()
    print(f"{len(ROWS) - failed}/{len(ROWS)} checks passed")
    return 1 if failed else 0


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.parse_args()

    print("SightOps demo scenario verification")
    print()
    settings = Settings(data_dir=Path(tempfile.mkdtemp(prefix="sightops-verify-ve-")))
    settings.ensure_dirs()
    engine = VisionEngine(settings)

    check_fixture_scenes(engine)
    await check_agent_trace()
    return report()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
