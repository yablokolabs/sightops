#!/usr/bin/env python3
"""Re-derive and check the blur calibration from the repository's own fixtures.

    python3 scripts/calibrate_quality.py
    python3 scripts/calibrate_quality.py --json

:mod:`app.vision.quality` scores sharpness as

    var(Laplacian(gray)) / std(gray)**2 / BLUR_REFERENCE

clipped to 0..1, and the frame gate rejects anything below ``blur_threshold``.
Those two constants are only defensible if the frames the product actually
measures are separated by them: a fixture that is sharp on purpose has to clear
the threshold, and a frame whose detail has genuinely gone has to fall under it.

This script draws the fixtures from :mod:`app.fixtures.generate_panels` — the
same generator the evaluation and the demonstrations use, so the ground truth is
exact rather than hand-labelled — measures the blur score on each, and reports
the separation. It also walks a Gaussian-blur ladder over the synthetic panel so
the trend between the two extremes is visible rather than asserted.

**It changes nothing.** Every constant is read, none is written. If the
separation is not there, the numbers are printed and the script exits 1: the
honest response to a broken calibration is to see it, not to move the threshold
until the check passes.

The top of the blur ladder is :data:`UNREADABLE_BLUR_SIGMA`, the point
``scripts/evaluate.py`` already documents as "removes the needle's edge" in its
readability criterion. That link is deliberate: the blur gate should fire where
the frame's information has actually gone.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.config import Settings  # noqa: E402
from app.fixtures import generate_panels as gp  # noqa: E402
from app.vision.quality import (  # noqa: E402
    BLUR_REFERENCE,
    DEFAULT_BLUR_THRESHOLD,
    assess,
    blur_score,
)

#: The threshold the engine actually applies, read from configuration rather
#: than from the module default, so this check tracks the deployed behaviour.
THRESHOLD = float(Settings().blur_threshold)

#: Fixtures with no blur degradation. Every one of these has to score at or
#: above the threshold, or the gate would refuse a frame that is in focus.
SHARP_FIXTURES: list[tuple[str, object]] = [
    ("industrial_normal", gp.scenario_normal),
    ("industrial_fault_distant", gp.scenario_fault_distant),
    ("industrial_fault_closeup", gp.scenario_fault_closeup),
    ("dishwasher_closeup", gp.scenario_dishwasher_closeup),
    ("dishwasher_unpowered", gp.scenario_dishwasher_unpowered),
]

#: Fixtures that are soft on purpose (a Gaussian blur plus a coarse sensor in
#: ``scenario_dishwasher_wide``). Reported for context, not asserted: that
#: fixture is a *region-quality* case in the household demo, and the frame gate
#: is only one of the paths that can ask for a better view.
SOFT_FIXTURES: list[tuple[str, object]] = [
    ("dishwasher_wide", gp.scenario_dishwasher_wide),
]

#: Gaussian sigma applied to the synthetic industrial panel, in order. 0.0 is
#: the undegraded render.
BLUR_LADDER: list[float] = [0.0, 0.8, 1.6, 2.4, 3.2, 4.0, 4.5]

#: The top of the ladder, and the sigma ``scripts/evaluate.py`` treats as
#: removing the needle's edge entirely. The blur score here must fall below the
#: threshold.
UNREADABLE_BLUR_SIGMA = 4.5

#: A step in the ladder is only called a break in the trend when the score rises
#: by more than this. A rising score would mean the metric is not measuring
#: blur; a rise smaller than this is the resolution of a clipped score and is not
#: worth failing over.
MONOTONIC_TOLERANCE = 0.01


def measure(frame: np.ndarray) -> dict:
    """Blur score plus the gate's own verdict for one frame."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    score, variance = blur_score(gray)
    verdict = assess(frame, blur_threshold=THRESHOLD)
    return {
        "blur_score": round(score, 6),
        "laplacian_variance": round(variance, 4),
        "multiple_of_threshold": round(score / THRESHOLD, 4),
        "gate_asks_for_new_view": bool(verdict.requires_new_view),
        "gate_reason": verdict.reason,
    }


def rows_for(fixtures: list[tuple[str, object]]) -> list[dict]:
    out: list[dict] = []
    for name, factory in fixtures:
        scene = factory()  # type: ignore[operator]
        out.append({"name": name, **measure(scene.image)})
    return out


def ladder_rows() -> list[dict]:
    out: list[dict] = []
    for sigma in BLUR_LADDER:
        scene = gp.render_industrial_panel(
            pressure_psi=42.0, degrade=gp.Degradation(blur_sigma=sigma)
        )
        out.append({"blur_sigma": sigma, **measure(scene.image)})
    return out


def trend_breaks(ladder: list[dict]) -> list[dict]:
    """Steps where a heavier blur scored *higher*, beyond the tolerance."""
    breaks: list[dict] = []
    for previous, current in zip(ladder, ladder[1:]):
        rise = current["blur_score"] - previous["blur_score"]
        if rise > MONOTONIC_TOLERANCE:
            breaks.append(
                {
                    "from_sigma": previous["blur_sigma"],
                    "to_sigma": current["blur_sigma"],
                    "rise": round(rise, 6),
                }
            )
    return breaks


