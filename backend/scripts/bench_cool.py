#!/usr/bin/env python3
"""Measure the SightOps vision pipeline on one benchmark arm.

    python3 scripts/bench_cool.py \\
        --arm azure-vm-x86_64-stock-wheel \\
        --repetitions 200 --warmup 20 --threads 1 \\
        --out /tmp/bench-azure-x86.json

This implements the method in ``docs/benchmarks/cool-methodology.md``. It reports
**single-frame latency** and **throughput** for ``VisionEngine.analyze()`` — the
entry point the API itself calls, not a microbenchmark of ``cv2`` functions —
over the same fixtures the accuracy evaluation uses, so the benchmark and the
measured accuracy describe the same pixels. It also reports a per-operation
split, so a difference can be attributed to one stage rather than to the
pipeline as a whole.

    *** THIS SCRIPT DOES NOT USE AWS. ***
    It provisions nothing and drives no cloud API. The COOL-on-Graviton arm of
    the comparison needs a Graviton instance, which is billable and must not be
    created without authorisation. What this can produce today is the x86
    baseline arm, on the machine it is run on. The arm name is therefore
    required and is recorded verbatim: naming it honestly is what stops the
    report being mistaken for a machine it was not produced on.

Nothing is estimated. The environment, the OpenCV build flags, the thread count
actually in use, the fixture-set digest and the CPU and memory consumed are all
recorded because a latency number without them is not reproducible. No cost
figure is recorded, because no price has been looked up.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.config import Settings  # noqa: E402
from app.fixtures import generate_panels as gp  # noqa: E402
from app.vision import gauges, indicators, quality, regions  # noqa: E402
from app.vision.engine import VisionEngine, opencv_version  # noqa: E402
from app.vision.preprocess import crop_region, to_working_copy  # noqa: E402
from app.vision.profiles import INDUSTRIAL_PANEL  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: The thread count OpenCV was using before this script touched it. Captured at
#: import so it cannot be confused with a value this script set. The throughput
#: arm restores this, which is what "at the default thread count" means.
DEFAULT_THREADS = cv2.getNumThreads()

AUTHORISATION_WARNING = (
    "The COOL-on-Graviton arm needs an AWS Graviton instance. That is billable "
    "capacity and must not be provisioned without authorisation. This script does "
    "not create, start or contact anything: it measures the machine it runs on. "
    "The report records --arm verbatim, so a baseline run can never be read as a "
    "COOL result."
)

#: The frames the accuracy evaluation uses, so the benchmark describes the same
#: pixels as the reported accuracy. Order is fixed, and the digest below depends
#: on it.
FIXTURES: list[tuple[str, object]] = [
    ("industrial_normal", gp.scenario_normal),
    ("industrial_fault_distant", gp.scenario_fault_distant),
    ("industrial_fault_closeup", gp.scenario_fault_closeup),
    ("dishwasher_wide", gp.scenario_dishwasher_wide),
    ("dishwasher_closeup", gp.scenario_dishwasher_closeup),
    ("dishwasher_unpowered", gp.scenario_dishwasher_unpowered),
]

#: The operational split is only meaningful on frames that actually contain the
#: component being timed, so the gauge and indicator operations use the
#: industrial panels and say so in the report. The frame-level operations
#: (blur scoring, panel detection) use every fixture.
INDUSTRIAL_OPERATION_FIXTURES = [
    "industrial_normal",
    "industrial_fault_distant",
    "industrial_fault_closeup",
]

#: Lines of ``cv2.getBuildInformation()`` worth keeping: the build is the
#: independent variable in a COOL comparison, so the CPU baseline and dispatch
#: flags have to be in the report.
_WANTED_BUILD_PREFIXES = (
    "General configuration for OpenCV",
    "CPU/HW features",
    "Baseline:",
    "requested:",
    "dispatch:",
    "Parallel framework:",
    "NVIDIA CUDA:",
    "OpenCL:",
    "C++ Compiler:",
    "Optimization flags",
    "Build-only",
)

CAVEATS = [
    "A CPU-bound vision workload benefits less than a headline number suggests: "
    "the pipeline is dominated by HoughCircles and a numpy gather loop, and both "
    "are affected by memory access patterns as much as by arithmetic throughput.",
    "Preprocessing is not reworked to suit a benchmark. If an arm is faster on the "
    "current code, that is the finding.",
    "Single-frame latency and total throughput are different questions and can "
    "point in opposite directions once OpenCV's internal threading is involved, "
    "which is why both arms are reported.",
    "Container and cold-start overhead is excluded from the per-frame numbers.",
    "These numbers would not transfer to real photographs: the fixtures are "
    "synthetic, a real photo has more texture, and more of the time would land in "
    "segmentation and contour work.",
]


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = int(round(fraction * (len(ordered) - 1)))
    return ordered[min(len(ordered) - 1, max(0, position))]


def summarise(values: list[float]) -> dict:
    """Mean, median, p95, p99 and the spread — never a single number.

    A heavy-tailed latency distribution summarised by its mean alone is not
    usable for capacity planning, so the tail and the spread are always present.
    """
    if not values:
        return {
            "samples": 0,
            "mean": None,
            "median": None,
            "p95": None,
            "p99": None,
            "min": None,
            "max": None,
            "iqr": None,
            "stddev": None,
        }
    p25 = percentile(values, 0.25)
    p75 = percentile(values, 0.75)
    return {
        "samples": len(values),
        "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "p95": round(percentile(values, 0.95) or 0.0, 4),
        "p99": round(percentile(values, 0.99) or 0.0, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "iqr": round(p75 - p25, 4) if p25 is not None and p75 is not None else None,
        # stdev needs two samples; a single repetition is reported as null rather
        # than as zero, which would overstate the precision of the run.
        "stddev": round(statistics.stdev(values), 4) if len(values) > 1 else None,
    }


def reduce_build_information() -> dict:
    """``cv2.getBuildInformation()`` reduced to the lines that identify a build."""
    getter = getattr(cv2, "getBuildInformation", None)
    if getter is None:  # pragma: no cover - every wheel ships this
        return {"available": False, "reason": "cv2.getBuildInformation is absent"}
    try:
        text = getter()
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped and stripped.startswith(_WANTED_BUILD_PREFIXES):
            lines.append(" ".join(stripped.split()))
    return {"available": True, "lines": lines}


def blas_description() -> str | None:
    """Best-effort numpy build description, or ``None`` if it cannot be read.

    NumPy does not expose this consistently across builds, and guessing would be
    worse than reporting that it is unknown.
    """
    try:
        config = np.__config__.CONFIG  # type: ignore[attr-defined]
        entries = []
        for key, value in config.items():
            if isinstance(value, dict):
                entries.append(f"{key}: " + ", ".join(f"{k}={v}" for k, v in value.items()))
            else:
                entries.append(f"{key}: {value}")
        return "; ".join(entries) or None
    except Exception:
        return None


def fixture_set_digest() -> dict:
    """SHA-256 over the ordered fixture set, so a generator change is detectable."""
    digest = hashlib.sha256()
    per_fixture: dict[str, str] = {}
    for name, factory in FIXTURES:
        scene = factory()  # type: ignore[operator]
        payload = scene.image.tobytes()
        per_fixture[name] = hashlib.sha256(payload).hexdigest()
        digest.update(name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(payload)
    return {"sha256": digest.hexdigest(), "per_fixture": per_fixture}


def generator_source_digest() -> dict:
    """SHA-256 of the files that define the fixtures and the geometry they assume."""
    out: dict[str, str | None] = {}
    for relative in ("app/fixtures/generate_panels.py", "app/vision/profiles.py"):
        path = BACKEND_ROOT / relative
        out[relative] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        )
    return out


def git_revision() -> str | None:
    """The checked-out revision, if this is a git work tree at all."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(BACKEND_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def cpu_count_available() -> int | None:
    """Cores this process may actually use, not the host's core count."""
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:  # pragma: no cover - non-Linux
        return os.cpu_count()


