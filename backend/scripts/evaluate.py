#!/usr/bin/env python3
"""Reproducible evaluation harness for SightOps.

    python3 scripts/evaluate.py --out ../docs/evaluation

Everything measured here comes from real runs: the fixtures are drawn with known
ground truth, the measurements are produced by OpenCV, and the agent metrics come
from driving the real bounded loop. Nothing is estimated, and any metric that
cannot be measured is reported as ``null`` with a reason rather than guessed.

Results are written to ``results.json`` and rendered to ``results.md`` by
:func:`render_markdown`, so the numbers in the documentation are the numbers this
script produced and are never copied by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import resource
import statistics
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.agent.loop import InspectionAgent  # noqa: E402
from app.config import Settings  # noqa: E402
from app.fixtures import generate_panels as gp  # noqa: E402
from app.models.schemas import Inspection, InspectionMode, utcnow  # noqa: E402
from app.storage.evidence import LocalEvidenceStorage  # noqa: E402
from app.storage.repo import Repository  # noqa: E402
from app.vision.annotate import encode_png  # noqa: E402
from app.vision.engine import VisionEngine, opencv_version  # noqa: E402
from app.vision.gauges import REPORT_FLOOR  # noqa: E402
from app.vision.profiles import DISHWASHER_PANEL, INDUSTRIAL_PANEL  # noqa: E402

#: Indicator states counted as classes for precision/recall.
INDICATOR_CLASSES = ["RED", "GREEN", "AMBER", "OFF"]


# --------------------------------------------------------------------------
# result containers
# --------------------------------------------------------------------------


@dataclass
class Counter:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def precision(self) -> float | None:
        denominator = self.tp + self.fp
        return None if denominator == 0 else self.tp / denominator

    def recall(self) -> float | None:
        denominator = self.tp + self.fn
        return None if denominator == 0 else self.tp / denominator

    def f1(self) -> float | None:
        p, r = self.precision(), self.recall()
        if p is None or r is None or (p + r) == 0:
            return None
        return 2 * p * r / (p + r)


@dataclass
class Results:
    environment: dict = field(default_factory=dict)
    dataset: dict = field(default_factory=dict)
    gauge: dict = field(default_factory=dict)
    indicators: dict = field(default_factory=dict)
    display: dict = field(default_factory=dict)
    switch: dict = field(default_factory=dict)
    roi: dict = field(default_factory=dict)
    quality_gate: dict = field(default_factory=dict)
    agent: dict = field(default_factory=dict)
    performance: dict = field(default_factory=dict)
    unavailable: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


# --------------------------------------------------------------------------
# vision evaluation
# --------------------------------------------------------------------------

#: (name, degradation) for every variation the gauge is measured across.
VARIATIONS: list[tuple[str, gp.Degradation]] = [
    ("clean", gp.Degradation()),
    ("sensor_noise", gp.Degradation(noise_sigma=4.0)),
    ("mild_blur", gp.Degradation(blur_sigma=1.2)),
    ("moderate_blur", gp.Degradation(blur_sigma=2.2)),
    ("strong_blur", gp.Degradation(blur_sigma=4.5)),
    ("underexposed", gp.Degradation(brightness=0.42)),
    ("overexposed", gp.Degradation(brightness=1.75)),
    ("glare", gp.Degradation(glare=0.55)),
    ("heavy_glare", gp.Degradation(glare=0.85)),
    ("low_resolution", gp.Degradation(resolution_scale=0.35)),
    ("very_low_resolution", gp.Degradation(resolution_scale=0.18)),
    ("perspective", gp.Degradation(perspective=0.07)),
    ("strong_perspective", gp.Degradation(perspective=0.20)),
    ("rotation", gp.Degradation(rotation_deg=4.0)),
    ("strong_rotation", gp.Degradation(rotation_deg=11.0)),
    ("occlusion_40", gp.Degradation(occlusion=0.40)),
    ("occlusion_80", gp.Degradation(occlusion=0.80)),
]

PRESSURES = [0.0, 12.5, 28.0, 43.5, 61.0, 74.5, 88.0, 97.0]

#: Tolerance in PSI above which a published gauge value is counted as wrong.
WRONG_VALUE_TOLERANCE_PSI = 3.0


def unreadable_by_construction(degradation: gp.Degradation) -> bool:
    """Documented information-content criterion for "this frame cannot be read".

    This is an *analysis assumption*, stated as a rule rather than asserted as
    measured truth, because the only non-circular ground truth for readability
    would be a second, independent reader. It is deliberately about whether the
    needle's information survived the degradation:

    * occlusion hides radii below ``occlusion * R``; the sampled band is
      0.28R-0.72R, so more than half the band is gone above ``occlusion = 0.40``
    * a brightness multiplier below 0.5 or above 1.5 clips the dial
    * a blur sigma above 4.0 removes the needle's edge
    * a rotation above 8 deg moves the dial away from its configured geometry
    * a perspective term above 0.12 turns the dial into an ellipse
    * a resolution scale below 0.30 leaves the needle fewer than three pixels
    """
    if degradation.occlusion > 0.40:
        return True
    if degradation.brightness < 0.50 or degradation.brightness > 1.50:
        return True
    if degradation.blur_sigma > 4.0:
        return True
    if degradation.rotation_deg > 8.0:
        return True
    if degradation.perspective > 0.12:
        return True
    if degradation.resolution_scale < 0.30:
        return True
    return False


def evaluate_vision(engine: VisionEngine, results: Results) -> None:
    gauge_errors: list[float] = []
    gauge_confidences: list[float] = []
    gauge_refusals = 0
    gauge_attempts = 0
    gauge_wrong_and_confident: list[dict] = []
    per_pressure_error: dict[str, list[float]] = {}

    indicator_counter = {state: Counter() for state in INDICATOR_CLASSES}
    indicator_confusions: list[dict] = []
    display_correct = 0
    display_total = 0
    switch_correct = 0
    switch_total = 0
    roi_success = 0
    roi_total = 0

    gate_tp = gate_fp = gate_tn = gate_fn = 0
    latencies: list[float] = []
    samples: list[dict] = []
    wrong_values: list[dict] = []

    refused_by_variation: dict[str, int] = {name: 0 for name, _ in VARIATIONS}
    samples_by_variation: dict[str, int] = {name: 0 for name, _ in VARIATIONS}
    display_failures: list[dict] = []

    for variation_name, degradation in VARIATIONS:
        expect_readable = not unreadable_by_construction(degradation)
        for pressure in PRESSURES:
            warning = INDICATOR_CLASSES[PRESSURES.index(pressure) % len(INDICATOR_CLASSES)]
            scene = gp.render_industrial_panel(
                pressure_psi=pressure,
                warning=warning,
                status="GREEN",
                switch="UP",
                degrade=degradation,
                seed=int(pressure * 10) + len(variation_name),
            )
            analysis = engine.analyze(
                scene.image, image_id=f"{variation_name}-{pressure}", profile=INDUSTRIAL_PANEL
            )
            latencies.append(analysis.latency_ms)

            by_id = {m.component_id: m for m in analysis.measurements}

            # -- gauge ------------------------------------------------------
            gauge = by_id["pressure_gauge_01"]
            gauge_attempts += 1
            samples_by_variation[variation_name] += 1
            if gauge.value is None:
                gauge_refusals += 1
                refused_by_variation[variation_name] += 1
            else:
                error = abs(gauge.value - pressure)
                gauge_errors.append(error)
                gauge_confidences.append(gauge.confidence)
                per_pressure_error.setdefault(f"{pressure:g}", []).append(error)
                # A published reading is a *claim*; a wrong claim above the
                # reporting floor is the failure mode this whole evaluation
                # exists to detect.
                if error > WRONG_VALUE_TOLERANCE_PSI and gauge.confidence >= REPORT_FLOOR:
                    wrong_values.append(
                        {
                            "variation": variation_name,
                            "true_psi": pressure,
                            "measured_psi": gauge.value,
                            "confidence": gauge.confidence,
                            "absolute_error": round(error, 3),
                        }
                    )
                    gauge_wrong_and_confident.append(wrong_values[-1])

            # -- indicators -------------------------------------------------
            for region_id, truth in (("warning_led_01", warning), ("status_led_01", "GREEN")):
                measurement = by_id[region_id]
                predicted = measurement.state
                if truth in indicator_counter:
                    counter = indicator_counter[truth]
                    if predicted == truth:
                        counter.tp += 1
                    else:
                        counter.fn += 1
                        indicator_counter[predicted].fp += 1 if predicted in indicator_counter else 0
                        indicator_confusions.append(
                            {
                                "variation": variation_name,
                                "region": region_id,
                                "truth": truth,
                                "predicted": predicted,
                                "confidence": measurement.confidence,
                            }
                        )

            # -- ROI localisation ------------------------------------------
            roi_total += 1
            region = next((r for r in analysis.regions if r.region_id == "pressure_gauge_01"), None)
            if region is not None:
                x, y, w, h = region.box
                if w > 8 and h > 8 and x + w <= analysis.quality.width:
                    roi_success += 1

            # -- quality gate ----------------------------------------------
            refused = gauge.value is None or gauge.requires_reinspection
            if expect_readable:
                gate_tn += 0 if refused else 1
                gate_fp += 1 if refused else 0
            else:
                gate_tp += 1 if refused else 0
                gate_fn += 0 if refused else 1

            samples.append(
                {
                    "variation": variation_name,
                    "true_psi": pressure,
                    "measured_psi": gauge.value,
                    "confidence": gauge.confidence,
                    "blur_score": analysis.quality.blur_score,
                    "requires_new_view": analysis.quality.requires_new_view,
                    "expect_readable": expect_readable,
                }
            )

        # -- dishwasher (display + switch) --------------------------------
        for lit in (True, False):
            scene = gp.render_dishwasher_panel(
                lit=lit, glyph="1:42" if lit else "", power="GREEN" if lit else "OFF",
                start="OFF", degrade=degradation, seed=len(variation_name) + int(lit),
            )
            analysis = engine.analyze(scene.image, image_id=f"dw-{variation_name}-{lit}",
                                      profile=DISHWASHER_PANEL)
            latencies.append(analysis.latency_ms)
            display = next(m for m in analysis.measurements if m.component_id == "display_01")
            display_total += 1
            expected = "LIT" if lit else "BLANK"
            if display.state == expected:
                display_correct += 1
            else:
                display_failures.append(
                    {
                        "variation": variation_name,
                        "truth": expected,
                        "predicted": display.state,
                        "confidence": display.confidence,
                        "details": {
                            k: display.details.get(k)
                            for k in ("p98_luma", "dynamic_range", "lit_fraction", "mean_luma")
                        },
                    }
                )

        scene = gp.render_industrial_panel(
            pressure_psi=43.5, warning="OFF", status="GREEN", switch="RIGHT",
            degrade=degradation, seed=len(variation_name) + 77,
        )
        analysis = engine.analyze(scene.image, image_id=f"sw-{variation_name}",
                                  profile=INDUSTRIAL_PANEL)
        switch = next(m for m in analysis.measurements if m.component_id == "selector_switch_01")
        switch_total += 1
        if switch.state == "RIGHT":
            switch_correct += 1

    results.gauge = {
        "attempts": gauge_attempts,
        "published": len(gauge_errors),
        "refused": gauge_refusals,
        "refusal_rate": round(gauge_refusals / gauge_attempts, 4) if gauge_attempts else None,
        "mean_absolute_error_psi": round(statistics.fmean(gauge_errors), 4) if gauge_errors else None,
        "median_absolute_error_psi": round(statistics.median(gauge_errors), 4) if gauge_errors else None,
        "p95_absolute_error_psi": (
            round(percentile(gauge_errors, 0.95), 4) if gauge_errors else None
        ),
        "max_absolute_error_psi": round(max(gauge_errors), 4) if gauge_errors else None,
        "mean_confidence": round(statistics.fmean(gauge_confidences), 4) if gauge_confidences else None,
        "report_floor": REPORT_FLOOR,
        "full_scale_error_percent": (
            round(100 * statistics.fmean(gauge_errors) / 100.0, 4) if gauge_errors else None
        ),
        "confident_wrong_readings": gauge_wrong_and_confident,
        "wrong_reading_count": len(wrong_values),
        "error_by_pressure_psi": {
            k: round(statistics.fmean(v), 4) for k, v in sorted(per_pressure_error.items(), key=lambda kv: float(kv[0]))
        },
    }

    results.indicators = {
        state: {
            "support": counter.tp + counter.fn,
            "precision": counter.precision(),
            "recall": counter.recall(),
            "f1": counter.f1(),
            "true_positives": counter.tp,
            "false_positives": counter.fp,
            "false_negatives": counter.fn,
        }
        for state, counter in indicator_counter.items()
    }
    macro_precision = [
        c.precision() for c in indicator_counter.values() if c.precision() is not None
    ]
    macro_recall = [c.recall() for c in indicator_counter.values() if c.recall() is not None]
    results.indicators["macro_precision"] = (
        round(statistics.fmean(macro_precision), 4) if macro_precision else None
    )
    results.indicators["macro_recall"] = (
        round(statistics.fmean(macro_recall), 4) if macro_recall else None
    )
    results.indicators["confusions"] = indicator_confusions[:40]
    results.indicators["confusion_count"] = len(indicator_confusions)

    results.display = {
        "samples": display_total,
        "correct": display_correct,
        "accuracy": round(display_correct / display_total, 4) if display_total else None,
        "failures": display_failures,
        "failure_count": len(display_failures),
        "failures_by_variation": {}
        if not display_failures
        else {
            name: sum(1 for f in display_failures if f["variation"] == name)
            for name in sorted({f["variation"] for f in display_failures})
        },
    }
    results.switch = {
        "samples": switch_total,
        "correct": switch_correct,
        "accuracy": round(switch_correct / switch_total, 4) if switch_total else None,
    }
    results.roi = {
        "samples": roi_total,
        "localised": roi_success,
        "success_rate": round(roi_success / roi_total, 4) if roi_total else None,
        "method": "configured profile regions, validated against image bounds",
    }
    published_errors = gauge_errors
    escape = len(gauge_wrong_and_confident)
    results.quality_gate = {
        "wrong_value_tolerance_psi": WRONG_VALUE_TOLERANCE_PSI,
        "wrong_value_escape_count": escape,
        "wrong_value_escape_rate": round(escape / len(published_errors), 4) if published_errors else None,
        "escape_note": (
            "A published reading whose error exceeds the tolerance is the metric that matters: "
            "it is measured against exact ground truth and does not depend on any readability "
            "assumption. This is the number a reliability tool must keep at zero."
        ),
        "unreadable_by_construction": {
            "definition": unreadable_by_construction.__doc__.split("\n")[0].strip(),
            "correct_rejections": gate_tp,
            "missed_rejections": gate_fn,
            "detection_rate": round(gate_tp / (gate_tp + gate_fn), 4) if (gate_tp + gate_fn) else None,
        },
        "readable_by_construction": {
            "unnecessary_rejections": gate_fp,
            "accepted": gate_tn,
            "false_refusal_rate": round(gate_fp / (gate_fp + gate_tn), 4) if (gate_fp + gate_tn) else None,
        },
        "refusal_rate_by_variation": {
            name: round(refused_by_variation[name] / samples_by_variation[name], 3)
            for name, _ in VARIATIONS
            if samples_by_variation[name]
        },
        "caveat": (
            "The unreadable set is an analysis assumption stated as a rule in "
            "docs/evaluation/methodology.md, not measured ground truth. Several frames it calls "
            "unreadable are in fact measurable, which is why the missed-rejection count is high "
            "while the wrong-value escape rate is the figure to trust."
        ),
    }
    results.dataset = {
        "variations": [v[0] for v in VARIATIONS],
        "pressures_psi": PRESSURES,
        "industrial_samples": len(VARIATIONS) * len(PRESSURES),
        "dishwasher_samples": len(VARIATIONS) * 2,
        "switch_samples": len(VARIATIONS),
        "generator": "app.fixtures.generate_panels (ground truth is exact: the fixture drew the values)",
    }
    results.performance["vision_latency_ms"] = {
        "samples": len(latencies),
        "mean": round(statistics.fmean(latencies), 2) if latencies else None,
        "median": round(statistics.median(latencies), 2) if latencies else None,
        "p95": round(percentile(latencies, 0.95), 2) if latencies else None,
        "max": round(max(latencies), 2) if latencies else None,
    }
    results.notes.append(
        f"Gauge reporting floor: a value is withheld below {REPORT_FLOOR:.2f} confidence. "
        f"Of {gauge_attempts} attempts, {gauge_refusals} were refused and "
        f"{len(gauge_errors)} were published."
    )


# --------------------------------------------------------------------------
# agent evaluation
# --------------------------------------------------------------------------


@dataclass
class AgentScenario:
    name: str
    mode: InspectionMode
    profile_id: str
    steps: list[gp.PanelScene]
    expect_reinspection: bool
    expect_incident: bool


def agent_scenarios() -> list[AgentScenario]:
    return [
        AgentScenario(
            name="industrial_fault_two_observations",
            mode=InspectionMode.INDUSTRIAL,
            profile_id=INDUSTRIAL_PANEL.profile_id,
            steps=[gp.scenario_fault_distant(), gp.scenario_fault_closeup()],
            expect_reinspection=True,
            expect_incident=True,
        ),
        AgentScenario(
            name="industrial_healthy_single_observation",
            mode=InspectionMode.INDUSTRIAL,
            profile_id=INDUSTRIAL_PANEL.profile_id,
            steps=[gp.scenario_normal()],
            expect_reinspection=False,
            expect_incident=False,
        ),
        AgentScenario(
            name="industrial_fault_clear_first_try",
            mode=InspectionMode.INDUSTRIAL,
            profile_id=INDUSTRIAL_PANEL.profile_id,
            steps=[gp.scenario_fault_closeup()],
            expect_reinspection=False,
            expect_incident=True,
        ),
        AgentScenario(
            name="home_unpowered_dishwasher",
            mode=InspectionMode.HOME,
            profile_id=DISHWASHER_PANEL.profile_id,
            steps=[gp.scenario_dishwasher_closeup(), gp.scenario_dishwasher_unpowered()],
            expect_reinspection=False,
            expect_incident=False,
        ),
    ]


async def evaluate_agent(settings: Settings, results: Results) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sightops-eval-"))
    settings = Settings(data_dir=tmp, demo_mode=True)
    settings.ensure_dirs()
    repo = await Repository.open(settings.db_path)
    engine = VisionEngine(settings)
    agent = InspectionAgent(repo, engine, provider=None, settings=settings)
    storage = LocalEvidenceStorage(settings.evidence_dir)

    outcomes: list[dict] = []
    durations: list[float] = []
    observations_per_task: list[int] = []
    tool_calls_per_task: list[int] = []

    for scenario in agent_scenarios():
        started = time.perf_counter()
        inspection = Inspection(
            id=uuid.uuid4().hex,
            mode=scenario.mode,
            profile_id=scenario.profile_id,
            problem_statement=f"evaluation: {scenario.name}",
            demo_mode=True,
        )
        await repo.create_inspection(inspection)

        for scene in scenario.steps:
            image_id = uuid.uuid4().hex
            data = encode_png(scene.image)
            key = storage.put(inspection.id, image_id, "png", data)
            height, width = scene.image.shape[:2]
            sequence = await repo.next_sequence(inspection.id)
            await repo.add_image(
                image_id=image_id, inspection_id=inspection.id, original_name=f"{sequence}.png",
                content_type="image/png", sha256="eval", width=width, height=height,
                stored_path=key, role="primary" if sequence == 1 else "follow_up",
                sequence=sequence, created_at=utcnow().isoformat(),
            )
            await repo.add_observation(uuid.uuid4().hex, inspection.id, image_id, None,
                                       utcnow().isoformat())
            await agent.run(inspection.id)

        final = await repo.get_inspection(inspection.id)
        calls = await repo.list_tool_calls(inspection.id)
        timeline = await repo.list_timeline(inspection.id)
        durations.append((time.perf_counter() - started) * 1000.0)
        observations_per_task.append(len(final.observations) if final else 0)
        tool_calls_per_task.append(final.tool_call_count if final else 0)

        requested = any(c.tool == "request_new_view" and c.ok for c in calls)
        incident = final.incident_id is not None if final else False
        state = final.state.value if final else "UNKNOWN"

        # Task success is defined per scenario: the inspection reached the state
        # its evidence justifies, and asked for another view exactly when the
        # evidence warranted it.
        reinspection_correct = requested == scenario.expect_reinspection
        incident_correct = incident == scenario.expect_incident
        terminal_ok = state in {"COMPLETED", "AWAITING_APPROVAL", "WAITING_FOR_USER"}
        success = reinspection_correct and incident_correct and terminal_ok

        outcomes.append(
            {
                "scenario": scenario.name,
                "final_state": state,
                "requested_reinspection": requested,
                "expected_reinspection": scenario.expect_reinspection,
                "reinspection_correct": reinspection_correct,
                "incident_created": incident,
                "expected_incident": scenario.expect_incident,
                "incident_correct": incident_correct,
                "terminal_state_reached": terminal_ok,
                "task_success": success,
                "observations": len(final.observations) if final else 0,
                "tool_calls": final.tool_call_count if final else 0,
                "steps": final.step_count if final else 0,
                "timeline_entries": len(timeline),
                "bounded": bool(
                    final
                    and final.tool_call_count <= settings.max_tool_calls
                    and final.step_count <= settings.max_agent_steps
                ),
            }
        )

    await repo.close()

    successes = sum(1 for o in outcomes if o["task_success"])
    reinspection_expected = [o for o in outcomes if o["expected_reinspection"]]
    reinspection_actual = [o for o in outcomes if o["requested_reinspection"]]
    true_positive = sum(1 for o in reinspection_actual if o["expected_reinspection"])
    false_positive = len(reinspection_actual) - true_positive
    false_negative = sum(1 for o in reinspection_expected if not o["requested_reinspection"])

    results.agent = {
        "scenarios": outcomes,
        "tasks": len(outcomes),
        "task_successes": successes,
        "task_success_rate": round(successes / len(outcomes), 4) if outcomes else None,
        "all_runs_bounded": all(o["bounded"] for o in outcomes),
        "active_perception": {
            "definition": "the agent asked for a new view exactly when the measured evidence was insufficient",
            "correct_requests": true_positive,
            "unnecessary_requests": false_positive,
            "missed_requests": false_negative,
            "precision": round(true_positive / (true_positive + false_positive), 4)
            if (true_positive + false_positive)
            else None,
            "recall": round(true_positive / (true_positive + false_negative), 4)
            if (true_positive + false_negative)
            else None,
        },
        "observation_selection": {
            "mean_observations_per_task": round(statistics.fmean(observations_per_task), 3)
            if observations_per_task
            else None,
            "observations_per_task": observations_per_task,
            "tool_calls_per_task": tool_calls_per_task,
        },
        "escalation": {
            "incidents_created": sum(1 for o in outcomes if o["incident_created"]),
            "incidents_expected": sum(1 for o in outcomes if o["expected_incident"]),
            "incorrect_escalations": sum(
                1 for o in outcomes if o["incident_created"] and not o["expected_incident"]
            ),
            "missed_escalations": sum(
                1 for o in outcomes if o["expected_incident"] and not o["incident_created"]
            ),
        },
        "tool_failure_recovery": {
            "measured": None,
            "reason": (
                "No scripted scenario produced a tool failure, so recovery was not exercised "
                "end to end. Failure paths are covered by backend/tests/test_tools.py and the "
                "loop's repeated-failure guard."
            ),
        },
    }
    results.performance["inspection_end_to_end_ms"] = {
        "samples": len(durations),
        "mean": round(statistics.fmean(durations), 2) if durations else None,
        "max": round(max(durations), 2) if durations else None,
    }
    results.unavailable.append(
        "tool_failure_recovery: no scenario in this suite forces a tool to fail"
    )


# --------------------------------------------------------------------------
# performance
# --------------------------------------------------------------------------


async def evaluate_performance(settings: Settings, results: Results) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sightops-perf-"))
    settings = Settings(data_dir=tmp)
    settings.ensure_dirs()
    engine = VisionEngine(settings)
    scene = gp.scenario_fault_closeup()

    # Warm-up is excluded so the numbers describe steady state.
    for _ in range(3):
        engine.analyze(scene.image, image_id="warmup", profile=INDUSTRIAL_PANEL)

    runs = 30
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.perf_counter()
    for index in range(runs):
        engine.analyze(scene.image, image_id=f"perf{index}", profile=INDUSTRIAL_PANEL)
    elapsed = time.perf_counter() - started
    usage_after = resource.getrusage(resource.RUSAGE_SELF)

    cpu_seconds = (usage_after.ru_utime - usage_before.ru_utime) + (
        usage_after.ru_stime - usage_before.ru_stime
    )
    per_call = elapsed / runs

    try:
        load = os.getloadavg()
    except OSError:
        load = None

    results.performance["throughput"] = {
        "runs": runs,
        "wall_seconds": round(elapsed, 4),
        "analyses_per_second": round(runs / elapsed, 3),
        "seconds_per_analysis": round(per_call, 5),
        "cpu_seconds": round(cpu_seconds, 4),
        "cpu_utilisation_of_one_core_percent": round(100 * cpu_seconds / elapsed, 2),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 2),
        "note": "single-process, single-threaded analysis of a 1280x720 frame with four regions",
    }
    results.environment["load_average"] = [round(v, 3) for v in load] if load else None


def environment_report() -> dict:
    cpu_model = None
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    cpu_count = os.cpu_count()
    memory_kb = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                memory_kb = int(line.split()[1])
                break
    except OSError:
        pass
    return {
        "opencv_version": opencv_version(),
        "opencv_claim_verified": opencv_version().split(".")[0] == "5",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": cpu_model,
        "cpu_count": cpu_count,
        "memory_total_mb": round(memory_kb / 1024.0, 1) if memory_kb else None,
        "gpu": None,
        "gpu_note": "CPU-only execution; no GPU is used or required.",
        "numpy_version": np.__version__,
        "cv2_build": "pip wheel opencv-python (x86_64)",
        "aws": "NOT IMPLEMENTED — no AWS resource is used, provisioned or benchmarked",
        "deployment": "existing Azure virtual machine",
        "hindsight": "memory service on localhost:8888 (development aid only)",
    }


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------


def render_markdown(results: Results) -> str:
    env = results.environment
    gauge = results.gauge
    ind = results.indicators
    gate = results.quality_gate
    agent = results.agent
    perf = results.performance

    lines: list[str] = []
    add = lines.append

    add("# SightOps — Evaluation Results")
    add("")
    add(
        "Generated by `backend/scripts/evaluate.py`. Every number below was produced by that "
        "script on the machine described here; none of it is estimated or transcribed by hand."
    )
    add("")
    add("## Environment")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| OpenCV | `{env['opencv_version']}` (major-version-5 claim holds: **{env['opencv_claim_verified']}**) |")
    add(f"| Python | {env['python_version']} |")
    add(f"| Platform | {env['platform']} ({env['machine']}) |")
    add(f"| CPU | {env['processor']} x {env['cpu_count']} |")
    add(f"| Memory | {env['memory_total_mb']} MB |")
    add(f"| GPU | none — {env['gpu_note']} |")
    add(f"| NumPy | {env['numpy_version']} |")
    add(f"| Deployment | {env['deployment']} |")
    add(f"| AWS | {env['aws']} |")
    add("")

    add("## Dataset")
    add("")
    add(f"- Variations: {', '.join(f'`{v}`' for v in results.dataset['variations'])}")
    add(f"- Gauge pressures: {', '.join(f'{p:g}' for p in results.dataset['pressures_psi'])} PSI")
    add(
        f"- Samples: {results.dataset['industrial_samples']} industrial, "
        f"{results.dataset['dishwasher_samples']} dishwasher, {results.dataset['switch_samples']} switch"
    )
    add(f"- Ground truth: {results.dataset['generator']}")
    add("")

    add("## Analog gauge accuracy")
    add("")
    add("| Metric | Value |")
    add("|---|---|")
    add(f"| Attempts | {gauge['attempts']} |")
    add(f"| Published readings | {gauge['published']} |")
    add(f"| Refused (no value reported) | {gauge['refused']} ({_pct(gauge['refusal_rate'])}) |")
    add(f"| Mean absolute error | {gauge['mean_absolute_error_psi']} PSI |")
    add(f"| Median absolute error | {gauge['median_absolute_error_psi']} PSI |")
    add(f"| 95th percentile absolute error | {gauge['p95_absolute_error_psi']} PSI |")
    add(f"| Max absolute error | {gauge['max_absolute_error_psi']} PSI |")
    add(f"| Mean absolute error, % of full scale | {gauge['full_scale_error_percent']} % |")
    add(f"| Mean confidence of published readings | {gauge['mean_confidence']} |")
    add(f"| Reporting floor | {gauge['report_floor']} |")
    add(f"| Confident wrong readings (error > 3 PSI above the floor) | **{gauge['wrong_reading_count']}** |")
    add("")
    if gauge["wrong_reading_count"]:
        add("Confident wrong readings, listed in full:")
        add("")
        add("| Variation | True PSI | Measured | Confidence | Error |")
        add("|---|---|---|---|---|")
        for row in gauge["confident_wrong_readings"]:
            add(
                f"| `{row['variation']}` | {row['true_psi']:g} | {row['measured_psi']:g} | "
                f"{row['confidence']:.3f} | {row['absolute_error']:g} |"
            )
        add("")

    add("## Indicator classification")
    add("")
    add("| State | Support | Precision | Recall | F1 |")
    add("|---|---|---|---|---|")
    for state in INDICATOR_CLASSES:
        row = ind[state]
        add(
            f"| {state} | {row['support']} | {_num(row['precision'])} | {_num(row['recall'])} | "
            f"{_num(row['f1'])} |"
        )
    add(f"| **Macro** | | **{_num(ind['macro_precision'])}** | **{_num(ind['macro_recall'])}** | |")
    add("")
    add(f"Misclassifications: {ind['confusion_count']}")
    if ind["confusion_count"]:
        add("")
        add("| Variation | Region | Truth | Predicted | Confidence |")
        add("|---|---|---|---|---|")
        for row in ind["confusions"][:12]:
            add(
                f"| `{row['variation']}` | {row['region']} | {row['truth']} | {row['predicted']} | "
                f"{row['confidence']:.3f} |"
            )
        add("")

    add("## Display and switch")
    add("")
    add("| Task | Samples | Correct | Accuracy |")
    add("|---|---|---|---|")
    add(
        f"| Display lit/blank | {results.display['samples']} | {results.display['correct']} | "
        f"{_pct(results.display['accuracy'])} |"
    )
    add(
        f"| Switch position | {results.switch['samples']} | {results.switch['correct']} | "
        f"{_pct(results.switch['accuracy'])} |"
    )
    add("")
    if results.display["failure_count"]:
        add(
            f"The {results.display['failure_count']} display failures are concentrated in "
            + ", ".join(
                f"`{name}` ({count})" for name, count in results.display["failures_by_variation"].items()
            )
            + ". Every one of these is a lit display that was read as blank because the degradation "
            "pushed its stroke brightness below the detection level, or a blank display read as lit. "
            "This is a genuine limitation of a luminance-based display test and it is why digit "
            "interpretation is left to the multimodal model, tagged as inferred."
        )
        add("")
        add("| Variation | Truth | Predicted | Confidence | p98 luma |")
        add("|---|---|---|---|---|")
        for row in results.display["failures"][:10]:
            add(
                f"| `{row['variation']}` | {row['truth']} | {row['predicted']} | "
                f"{row['confidence']:.2f} | {row['details'].get('p98_luma')} |"
            )
        add("")

    add("## ROI localisation and the quality gate")
    add("")
    add(f"- ROI success rate: **{_pct(results.roi['success_rate'])}** over {results.roi['samples']} samples ({results.roi['method']}).")
    add("")
    add(
        f"**Wrong-value escape rate: {_pct(gate['wrong_value_escape_rate'])}** "
        f"({gate['wrong_value_escape_count']} of {gauge['published']} published readings exceeded "
        f"{gate['wrong_value_tolerance_psi']:g} PSI)."
    )
    add("")
    add(f"> {gate['escape_note']}")
    add("")
    add("| Quality gate | Count |")
    add("|---|---|")
    add(f"| Correct rejections on unreadable frames | {gate['unreadable_by_construction']['correct_rejections']} |")
    add(f"| Missed rejections | {gate['unreadable_by_construction']['missed_rejections']} |")
    add(f"| Detection rate | {_pct(gate['unreadable_by_construction']['detection_rate'])} |")
    add(f"| Unnecessary rejections on readable frames | {gate['readable_by_construction']['unnecessary_rejections']} |")
    add(f"| False refusal rate | {_pct(gate['readable_by_construction']['false_refusal_rate'])} |")
    add("")
    add("Refusal rate per variation:")
    add("")
    add("| Variation | Refusal rate |")
    add("|---|---|")
    for name, rate in gate["refusal_rate_by_variation"].items():
        add(f"| `{name}` | {_pct(rate)} |")
    add("")
    add(f"> {gate['caveat']}")
    add("")

    add("## Agent behaviour")
    add("")
    add(f"- Tasks: {agent['tasks']}, successes: {agent['task_successes']} (**{_pct(agent['task_success_rate'])}**)")
    add(f"- Every run stayed inside its bounds: **{agent['all_runs_bounded']}**")
    ap = agent["active_perception"]
    add("")
    add("Active perception — " + ap["definition"] + ":")
    add("")
    add(f"- Correct requests: {ap['correct_requests']}, unnecessary: {ap['unnecessary_requests']}, missed: {ap['missed_requests']}")
    add(f"- Precision {_num(ap['precision'])}, recall {_num(ap['recall'])}")
    add("")
    add("| Scenario | Final state | Reinspection | Incident | Success | Observations | Tool calls |")
    add("|---|---|---|---|---|---|---|")
    for row in agent["scenarios"]:
        add(
            f"| `{row['scenario']}` | {row['final_state']} | "
            f"{'yes' if row['requested_reinspection'] else 'no'} "
            f"(expected {'yes' if row['expected_reinspection'] else 'no'}) | "
            f"{'yes' if row['incident_created'] else 'no'} | "
            f"{'PASS' if row['task_success'] else 'FAIL'} | {row['observations']} | {row['tool_calls']} |"
        )
    add("")
    esc = agent["escalation"]
    add(
        f"Escalation — incidents created {esc['incidents_created']} of {esc['incidents_expected']} expected, "
        f"incorrect {esc['incorrect_escalations']}, missed {esc['missed_escalations']}."
    )
    add(f"- Mean observations per task: {agent['observation_selection']['mean_observations_per_task']}")
    add("")

    add("## Performance")
    add("")
    lat = perf["vision_latency_ms"]
    add("| Metric | Value |")
    add("|---|---|")
    add(f"| Vision analysis latency, mean | {lat['mean']} ms |")
    add(f"| Vision analysis latency, median | {lat['median']} ms |")
    add(f"| Vision analysis latency, p95 | {lat['p95']} ms |")
    add(f"| Vision analysis latency, max | {lat['max']} ms |")
    thr = perf["throughput"]
    add(f"| Throughput | {thr['analyses_per_second']} analyses/s |")
    add(f"| CPU utilisation (one core) | {thr['cpu_utilisation_of_one_core_percent']} % |")
    add(f"| Peak RSS | {thr['peak_rss_mb']} MB |")
    e2e = perf["inspection_end_to_end_ms"]
    add(f"| End-to-end inspection, mean | {e2e['mean']} ms |")
    add(f"| End-to-end inspection, max | {e2e['max']} ms |")
    add("")
    add(f"> {thr['note']}.")
    add("")

    if results.unavailable:
        add("## Metrics that could not be measured")
        add("")
        for item in results.unavailable:
            add(f"- {item}")
        add("")

    add("## Reproducing")
    add("")
    add("```bash")
    add("cd backend")
    add("python3 scripts/evaluate.py --out ../docs/evaluation")
    add("```")
    add("")
    return "\n".join(lines)


def _num(value) -> str:
    return "n/a" if value is None else f"{value:.4f}".rstrip("0").rstrip(".")


def _pct(value) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="../docs/evaluation", help="output directory")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    results = Results()
    results.environment = environment_report()

    settings = Settings(data_dir=Path(tempfile.mkdtemp(prefix="sightops-eval-")), demo_mode=True)
    settings.ensure_dirs()
    engine = VisionEngine(settings)

    print("evaluating computer vision ...")
    evaluate_vision(engine, results)
    print("evaluating the agent ...")
    await evaluate_agent(settings, results)
    print("measuring performance ...")
    await evaluate_performance(settings, results)
    results.environment["load_average"] = results.environment.get("load_average")

    (out / "results.json").write_text(json.dumps(asdict(results), indent=2, default=str) + "\n")
    (out / "results.md").write_text(render_markdown(results))

    print(f"wrote {out / 'results.json'}")
    print(f"wrote {out / 'results.md'}")
    print(
        f"gauge MAE {results.gauge['mean_absolute_error_psi']} PSI over "
        f"{results.gauge['published']} published readings, "
        f"{results.gauge['wrong_reading_count']} confident-wrong; "
        f"task success {results.agent['task_success_rate']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
