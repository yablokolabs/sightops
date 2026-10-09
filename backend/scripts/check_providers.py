#!/usr/bin/env python3
"""Verify the live providers and the OpenCV version SightOps depends on.

Checks, in order:

1. **Local OpenCV.** Prints ``cv2.__version__`` and asserts the major version is
   5. The README's OpenCV 5 claim depends on this, so it is checked rather than
   assumed.
2. **Nebius model list.** ``GET https://api.studio.nebius.com/v1/models`` with
   the configured key, confirming that both the configured reasoning model and
   the configured vision model are present in what the endpoint actually serves.
3. **Nebius tool calling.** One minimal ``POST /v1/chat/completions`` offering a
   single function schema, confirming a well-formed ``tool_calls`` array comes
   back. This is the capability the agent loop cannot work without.
4. **ElevenLabs voices.** ``GET https://api.elevenlabs.io/v1/voices``,
   confirming the configured voice id exists and reporting its name and labels.

Identifiers are read from the local configuration rather than hard-coded, so the
check follows ``SIGHTOPS_NEBIUS_MODEL`` and friends.

**No key material is ever printed.** The scripts reports whether each credential
is present, never any part of its value. A missing key is a reported FAIL rather
than a crash, so a partially configured machine still produces a useful report.

Exits non-zero if any check fails.

    python3 scripts/check_providers.py
    python3 scripts/check_providers.py --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings, load_secrets  # noqa: E402
from app.providers.base import ProviderError, ProviderUnavailable  # noqa: E402
from app.providers.elevenlabs import list_voices  # noqa: E402
from app.providers.nebius import NebiusProvider, list_models  # noqa: E402
from app.vision.engine import opencv_version  # noqa: E402

#: One function schema, enough to prove the endpoint honours the tool protocol.
_TOOL_PROBE = [
    {
        "type": "function",
        "function": {
            "name": "read_gauge",
            "description": "Read an analog gauge in a named region.",
            "parameters": {
                "type": "object",
                "properties": {"region_id": {"type": "string"}},
                "required": ["region_id"],
            },
        },
    }
]


class Report:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def add(self, check: str, passed: bool, detail: str) -> None:
        self.rows.append({"check": check, "passed": passed, "detail": detail})

    @property
    def failed(self) -> int:
        return sum(1 for row in self.rows if not row["passed"])

    def render(self) -> None:
        width = max(len(str(row["check"])) for row in self.rows) if self.rows else 0
        for row in self.rows:
            status = "PASS" if row["passed"] else "FAIL"
            print(f"  [{status}] {str(row['check']):<{width}}  {row['detail']}")
        print()
        total = len(self.rows)
        print(f"{total - self.failed}/{total} checks passed")
        if self.failed:
            print("Some checks failed. This does not stop SightOps: a missing provider "
                  "degrades the affected feature and the rest keeps working.")


def check_opencv(report: Report) -> None:
    version = opencv_version()
    major = version.split(".")[0]
    report.add(
        "OpenCV major version is 5",
        major == "5",
        f"cv2.__version__ = {version}",
    )


async def check_nebius_models(report: Report, settings: Settings) -> None:
    if not load_secrets().get("NEBIUS_API_KEY"):
        report.add(
            "Nebius credentials present",
            False,
            "NEBIUS_API_KEY not found in the environment or ~/.hermes/.env",
        )
        return
    report.add("Nebius credentials present", True, "key present (value not read out)")

    try:
        models = await list_models(settings)
    except (ProviderError, ProviderUnavailable) as exc:
        report.add("Nebius /models reachable", False, str(exc)[:160])
        return

    report.add("Nebius /models reachable", True, f"{len(models)} models served")

    for label, model in (
        ("reasoning model", settings.nebius_model),
        ("vision model", settings.nebius_vision_model),
    ):
        present = model in models
        detail = f"{model} {'is' if present else 'is NOT'} in the served list"
        if not present:
            near = [m for m in models if m.split("/")[-1].lower()[:6] in model.lower()]
            if near:
                detail += f"; similar served ids: {', '.join(near[:3])}"
        report.add(f"Configured {label} is served", present, detail)


async def check_nebius_tool_calling(report: Report, settings: Settings) -> None:
    provider = NebiusProvider(settings)
    if not await provider.is_available():
        report.add("Nebius tool calling", False, "no key, check skipped")
        return

    try:
        response = await provider.generate(
            [
                {
                    "role": "system",
                    "content": "Choose the tool that reads the pressure gauge. Call it.",
                },
                {"role": "user", "content": "Read the gauge in region pressure_gauge_01."},
            ],
            tools=_TOOL_PROBE,
            max_tokens=200,
            temperature=0.0,
        )
    except (ProviderError, ProviderUnavailable) as exc:
        report.add("Nebius tool calling", False, str(exc)[:160])
        return

    if not response.tool_calls:
        report.add(
            "Nebius tool calling",
            False,
            f"no tool_calls returned (finish_reason={response.finish_reason!r}); "
            "the agent loop cannot run live without this",
        )
        return

    call = response.tool_calls[0]
    well_formed = bool(call.name) and isinstance(call.arguments, dict)
    report.add(
        "Nebius tool calling",
        well_formed,
        (
            f"{response.model} returned {call.name}({json.dumps(call.arguments)}) "
            f"finish_reason={response.finish_reason!r} tokens={response.usage.total_tokens}"
        ),
    )


async def check_elevenlabs(report: Report, settings: Settings) -> None:
    if not load_secrets().get("ELEVENLABS_API_KEY"):
        report.add(
            "ElevenLabs credentials present",
            False,
            "ELEVENLABS_API_KEY not found; voice guidance will report 503 and written "
            "guidance is unaffected",
        )
        return
    report.add("ElevenLabs credentials present", True, "key present (value not read out)")

    try:
        voices = await list_voices(settings)
    except (ProviderError, ProviderUnavailable) as exc:
        report.add("ElevenLabs /voices reachable", False, str(exc)[:160])
        return

    report.add("ElevenLabs /voices reachable", True, f"{len(voices)} voices available")

    wanted = settings.elevenlabs_voice_id
    match = next((v for v in voices if v.get("voice_id") == wanted), None)
    if match is None:
        report.add(
            "Configured voice id exists",
            False,
            f"{wanted} is not in this account's voice list",
        )
        return

    labels = " / ".join(
        str(match.get(key)) for key in ("accent", "gender", "age") if match.get(key)
    )
    report.add(
        "Configured voice id exists",
        True,
        f"{wanted} is {match.get('name')!r} ({labels})",
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args()

    settings = Settings()
    report = Report()

    print("SightOps provider check")
    print(f"  api base      {settings.nebius_base_url}")
    print(f"  reasoning     {settings.nebius_model}")
    print(f"  vision        {settings.nebius_vision_model}")
    print(f"  voice         {settings.elevenlabs_voice_id} ({settings.elevenlabs_model_id})")
    print()

    check_opencv(report)
    await check_nebius_models(report, settings)
    await check_nebius_tool_calling(report, settings)
    await check_elevenlabs(report, settings)

    if args.json:
        print(json.dumps({"checks": report.rows, "failed": report.failed}, indent=2))
    else:
        report.render()

    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