def environment_report(arm: str) -> dict:
    return {
        "arm": arm,
        "machine": platform.machine(),
        "architecture": platform.architecture()[0],
        "processor": platform.processor() or None,
        "vcpu_available": cpu_count_available(),
        "python": platform.python_version(),
        "numpy_version": np.__version__,
        "numpy_build": blas_description(),
        "numpy_build_note": (
            "null means the build description could not be read from this NumPy; it "
            "was not inferred."
        ),
        "opencv_version": opencv_version(),
        "opencv_build": reduce_build_information(),
        "cv2_get_num_threads_default": DEFAULT_THREADS,
        "platform": platform.platform(),
        "kernel_release": platform.uname().release,
        "instance_type": None,
        "instance_type_note": (
            "No instance type is recorded: this run is on the local machine and no "
            "cloud instance was used or looked up."
        ),
        "region": None,
        "region_note": "No cloud region is recorded, for the same reason.",
        "git_revision": git_revision(),
    }


def _gauge_preprocess(crop: np.ndarray) -> np.ndarray:
    """``read_gauge``'s own first three lines, reproduced so the split is faithful.

    If this drifts from ``app.vision.gauges.read_gauge`` the operation split
    would attribute time to the wrong stage, so it is spelled out here rather
    than imported from a private helper.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    return cv2.bilateralFilter(gray, 7, 40, 40)


@dataclass
class Prepared:
    """One fixture with the inputs each operation needs, computed once."""

    name: str
    frame: np.ndarray
    frame_gray: np.ndarray
    gauge_crop: np.ndarray
    gauge_gray: np.ndarray
    dial: tuple
    lamp_crop: np.ndarray


def prepare(name: str, frame: np.ndarray) -> Prepared:
    working, _ = to_working_copy(frame)
    gauge_spec = INDUSTRIAL_PANEL.gauge
    if gauge_spec is None:  # pragma: no cover - the profile always has one
        raise SystemExit("industrial_panel_v1 has no gauge region to benchmark")
    gauge_crop = crop_region(working, gauge_spec)
    gauge_gray = _gauge_preprocess(gauge_crop)
    lamp_spec = INDUSTRIAL_PANEL.region("warning_led_01")
    lamp_crop = crop_region(working, lamp_spec) if lamp_spec is not None else np.zeros((1, 1, 3), np.uint8)
    return Prepared(
        name=name,
        frame=working,
        frame_gray=cv2.cvtColor(working, cv2.COLOR_BGR2GRAY),
        gauge_crop=gauge_crop,
        gauge_gray=gauge_gray,
        dial=gauges._dial(gauge_crop, gauge_gray),
        lamp_crop=lamp_crop,
    )


def _timed_operation(label: str, scope: str, call, *, repetitions: int, warmup: int) -> dict:
    """Time one operation, and fail that row rather than the whole benchmark.

    A single unavailable operation must not cost the report; the error is
    recorded against the row so the gap is visible instead of silent.
    """
    try:
        for _ in range(warmup):
            call()
        samples = []
        for _ in range(repetitions):
            started = time.perf_counter()
            call()
            samples.append((time.perf_counter() - started) * 1000.0)
    except Exception as exc:
        return {
            "operation": label,
            "scope": scope,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {"operation": label, "scope": scope, **summarise(samples)}


def measure_operations(
    prepared_all: list[Prepared], *, repetitions: int, warmup: int
) -> list[dict]:
    """Per-operation timings, rotating over the fixtures the operation applies to."""
    industrial = [p for p in prepared_all if p.name in INDUSTRIAL_OPERATION_FIXTURES]
    if not industrial:  # pragma: no cover - guarded by the fixture list above
        industrial = prepared_all

    def rotating(items: list[Prepared], fn):
        index = 0

        def call():
            nonlocal index
            fn(items[index % len(items)])
            index += 1

        return call

    gauge_spec = INDUSTRIAL_PANEL.gauge

    operations = [
        (
            "quality.blur_score (frame)",
            "all fixtures",
            rotating(prepared_all, lambda p: quality.blur_score(p.frame_gray)),
        ),
        (
            "regions.detect_panel (frame)",
            "all fixtures",
            rotating(prepared_all, lambda p: regions.detect_panel(p.frame)),
        ),
        (
            "gauge preprocess (cvtColor + CLAHE + bilateral)",
            "industrial fixtures",
            rotating(industrial, lambda p: _gauge_preprocess(p.gauge_crop)),
        ),
        (
            "gauge dial localisation (cv2.HoughCircles, gauges._dial)",
            "industrial fixtures",
            rotating(industrial, lambda p: gauges._dial(p.gauge_crop, p.gauge_gray)),
        ),
        (
            "gauge radial scan (gauges._radial_samples)",
            "industrial fixtures",
            rotating(
                industrial,
                lambda p: gauges._radial_samples(
                    p.gauge_gray, p.dial[0], p.dial[1], p.dial[2]
                ),
            ),
        ),
        (
            "indicator HSV segmentation (indicators._lamp_blob)",
            "industrial fixtures",
            rotating(industrial, lambda p: indicators._lamp_blob(p.lamp_crop)),
        ),
        (
            "gauge full stage (gauges.read_gauge)",
            "industrial fixtures",
            rotating(industrial, lambda p: gauges.read_gauge(p.gauge_crop, gauge_spec)),
        ),
    ]

    return [
        _timed_operation(label, scope, call, repetitions=repetitions, warmup=warmup)
        for label, scope, call in operations
    ]


def measure_latency_arm(
    engine: VisionEngine, prepared: list[Prepared], *, repetitions: int, warmup: int, threads: int
) -> dict:
    """Single-frame latency at a fixed thread count — what a person waiting sees."""
    cv2.setNumThreads(threads)
    threads_in_use = cv2.getNumThreads()

    per_fixture: dict[str, dict] = {}
    everything: list[float] = []

    # Warm-up is discarded, and it sits before the CPU counter is read: the first
    # HoughCircles call pays lazy initialisation, and charging that to the
    # measured CPU seconds would overstate the cost of a steady-state analysis.
    for _ in range(warmup):
        for item in prepared:
            engine.analyze(item.frame, image_id=f"warmup-{item.name}", profile=INDUSTRIAL_PANEL)

    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    for item in prepared:
        samples = []
        for index in range(repetitions):
            started = time.perf_counter()
            engine.analyze(item.frame, image_id=f"{item.name}-{index}", profile=INDUSTRIAL_PANEL)
            samples.append((time.perf_counter() - started) * 1000.0)
        per_fixture[item.name] = summarise(samples)
        everything.extend(samples)
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "threads_requested": threads,
        "threads_in_use": threads_in_use,
        "warmup_iterations_per_fixture": warmup,
        "measured_iterations_per_fixture": repetitions,
        "capability": "single-frame latency, milliseconds",
        "per_fixture_ms": per_fixture,
        "aggregate_ms": summarise(everything),
        "cpu_seconds_consumed": round(
            (usage_after.ru_utime - usage_before.ru_utime)
            + (usage_after.ru_stime - usage_before.ru_stime),
            4,
        ),
    }


def measure_throughput_arm(
    engine: VisionEngine, prepared: list[Prepared], *, repetitions: int, warmup: int, threads: int
) -> dict:
    """Analyses per second at the default thread count — what a deployment sees."""
    cv2.setNumThreads(threads)
    threads_in_use = cv2.getNumThreads()

    for _ in range(warmup):
        for item in prepared:
            engine.analyze(item.frame, image_id=f"warmup-{item.name}", profile=INDUSTRIAL_PANEL)

    runs = repetitions * len(prepared)
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.perf_counter()
    for index in range(repetitions):
        for item in prepared:
            engine.analyze(item.frame, image_id=f"{item.name}-t{index}", profile=INDUSTRIAL_PANEL)
    elapsed = time.perf_counter() - started
    usage_after = resource.getrusage(resource.RUSAGE_SELF)

    cpu_seconds = (usage_after.ru_utime - usage_before.ru_utime) + (
        usage_after.ru_stime - usage_before.ru_stime
    )
    return {
        "threads_requested": threads,
        "threads_in_use": threads_in_use,
        "analyses": runs,
        "wall_seconds": round(elapsed, 4),
        "analyses_per_second": round(runs / elapsed, 4) if elapsed > 0 else None,
        "seconds_per_analysis": round(elapsed / runs, 6) if runs else None,
        "cpu_seconds_consumed": round(cpu_seconds, 4),
        "cpu_utilisation_of_one_core_percent": (
            round(100.0 * cpu_seconds / elapsed, 2) if elapsed > 0 else None
        ),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 2),
        "peak_rss_note": "ru_maxrss is in KiB on Linux, which is where this is measured.",
        "note": (
            "Frame sizes are 1280x720 with four configured regions, analysed "
            "sequentially through VisionEngine.analyze."
        ),
    }


def render(report: dict) -> None:
    env = report["environment"]
    print()
    print("SightOps vision benchmark")
    print(f"  arm                {env['arm']}")
    print(f"  OpenCV             {env['opencv_version']}")
    print(f"  numpy              {env['numpy_version']}")
    print(f"  architecture       {env['machine']} ({env['architecture']})")
    print(f"  vCPUs available    {env['vcpu_available']}")
    print(f"  OpenCV default threads at startup  {env['cv2_get_num_threads_default']}")
    print(f"  git revision       {env['git_revision']}")
    print(f"  fixture set sha256 {report['fixture_set']['sha256']}")
    print()

    latency = report["latency_arm"]
    print(f"Latency arm — {latency['threads_in_use']} thread(s), {latency['measured_iterations_per_fixture']} measured per fixture")
    aggregate = latency["aggregate_ms"]
    print(
        f"  aggregate ms: mean {aggregate['mean']}  median {aggregate['median']}  "
        f"p95 {aggregate['p95']}  p99 {aggregate['p99']}  "
        f"min {aggregate['min']}  max {aggregate['max']}  iqr {aggregate['iqr']}  "
        f"stddev {aggregate['stddev']}"
    )
    width = max(len(name) for name in latency["per_fixture_ms"]) if latency["per_fixture_ms"] else 0
    for name, row in latency["per_fixture_ms"].items():
        print(
            f"    {name:<{width}}  mean {row['mean']:>8.3f}  median {row['median']:>8.3f}  "
            f"p95 {row['p95']:>8.3f}  max {row['max']:>8.3f}"
        )
    print()

    throughput = report["throughput_arm"]
    print(
        f"Throughput arm — {throughput['threads_in_use']} thread(s), "
        f"{throughput['analyses']} analyses"
    )
    print(
        f"  {throughput['analyses_per_second']} analyses/s  "
        f"({throughput['seconds_per_analysis']} s per analysis), "
        f"{throughput['cpu_seconds_consumed']} CPU s, "
        f"{throughput['cpu_utilisation_of_one_core_percent']}% of one core, "
        f"peak RSS {throughput['peak_rss_mb']} MB"
    )
    print()

    print("Per-operation split (milliseconds)")
    for row in report["operations"]:
        if "error" in row:
            print(f"  [ERROR] {row['operation']} ({row['scope']}): {row['error']}")
            continue
        print(
            f"  {row['operation']:<52}  mean {row['mean']:>8.4f}  median {row['median']:>8.4f}  "
            f"p95 {row['p95']:>8.4f}   [{row['scope']}]"
        )
    print()
    print("The split is reported so a total improvement can be attributed: if the total")
    print("falls but HoughCircles does not, the win came from elsewhere.")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--arm",
        required=True,
        help="the arm this run measures, recorded verbatim, e.g. azure-vm-x86_64-stock-wheel",
    )
    parser.add_argument("--repetitions", type=int, default=200, help="measured iterations per fixture")
    parser.add_argument("--warmup", type=int, default=20, help="iterations per fixture, run and discarded")
    parser.add_argument(
        "--threads",
        type=int,
        default=1,
        help="threads for the latency arm; 0 means OpenCV's default as reported at startup",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="path for the JSON report (required, so a result always lands somewhere explicit)",
    )
    args = parser.parse_args()

    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    if args.warmup < 0:
        parser.error("--warmup cannot be negative")
    if args.threads < 0:
        parser.error("--threads cannot be negative")

    out = Path(args.out).expanduser()
    latency_threads = DEFAULT_THREADS if args.threads == 0 else args.threads

    print("!" * 78)
    print("SightOps vision benchmark")
    print("!" * 78)
    for line in _wrap(AUTHORISATION_WARNING, 74):
        print(f"  {line}")
    print("!" * 78)
    print()

    try:
        return run(args, out, latency_threads)
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - a legible failure beats a traceback
        print(f"benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


def run(args: argparse.Namespace, out: Path, latency_threads: int) -> int:
    generated_at = datetime.now(UTC).isoformat()
    print("preparing fixtures ...")
    fixtures = fixture_set_digest()
    prepared = [prepare(name, factory().image) for name, factory in FIXTURES]  # type: ignore[operator]

    settings = Settings(data_dir=Path(tempfile.mkdtemp(prefix="sightops-bench-")), demo_mode=True)
    settings.ensure_dirs()
    engine = VisionEngine(settings)

    print(f"measuring latency arm ({latency_threads} thread(s)) ...")
    latency = measure_latency_arm(
        engine,
        prepared,
        repetitions=args.repetitions,
        warmup=args.warmup,
        threads=latency_threads,
    )

    print(f"measuring throughput arm ({DEFAULT_THREADS} thread(s), OpenCV's default) ...")
    throughput = measure_throughput_arm(
        engine,
        prepared,
        repetitions=args.repetitions,
        warmup=args.warmup,
        threads=DEFAULT_THREADS,
    )

    print("measuring the per-operation split ...")
    operations = measure_operations(
        prepared, repetitions=args.repetitions, warmup=args.warmup
    )

    report = {
        "arm": args.arm,
        "generated_at": generated_at,
        "method": "docs/benchmarks/cool-methodology.md",
        "authorisation_warning": AUTHORISATION_WARNING,
        "environment": environment_report(args.arm),
        "fixture_set": {
            "names": [name for name, _ in FIXTURES],
            "sha256": fixtures["sha256"],
            "per_fixture": fixtures["per_fixture"],
            "generator_sources": generator_source_digest(),
        },
        "configuration": {
            "repetitions_per_fixture": args.repetitions,
            "warmup_per_fixture": args.warmup,
            "latency_threads_requested": latency_threads,
            "throughput_threads": DEFAULT_THREADS,
            "profile_id": INDUSTRIAL_PANEL.profile_id,
            "entry_point": "app.vision.engine.VisionEngine.analyze",
            "frame_size": "1280x720",
        },
        "latency_arm": latency,
        "throughput_arm": throughput,
        "operations": operations,
        "cost_assumption": {
            "cost_per_hour_usd": None,
            "source": None,
            "recorded_at": generated_at,
            "reason": (
                "No instance type has been chosen and no price has been looked up. Any "
                "figure here would be invented, so none is recorded."
            ),
        },
        "caveats": CAVEATS,
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    render(report)
    print(f"wrote {out}")
    if BACKEND_ROOT.parent in out.resolve().parents:
        print()
        print(
            "note: that path is inside the repository. A result may only be published "
            "alongside the arm name it was produced on; do not commit a baseline run as "
            "a COOL result."
        )
    return 0


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
