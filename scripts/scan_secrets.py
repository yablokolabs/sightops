#!/usr/bin/env python3
"""Scans every tracked file for material that looks like a credential.

This is the check `AGENTS.md` asks for, and it runs in CI on every push and pull
request. It scans **tracked files**, because those are what a commit publishes: a
secret that lives only in an ignored local file is not a leak, and a secret that has
been committed stays in the history after the file is deleted.

    python3 scripts/scan_secrets.py [--verbose]

Exits 1 and prints the file, line and a masked excerpt for anything it finds. It never
prints a matched value in full.

Two kinds of finding:

* **shape** — a string with the shape of a known provider credential (an AWS access
  key id, a GitHub token, a private key header, an ElevenLabs key, ...);
* **policy** — a file that must not be committed at all, currently any tracked
  ``.env`` other than ``.env.example``.

Deliberately not included: entropy heuristics. They fire on the base64 in the demo's
own MP3 and PNG assets and on the fixture seeds, which trains people to ignore the
check. Every rule here is a shape somebody can explain.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

#: Files that are never a credential leak even if they look like one.
SKIP_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".mp3",
    ".mp4",
    ".wav",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".ico",
    ".zip",
    ".gz",
)

#: (name, compiled regex). The name appears in the report, so it has to be readable.
SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("ElevenLabs key", re.compile(r"\bsk_[a-f0-9]{32,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("Tavily key", re.compile(r"\btvly-[A-Za-z0-9-]{16,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{20,}\.")),
    (
        "assigned credential value",
        re.compile(
            r"""(?ix)                     # case-insensitive, verbose
            # No leading \b: the interesting names are compound
            # (`nebius_api_key`, `AWS_SECRET_ACCESS_KEY`), and a boundary before
            # the `api_key` part would skip them.
            (?:api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token
                 |secret[_-]?key|client[_-]?secret|password|passwd|private[_-]?key)\b
            \s*[:=]\s*
            ["']?                          # an optional opening quote
            # `.` is in the set because served keys are often version-prefixed
            # (`v1.`) or dotted; the keyword and the 24-character floor are what
            # keep this from firing on ordinary prose.
            (?P<value>[A-Za-z0-9_.\-/+]{24,})   # a value long enough to be real
            """,
        ),
    ),
)

#: An assigned value matching any of these is a placeholder, not a credential.
PLACEHOLDER = re.compile(
    r"""(?ix)
    ^(?: ... | placeholder | redacted | changeme | none | null | test | dummy |
         example | your[_-]?key | replace[_-]?me | x{4,} | \.{3,} )$
    | \$\{? [A-Z_]+ \}?            # a shell or template expansion
    | ^< .* >$                     # an angle-bracket placeholder
    """,
)

#: A tracked file that must never be committed, whatever it contains, and the one
#: exception: the template that documents the variable names without values.
FORBIDDEN_PATHS = re.compile(r"(?:^|/)\.env(?:\.[^/]*)?$")
ALLOWED_PATHS = re.compile(r"(?:^|/)\.env\.example$")


def tracked_files() -> list[str]:
    """Every file git would publish, as paths relative to the repository root."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        check=True,
        text=True,
    )
    return [name for name in result.stdout.split("\0") if name]


def is_binary(path: str) -> bool:
    """True for a file that is either a known binary type or contains a NUL byte."""
    if path.lower().endswith(SKIP_SUFFIXES):
        return True
    try:
        with open(path, "rb") as handle:
            return b"\0" in handle.read(8192)
    except OSError:
        return True


def mask(value: str) -> str:
    """Show enough of a match to locate it, never enough to use it."""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:4]}{'*' * 8}{value[-2:]} ({len(value)} chars)"


def scan_text(path: str, text: str, describe, findings: list[str]) -> None:
    for number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in SHAPES:
            for match in pattern.finditer(line):
                value = match.group("value") if "value" in pattern.groupindex else match.group(0)
                if PLACEHOLDER.match(value):
                    continue
                findings.append(f"{path}:{number}: {name} — {mask(value)}")
                describe(f"{path}:{number}: {name} — {mask(value)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verbose", action="store_true", help="list every tracked file scanned")
    args = parser.parse_args()

    findings: list[str] = []
    scanned = 0

    def describe(message: str) -> None:
        print(f"  {message}")

    for path in tracked_files():
        if FORBIDDEN_PATHS.search(path) and not ALLOWED_PATHS.search(path):
            findings.append(
                f"{path}: a tracked .env file — credentials must be passed in the "
                "environment, never committed (see .env.example and README.md)"
            )
            describe(findings[-1])
            continue
        if is_binary(path):
            continue
        scanned += 1
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError as exc:
            findings.append(f"{path}: could not be read ({exc})")
            continue
        if args.verbose:
            print(f"  scanned {path}")
        scan_text(path, text, describe, findings)

    print(f"\nscanned {scanned} tracked text files")

    if findings:
        print(f"\nFAIL: {len(findings)} finding(s)")
        for finding in findings:
            print(f"  {finding}")
        return 1

    print("PASS: no credential-shaped material in any tracked file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
