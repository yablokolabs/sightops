#!/usr/bin/env python3
"""Fails when a fresh evaluation run regresses past the published numbers.

`backend/scripts/evaluate.py` writes `results.json` next to the report it generates.
This reads that file and checks the metrics a regression would show up in first, so CI
cannot go green on a vision change that halves the accuracy.

    python3 scripts/check_evaluation_metrics.py docs/evaluation/results.json

The thresholds are deliberately looser than the measured values they guard: they are
there to catch a regression, not to demand that a small, honest change to the fixtures
reproduces a number to the digit. The values they were set from are in
`docs/evaluation/results.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

#: (description, dotted path, predicate) — every one of these must hold.
GATES: tuple[tuple[str, str, Any], ...] = (
    ("the run really used OpenCV 5", "environment.opencv_version", lambda v: str(v).startswith("5.")),
    ("every fixture in the set was attempted", "gauge.attempts", lambda v: v >= 100),
    ("gauge mean absolute error stays under 1 PSI", "gauge.mean_absolute_error_psi", lambda v: v < 1.0),
    (
        "no more than the one known wrong reading escaped",
        "quality_gate.wrong_value_escape_count",
        lambda v: v <= 1,
    ),
    ("regions still localise", "roi.success_rate", lambda v: v >= 0.99),
    ("indicator precision holds", "indicators.macro_precision", lambda v: v >= 0.95),
    ("indicator recall holds", "indicators.macro_recall", lambda v: v >= 0.95),
    ("the agent still completes every scripted task", "agent.task_success_rate", lambda v: v >= 0.99),
    (
        "active perception never missed a needed request",
        "agent.active_perception.missed_requests",
        lambda v: v == 0,
    ),
    (
        "active perception never asked for an unneeded view",
        "agent.active_perception.unnecessary_requests",
        lambda v: v == 0,
    ),
    ("an inspection stays inside its step bound", "agent.all_runs_bounded", lambda v: v is True),
    ("AWS is still reported as absent", "environment.aws", lambda v: "NOT IMPLEMENTED" in str(v)),
)


def dig(document: dict[str, Any], path: str) -> Any:
    value: Any = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", help="path to the results.json written by evaluate.py")
    args = parser.parse_args()

    with open(args.results, encoding="utf-8") as handle:
        document = json.load(handle)

    failures = 0
    for description, path, predicate in GATES:
        value = dig(document, path)
        try:
            ok = value is not None and bool(predicate(value))
        except TypeError:
            ok = False
        print(f"  [{'PASS' if ok else 'FAIL'}] {description}  ({path} = {value!r})")
        failures += 0 if ok else 1

    print()
    if failures:
        print(f"FAIL: {failures} metric(s) regressed")
        return 1
    print(f"PASS: all {len(GATES)} metric gates hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