def build_report() -> dict:
    sharp = rows_for(SHARP_FIXTURES)
    soft = rows_for(SOFT_FIXTURES)
    ladder = ladder_rows()

    weak = [row for row in sharp if row["blur_score"] < THRESHOLD]
    top = ladder[-1]
    if top["blur_sigma"] != UNREADABLE_BLUR_SIGMA:  # pragma: no cover - guarded constant
        raise SystemExit("the blur ladder must end at UNREADABLE_BLUR_SIGMA")

    checks = [
        {
            "name": "every in-focus fixture clears the threshold",
            "passed": not weak,
            "detail": (
                "; ".join(
                    f"{row['name']} scored {row['blur_score']:.4f} < {THRESHOLD:.2f}"
                    for row in weak
                )
                or f"all {len(sharp)} fixtures scored at or above {THRESHOLD:.2f}"
            ),
        },
        {
            "name": (
                "detail that is gone falls below the threshold "
                f"(blur_sigma {UNREADABLE_BLUR_SIGMA})"
            ),
            "passed": top["blur_score"] < THRESHOLD,
            "detail": (
                f"scored {top['blur_score']:.4f} against a threshold of {THRESHOLD:.2f} "
                f"({top['multiple_of_threshold']:.4f}x)"
            ),
        },
    ]

    return {
        "opencv_version": cv2.__version__,
        "blur_reference": BLUR_REFERENCE,
        "blur_threshold": THRESHOLD,
        "default_blur_threshold": DEFAULT_BLUR_THRESHOLD,
        "monotonic_tolerance": MONOTONIC_TOLERANCE,
        "unreadable_blur_sigma": UNREADABLE_BLUR_SIGMA,
        "sharp_fixtures": sharp,
        "soft_fixtures": soft,
        "blur_ladder": ladder,
        "checks": checks,
        "trend_breaks": trend_breaks(ladder),
    }


def render(report: dict) -> None:
    sharp = report["sharp_fixtures"]
    soft = report["soft_fixtures"]
    ladder = report["blur_ladder"]
    threshold = report["blur_threshold"]
    width = max(len(row["name"]) for row in sharp) if sharp else 0

    print("SightOps blur calibration")
    print(f"  OpenCV                   {report['opencv_version']}")
    print(f"  BLUR_REFERENCE           {report['blur_reference']}")
    print(f"  blur_threshold           {threshold}")
    print(f"  DEFAULT_BLUR_THRESHOLD   {report['default_blur_threshold']}")
    if report["default_blur_threshold"] != threshold:
        print(
            f"  note: the configured threshold ({threshold}) differs from the module "
            f"default ({report['default_blur_threshold']}); the configured one is used "
            "here, because it is the one the engine applies."
        )
    print()

    print("In-focus fixtures (no blur degradation) — these must clear the threshold")
    for row in sharp:
        status = "PASS" if row["blur_score"] >= threshold else "FAIL"
        print(
            f"  [{status}] {row['name']:<{width}}  score {row['blur_score']:.4f}  "
            f"{row['multiple_of_threshold']:.2f}x threshold  "
            f"var(Laplacian) {row['laplacian_variance']:.2f}  "
            f"gate asks for a new view: {'yes' if row['gate_asks_for_new_view'] else 'no'}"
        )
        if row["gate_asks_for_new_view"] and row["blur_score"] >= threshold:
            print(f"           (and asked for another reason: {row['gate_reason']})")
    print()

    print("Soft fixtures (soft on purpose) — reported for context, not asserted")
    for row in soft:
        print(
            f"  [INFO] {row['name']:<{width}}  score {row['blur_score']:.4f}  "
            f"{row['multiple_of_threshold']:.2f}x threshold  "
            f"gate asks for a new view: {'yes' if row['gate_asks_for_new_view'] else 'no'}"
        )
    print()

    print("Blur ladder — the synthetic industrial panel resampled with a wider Gaussian")
    for row in ladder:
        marker = (
            "  <- documented as removing the needle's edge"
            if row["blur_sigma"] == report["unreadable_blur_sigma"]
            else ""
        )
        print(
            f"  sigma {row['blur_sigma']:>4.1f}   score {row['blur_score']:.4f}  "
            f"{row['multiple_of_threshold']:>9.4f}x threshold  "
            f"var(Laplacian) {row['laplacian_variance']:>8.3f}{marker}"
        )
    if report["trend_breaks"]:
        print()
        for entry in report["trend_breaks"]:
            print(
                f"  [WARN] the score rose from sigma {entry['from_sigma']} to "
                f"{entry['to_sigma']} by {entry['rise']} — a break in the trend, not a "
                "failure, but the metric is not purely a function of blur at that step."
            )
    print()

    print("Checks")
    for check in report["checks"]:
        print(f"  [{'PASS' if check['passed'] else 'FAIL'}] {check['name']}")
        print(f"          {check['detail']}")
    failed = sum(1 for check in report["checks"] if not check["passed"])
    print()
    print(f"{len(report['checks']) - failed}/{len(report['checks'])} checks passed")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        render(report)
    return 1 if any(not check["passed"] for check in report["checks"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
