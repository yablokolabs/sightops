#!/usr/bin/env python3
"""Rebuild `audio.mp3` and `timing.json` when only some narration blocks changed.

Why this exists. The ElevenLabs account behind this demo is on a plan with a fixed
monthly character allowance. `generate.sh` speaks the whole script again, so fixing
one paragraph costs as much as recording the video the first time, and an edit made
after the allowance is spent cannot be recorded at all. This script speaks **only the
blocks that changed** and splices the result into the existing recording at the
natural silence between blocks, so the spend is proportional to the edit.

It is a repair tool, not the normal path: for a fresh recording run `generate.sh`.
After either one, run `scripts/sync_audio.py` to rebuild the track and the segment
timing.

    python3 scripts/resplice_voiceover.py --replace 4,5,6 --budget 950
    python3 scripts/resplice_voiceover.py --drop-words 398:400

Blocks are numbered from 1 in timeline order, which is the same order as `CUES` in
`sync_audio.py`. Needs ELEVENLABS_API_KEY in the environment, plus curl, ffmpeg and
ffprobe. It refuses to run when the replacement text would exceed `--budget`
characters, so it cannot quietly overrun the allowance.

`--drop-words START:END` (0-based, inclusive) excises a word range from the existing
recording and from `timing.json` without spending anything. It exists because a
splice that lands on the wrong word leaves a fragment of a sentence in the voice
that no edit can reword around; cutting to the next clean sentence boundary is the
only repair that needs no new audio. The written script must be changed to match.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
VIDEO = PROJECT / "videos" / "sightops-demo"
VOICEOVER = VIDEO / "audio" / "originals" / "voiceovers" / "v1"

VOICE_ID = os.environ.get("VOICE_ID", "Xb7hH8MSUJpSbSDYk0k2")  # Alice
MODEL_ID = os.environ.get("MODEL_ID", "eleven_multilingual_v2")
BREAK = '<break time="0.6s" />'

# Silence kept on each side of a splice, taken out of the intentional pause between
# blocks so the join lands in silence rather than inside a word.
PAD_S = 0.30


def read_blocks() -> list[str]:
    script = (VOICEOVER / "provider_script.md").read_text().split("\n---\n", 1)[1]
    blocks = re.split(r"<break[^>]*/>", script)
    return [block.strip() for block in blocks]


def group_words(alignment: dict) -> list[dict]:
    """Group per-character alignment into words, dropping `<break ... />` tags.

    Mirrors the jq filter in `generate.sh`, so both paths produce identical word lists.
    """
    words: list[dict] = []
    current: dict | None = None
    in_tag = False
    for char, start, end in zip(
        alignment["characters"],
        alignment["character_start_times_seconds"],
        alignment["character_end_times_seconds"],
        strict=True,
    ):
        if in_tag:
            if char == ">":
                in_tag = False
            continue
        if char == "<":
            if current:
                words.append(current)
                current = None
            in_tag = True
        elif char.isspace():
            if current:
                words.append(current)
                current = None
        elif current:
            current["word"] += char
            current["end"] = end
        else:
            current = {"word": char, "start": start, "end": end}
    if current:
        words.append(current)
    return words


def speak(text: str) -> tuple[bytes, list[dict]]:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise SystemExit("set ELEVENLABS_API_KEY in the environment")
    payload = json.dumps(
        {
            "text": text,
            "model_id": MODEL_ID,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        response = Path(tmp) / "response.json"
        status = subprocess.run(
            [
                "curl", "-sS", "--max-time", "300", "-o", str(response), "-w", "%{http_code}",
                "-X", "POST",
                f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/with-timestamps",
                "-H", f"xi-api-key: {key}",
                "-H", "Content-Type: application/json",
                "-d", payload,
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        body = json.loads(response.read_text())
        if status != "200":
            raise SystemExit(f"ElevenLabs returned HTTP {status}: {json.dumps(body)[:400]}")
        audio = base64.b64decode(body["audio_base64"])
        return audio, group_words(body["alignment"])


def duration_of(path: Path) -> float:
    return float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            check=True, capture_output=True, text=True,
        ).stdout
    )


def retime(words: list[dict], cut_start: float, cut_end: float) -> list[dict]:
    """Shift every word that starts at or after `cut_end` back by the removed span."""
    shift = cut_end - cut_start
    return [
        word if word["start"] < cut_end else {**word, "start": word["start"] - shift, "end": word["end"] - shift}
        for word in words
    ]


def drop_words(spec: str) -> None:
    """Excise words START..END (0-based, inclusive) from the recording and the timing."""
    start_text, _, end_text = spec.partition(":")
    if not start_text.isdigit() or not end_text.isdigit():
        raise SystemExit(f"--drop-words wants START:END, got {spec!r}")
    start, end = int(start_text), int(end_text)

    audio_path = VOICEOVER / "audio.mp3"
    timing_path = VOICEOVER / "timing.json"
    words = json.loads(timing_path.read_text())["words"]
    if not 0 <= start <= end < len(words):
        raise SystemExit(f"word range {start}..{end} is outside 0..{len(words) - 1}")

    # Trim into the silence on both sides, so the join never lands inside a phoneme.
    cut_start = max(0.0, words[start]["start"] - PAD_S)
    cut_end = words[end + 1]["start"] - PAD_S if end + 1 < len(words) else duration_of(audio_path)
    if cut_end <= cut_start:
        raise SystemExit("the word range has no room between its neighbours")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "dropped.mp3"
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-i", str(audio_path),
                "-filter_complex",
                f"[0:a]atrim=start=0:end={cut_start},asetpts=N/SR[a];"
                f"[0:a]atrim=start={cut_end},asetpts=N/SR[b];"
                "[a][b]concat=n=2:v=0:a=1[out]",
                "-map", "[out]", "-ar", "44100", "-c:a", "libmp3lame", "-q:a", "2", str(out),
            ],
            check=True,
        )
        audio_path.write_bytes(out.read_bytes())

    removed = [word["word"] for word in words[start : end + 1]]
    timing_path.write_text(
        json.dumps({"words": retime(words[:start] + words[end + 1:], cut_start, cut_end)}, indent=2)
        + "\n"
    )
    print(f"dropped {end - start + 1} word(s) {removed} and {cut_end - cut_start:.3f}s of audio")
    print("now update provider_script.md to match, then run scripts/sync_audio.py")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", help="1-based block numbers, e.g. 4,5,6")
    parser.add_argument("--drop-words", help="0-based inclusive word range, e.g. 398:400")
    parser.add_argument("--budget", type=int, default=950, help="max characters to spend")
    args = parser.parse_args()

    if bool(args.replace) == bool(args.drop_words):
        raise SystemExit("pass exactly one of --replace or --drop-words")
    if args.drop_words:
        return drop_words(args.drop_words)

    replace = sorted({int(part) for part in args.replace.split(",")})
    blocks = read_blocks()
    for number in replace:
        if not 1 <= number <= len(blocks):
            raise SystemExit(f"block {number} is outside 1..{len(blocks)}")

    text = f"\n\n{BREAK}\n\n".join(blocks[number - 1] for number in replace)
    if len(text) > args.budget:
        raise SystemExit(f"{len(text)} characters needed, budget is {args.budget}")

    audio_path = VOICEOVER / "audio.mp3"
    timing_path = VOICEOVER / "timing.json"
    if not audio_path.exists() or not timing_path.exists():
        raise SystemExit("no existing recording to splice into; run generate.sh")

    old_words = json.loads(timing_path.read_text())["words"]
    # The word index at which each block starts, which is how sync_audio.py maps
    # blocks to timings too.
    firsts = [0]
    for block in blocks:
        firsts.append(firsts[-1] + len(block.split()))

    print(f"replacing {len(replace)} block(s): {len(text)} characters requested")
    new_audio, new_words = speak(text)
    print(f"received {len(new_words)} words of new audio")

    first_replaced, last_replaced = replace[0] - 1, replace[-1]
    if first_replaced == 0 or last_replaced + 1 >= len(blocks):
        raise SystemExit("do not splice the first or last block; re-record instead")

    cut_start = old_words[firsts[first_replaced] - 1]["end"] + PAD_S
    cut_end = old_words[firsts[last_replaced + 1]]["start"] - PAD_S
    if cut_end <= cut_start:
        raise SystemExit("the replaced blocks have no room between their neighbours")

    new_start = max(0.0, new_words[0]["start"] - PAD_S)
    new_end = new_words[-1]["end"] + PAD_S

    with tempfile.TemporaryDirectory() as tmp:
        piece = Path(tmp) / "piece.mp3"
        piece.write_bytes(new_audio)
        piece_end = min(new_end, duration_of(piece))
        out = Path(tmp) / "spliced.mp3"
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-i", str(audio_path), "-i", str(piece),
                "-filter_complex",
                "[0:a]atrim=start=0:end={a},asetpts=N/SR[a];".format(a=cut_start)
                + "[1:a]atrim=start={s}:end={e},asetpts=N/SR[b];".format(s=new_start, e=piece_end)
                + "[0:a]atrim=start={c},asetpts=N/SR[c];".format(c=cut_end)
                + "[a][b][c]concat=n=3:v=0:a=1[out]",
                "-map", "[out]", "-ar", "44100", "-c:a", "libmp3lame", "-q:a", "2", str(out),
            ],
            check=True,
        )
        audio_path.write_bytes(out.read_bytes())

    inserted = (piece_end - new_start)
    shift = cut_start + inserted - cut_end
    print(f"inserted {inserted:.3f}s, later blocks shift by {shift:+.3f}s")

    spliced = [dict(word) for word in old_words[: firsts[first_replaced]]]
    spliced += [
        {**word, "start": cut_start + word["start"] - new_start,
         "end": cut_start + word["end"] - new_start}
        for word in new_words
    ]
    spliced += [
        {**word, "start": word["start"] + shift, "end": word["end"] + shift}
        for word in old_words[firsts[last_replaced + 1]:]
    ]
    timing_path.write_text(json.dumps({"words": spliced}, indent=2) + "\n")
    print(f"wrote {audio_path} and {timing_path}; now run scripts/sync_audio.py")


if __name__ == "__main__":
    sys.exit(main())
