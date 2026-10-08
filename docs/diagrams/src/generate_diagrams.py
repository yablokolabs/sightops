#!/usr/bin/env python3
"""Generate the SightOps architecture diagrams as standalone SVG.

Run from ``docs/diagrams/``:

    python3 src/generate_diagrams.py --out .

The script uses only the Python standard library. Every diagram is laid out by
hand rather than by a layout engine, so text placement is explicit and the
output has no external dependencies at all: nothing to fetch, no scripts, no
``@import``. The only ``http`` string anywhere in the output is the SVG
namespace declaration.

Text is auto-fitted to its box: ``fit_size`` estimates a line's width from an
average glyph advance and shrinks the font until the line fits, which is what
keeps labels from overflowing at GitHub README width.

The palette is sampled from the official logo (``SightOps.png`` at the
repository root) so the diagrams match the product.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# palette (sampled from SightOps.png)
# --------------------------------------------------------------------------

NAVY = "#051D35"
NAVY2 = "#053B6E"
BLUE = "#075CA7"
BLUE_LIGHT = "#3B8FD4"
SLATE = "#3E4D5C"
MIST = "#D4DADF"
PAPER = "#F7F9FB"
INK = "#0B1626"
AMBER = "#FF7A1A"
AMBER_DARK = "#B45309"
AMBER_TEXT = "#6B3B08"
GOOD = "#2E9E5B"
BAD = "#D13B3B"
MUTED = "#8A98A6"

FONT_STACK = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
ON_DARK = "#D7E6F4"

ARROW_COLOURS = {
    "blue": BLUE,
    "navy": NAVY2,
    "slate": SLATE,
    "amber": AMBER,
    "good": GOOD,
    "bad": BAD,
    "muted": MUTED,
}

#: Average glyph advance as a fraction of font size. Conservative, so lines are
#: never clipped.
AVG_ADVANCE = 0.58
LINE_HEIGHT = 1.32
MIN_FONT = 9.5


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------


def esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text_width(value: str, size: float) -> float:
    return len(value) * size * AVG_ADVANCE


def fit_size(value: str, max_width: float, size: float, minimum: float = MIN_FONT) -> float:
    """Shrink ``size`` until ``value`` fits inside ``max_width``."""
    if max_width <= 0 or not value:
        return size
    width = text_width(value, size)
    if width <= max_width:
        return size
    return max(minimum, round(size * max_width / width, 2))


def text(
    x: float,
    y: float,
    value: str,
    *,
    size: float = 14,
    fill: str = INK,
    weight: str = "400",
    anchor: str = "start",
    opacity: float | None = None,
) -> str:
    attrs = (
        f'x="{x:g}" y="{y:g}" font-size="{size:g}" fill="{fill}" '
        f'font-weight="{weight}" text-anchor="{anchor}"'
    )
    if opacity is not None:
        attrs += f' opacity="{opacity:g}"'
    return f"<text {attrs}>{esc(value)}</text>"


def rect(
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str = "none",
    stroke: str | None = None,
    sw: float = 1.6,
    rx: float = 10,
    dash: str | None = None,
    opacity: float | None = None,
) -> str:
    attrs = f'x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{rx:g}" fill="{fill}"'
    if stroke:
        attrs += f' stroke="{stroke}" stroke-width="{sw:g}"'
    if dash:
        attrs += f' stroke-dasharray="{dash}"'
    if opacity is not None:
        attrs += f' opacity="{opacity:g}"'
    return f"<rect {attrs}/>"


def line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    stroke: str = BLUE,
    sw: float = 1.7,
    dash: str | None = None,
    marker: str | None = None,
) -> str:
    attrs = (
        f'x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" '
        f'stroke="{stroke}" stroke-width="{sw:g}"'
    )
    if dash:
        attrs += f' stroke-dasharray="{dash}"'
    if marker:
        attrs += f' marker-end="url(#a-{marker})"'
    return f"<line {attrs}/>"


def path(
    d: str,
    *,
    stroke: str = BLUE,
    sw: float = 1.7,
    fill: str = "none",
    dash: str | None = None,
    marker: str | None = None,
    opacity: float | None = None,
) -> str:
    attrs = f'd="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw:g}"'
    if dash:
        attrs += f' stroke-dasharray="{dash}"'
    if marker:
        attrs += f' marker-end="url(#a-{marker})"'
    if opacity is not None:
        attrs += f' opacity="{opacity:g}"'
    return f"<path {attrs}/>"


def lifeline(x: float, y1: float, y2: float, *, stroke: str = MIST) -> str:
    return line(x, y1, x, y2, stroke=stroke, sw=1.4, dash="5 5")


def box(
    x: float,
    y: float,
    w: float,
    h: float,
    lines: list[tuple],
    *,
    fill: str,
    stroke: str | None = None,
    sw: float = 1.6,
    rx: float = 10,
    dash: str | None = None,
    pad: float = 14,
    align: str = "left",
) -> list[str]:
    """A rounded box with vertically centred, auto-fitted lines.

    ``lines`` entries are ``(text, size, colour)`` or ``(text, size, colour, weight)``.
    """
    out = [rect(x, y, w, h, fill=fill, stroke=stroke, sw=sw, rx=rx, dash=dash)]
    inner = w - 2 * pad
    prepared: list[tuple[str, float, str, str]] = []
    for entry in lines:
        label, size, colour = entry[0], entry[1], entry[2]
        weight = entry[3] if len(entry) > 3 else "400"
        prepared.append((label, fit_size(label, inner, size), colour, weight))

    total = sum(size * LINE_HEIGHT for _, size, _, _ in prepared)
    cursor = y + (h - total) / 2.0
    for label, size, colour, weight in prepared:
        if align == "center":
            out.append(
                text(x + w / 2.0, cursor + size * 0.92, label,
                     size=size, fill=colour, weight=weight, anchor="middle")
            )
        else:
            out.append(text(x + pad, cursor + size * 0.92, label, size=size, fill=colour, weight=weight))
        cursor += size * LINE_HEIGHT
    return out


def diamond(
    cx: float,
    cy: float,
    hw: float,
    hh: float,
    lines: list[tuple],
    *,
    fill: str,
    stroke: str,
    sw: float = 2.0,
) -> list[str]:
    out = [
        path(
            f"M {cx:g} {cy - hh:g} L {cx + hw:g} {cy:g} L {cx:g} {cy + hh:g} L {cx - hw:g} {cy:g} Z",
            stroke=stroke, sw=sw, fill=fill,
        )
    ]
    inner = hw * 1.30
    prepared: list[tuple[str, float, str, str]] = []
    for entry in lines:
        label, size, colour = entry[0], entry[1], entry[2]
        weight = entry[3] if len(entry) > 3 else "600"
        prepared.append((label, fit_size(label, inner, size), colour, weight))
    total = sum(size * LINE_HEIGHT for _, size, _, _ in prepared)
    cursor = cy - total / 2.0
    for label, size, colour, weight in prepared:
        out.append(
            text(cx, cursor + size * 0.92, label, size=size, fill=colour, weight=weight, anchor="middle")
        )
        cursor += size * LINE_HEIGHT
    return out


def markers() -> str:
    out = []
    for name, colour in ARROW_COLOURS.items():
        out.append(
            f'<marker id="a-{name}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 Z" fill="{colour}"/></marker>'
        )
    return "\n".join(out)


def document(width: int, height: int, title: str, desc: str, body: list[str]) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{esc(desc)}" '
        f'font-family="{FONT_STACK}">\n'
        f"<title>{esc(title)}</title>\n"
        f"<desc>{esc(desc)}</desc>\n"
        "<defs>\n" + markers() + "\n</defs>\n"
        + rect(0, 0, width, height, fill=PAPER, rx=0)
        + "\n"
        + "\n".join(body)
        + "\n</svg>\n"
    )


def heading(body: list[str], title: str, subtitle: str, *, accent: str = BLUE, width: float = 1200) -> None:
    body.append(rect(32, 26, 6, 46, fill=accent, rx=3))
    body.append(text(54, 50, title, size=24, fill=NAVY, weight="700"))
    # The subtitle is a full-width line of prose, so it is fitted to the canvas
    # rather than assumed to fit. An earlier version ran past the right edge on
    # two of the five diagrams.
    body.append(text(54, 72, subtitle, size=fit_size(subtitle, width - 86, 13.5), fill=SLATE))


def note_bar(body: list[str], x: float, y: float, w: float, lines: list[str], *, accent: str = AMBER) -> float:
    h = 16 + len(lines) * 17
    body.append(rect(x, y, w, h, fill="#FFF6EC", stroke=accent, sw=1.4, rx=8))
    body.append(rect(x, y, 5, h, fill=accent, rx=2.5))
    for index, spec in enumerate(lines):
        label, size = (spec if isinstance(spec, tuple) else (spec, 12.5))
        body.append(text(x + 16, y + 26 + index * 17, label, size=fit_size(label, w - 34, size), fill=AMBER_TEXT))
    return h


def column_header(body: list[str], x: float, y: float, label: str, width: float) -> None:
    body.append(text(x, y, label, size=13, fill=SLATE, weight="700"))
    body.append(line(x, y + 6, x + width, y + 6, stroke=MIST, sw=1.2))


# --------------------------------------------------------------------------
# diagram 1 — system architecture
# --------------------------------------------------------------------------


def system_architecture() -> str:
    W, H = 1200, 800
    body: list[str] = []
    heading(
        body,
        "SightOps — System Architecture",
        "An Agentic Visual Reliability Engineer · React + FastAPI + OpenCV 5 · as implemented and verified 2026-10-08",
    )
    note_bar(
        body, 32, 86, W - 64,
        ["All external AI calls originate from the backend. API keys are loaded server-side and never reach the browser."],
    )

    top, height = 136, 424
    client_x, client_w = 32, 186
    back_x, back_w = 274, 436
    store_x, store_w = 766, 164
    ext_x, ext_w = 986, 182

    body.append(rect(client_x, top, client_w, height, fill="#FFFFFF", stroke=MIST, sw=1.6, rx=14))
    body.append(rect(back_x, top, back_w, height, fill="#FFFFFF", stroke=BLUE, sw=2.0, rx=14))
    body.append(rect(store_x, top, store_w, height, fill="#FFFFFF", stroke=MIST, sw=1.6, rx=14))
    body.append(rect(ext_x, top, ext_w, height, fill="#FFFDF8", stroke=AMBER, sw=1.8, rx=14, dash="7 5"))

    column_header(body, client_x + 12, top + 26, "Client", client_w - 24)
    column_header(body, back_x + 12, top + 26, "Backend — Azure VM, CPU only", back_w - 24)
    column_header(body, store_x + 12, top + 26, "Local storage", store_w - 24)
    column_header(body, ext_x + 14, top + 26, "External services", ext_w - 26)

    client_items = [
        ("React 18 + TypeScript", "strict SPA, Vite build"),
        ("Tailwind design system", "palette from the logo"),
        ("Evidence viewer", "annotated + original"),
        ("Agent timeline", "decisions, tool calls"),
        ("Voice playback", "play, pause, mute"),
    ]
    y = top + 44
    for title, sub in client_items:
        body += box(
            client_x + 12, y, client_w - 24, 56,
            [(title, 12.5, NAVY, "600"), (sub, 10.5, SLATE)],
            fill="#F2F6FA", stroke=MIST, sw=1.2, rx=8, pad=10,
        )
        y += 70

    body += box(
        back_x + 12, top + 44, back_w - 24, 66,
        [("FastAPI HTTP API", 15, "#FFFFFF", "700"),
         ("Pydantic contracts · X-Request-ID middleware · structured logs", 11.5, ON_DARK)],
        fill=BLUE, stroke=NAVY2, sw=1.2, rx=9, pad=12,
    )
    body += box(
        back_x + 12, top + 122, back_w - 24, 172,
        [("OpenCV 5.0.0 vision engine", 15, "#FFFFFF", "700"),
         ("Preprocessing · rescale, bilateral denoise, CLAHE", 11.5, ON_DARK),
         ("Regions · profile regions + contour panel detection", 11.5, ON_DARK),
         ("Indicators · HSV segmentation + hue bands", 11.5, ON_DARK),
         ("Gauge · Hough dial + radial needle scan", 11.5, ON_DARK),
         ("Quality · normalised Laplacian blur, exposure", 11.5, ON_DARK),
         ("Measurements carry method, confidence, criteria", 11.5, ON_DARK)],
        fill=NAVY, stroke=NAVY2, sw=1.2, rx=9, pad=12,
    )
    body += box(
        back_x + 12, top + 306, back_w - 24, 106,
        [("Agent orchestration", 15, "#FFFFFF", "700"),
         ("Typed tool registry · inspection state machine", 11.5, ON_DARK),
         ("Bounded loop · 8 steps, 12 tool calls, 2 reinspections", 11.5, ON_DARK),
         ("Human approval gate before any action is recorded", 11.5, ON_DARK)],
        fill=NAVY2, stroke=NAVY, sw=1.2, rx=9, pad=12,
    )

    store_boxes = [
        (top + 44, [("SQLite", 13, NAVY, "700"), ("inspection state", 10.5, SLATE),
                    ("observations, timeline", 10.5, SLATE), ("tool calls, incidents", 10.5, SLATE)], "#F2F6FA", MIST, None),
        (top + 174, [("Evidence store", 13, NAVY, "700"), ("original uploads", 10.5, SLATE),
                     ("annotated derivatives", 10.5, SLATE), ("on local disk", 10.5, SLATE)], "#F2F6FA", MIST, None),
        (top + 304, [("S3 / DynamoDB", 12.5, MUTED, "700"), ("adapters exist as", 10.5, MUTED),
                     ("interfaces only —", 10.5, MUTED), ("NOT IMPLEMENTED", 10.5, BAD, "700")], "#F4F5F6", MUTED, "6 4"),
    ]
    for by, lines, fill, stroke, dash in store_boxes:
        body += box(store_x + 12, by, store_w - 24, 118, lines,
                    fill=fill, stroke=stroke, sw=1.3, rx=8, dash=dash, pad=10)

    body += box(
        ext_x + 14, top + 44, ext_w - 28, 172,
        [("Nebius AI Studio", 13.5, NAVY, "700"),
         ("Qwen/Qwen3.5-397B-A17B", 10.5, SLATE),
         ("reasoning, tool selection", 10.5, SLATE),
         ("openbmb/MiniCPM-V-4_5", 10.5, SLATE),
         ("multimodal reading", 10.5, SLATE),
         ("HTTPS · key server-side", 10.5, AMBER_DARK, "600")],
        fill="#FFFFFF", stroke=AMBER, sw=1.3, rx=8, pad=10,
    )
    body += box(
        ext_x + 14, top + 228, ext_w - 28, 184,
        [("ElevenLabs", 13.5, NAVY, "700"),
         ("text-to-speech", 10.5, SLATE),
         ("voice zH7TN9vEZAs…", 10.5, SLATE),
         ("British female · young", 10.5, SLATE),
         ("Written guidance works", 10.5, SLATE),
         ("when voice is off", 10.5, SLATE),
         ("HTTPS · key server-side", 10.5, AMBER_DARK, "600")],
        fill="#FFFFFF", stroke=AMBER, sw=1.3, rx=8, pad=10,
    )

    mid_y = top + 212
    # The two external-service arrows have to cross the storage column to reach
    # the external boundary, so their labels are anchored in the gap between
    # that column and the boundary (x 930-986) instead of at the path midpoint,
    # which would land on top of the storage boxes.
    label_end = ext_x - 6
    arrows = [
        (client_x + client_w, mid_y, back_x, "JSON", BLUE, "blue", None, None),
        (client_x + client_w, mid_y + 44, back_x, "images", BLUE_LIGHT, "blue", "5 4", None),
        (back_x + back_w, mid_y, store_x, "SQL", NAVY2, "navy", None, None),
        (store_x, mid_y + 44, back_x + back_w, "records", NAVY2, "navy", "5 4", None),
        (back_x + back_w, mid_y + 92, ext_x, "HTTPS", AMBER, "amber", None, label_end),
        (ext_x, mid_y + 136, back_x + back_w, "results", AMBER, "amber", "5 4", label_end),
    ]
    # Paths are drawn from x1 to x2, so a reverse arrow simply runs right-to-left
    # and the ``orient="auto-start-reverse"`` marker points the right way.
    for x1, y1, x2, label, colour, marker, dash, label_x in arrows:
        body.append(
            path(
                f"M {x1:g} {y1:g} H {x2:g}",
                stroke=colour, sw=1.8, dash=dash, marker=marker,
            )
        )
        if label_x is None:
            body.append(
                text((x1 + x2) / 2.0, y1 - 8, label, size=10.5, fill=colour, weight="600", anchor="middle")
            )
        else:
            body.append(
                text(label_x, y1 - 8, label, size=10.5, fill=colour, weight="600", anchor="end")
            )

    aws_y = top + 460
    body.append(rect(32, aws_y, W - 64, 176, fill="#F4F5F6", stroke=MUTED, sw=1.8, rx=12, dash="9 6"))
    body.append(text(54, aws_y + 34, "AWS — PLANNED, NOT DEPLOYED", size=16, fill=BAD, weight="700"))
    body.append(text(54, aws_y + 64, "AWS Graviton EC2 · Cloud-Optimized OpenCV Library (COOL) · Amazon Bedrock", size=13, fill=SLATE))
    body.append(text(54, aws_y + 88, "Amazon S3 · Amazon DynamoDB · AWS Lambda · Amazon CloudWatch", size=13, fill=SLATE))
    body.append(text(54, aws_y + 120, "No AWS account is used, no resource has been provisioned, and no AWS component has been benchmarked.", size=12.5, fill=BAD, weight="600"))
    body.append(text(54, aws_y + 144, "SightOps runs entirely on the existing Azure virtual machine, on CPU, with no GPU.", size=12.5, fill=SLATE))

    return document(
        W, H, "SightOps system architecture",
        "React SPA, FastAPI backend, OpenCV 5 vision engine, agent orchestration, local persistence and external Nebius and ElevenLabs services, with AWS marked as planned and not deployed.",
        body,
    )


# --------------------------------------------------------------------------
# diagram 2 — agentic vision loop
# --------------------------------------------------------------------------


def agentic_vision_loop() -> str:
    W, H = 1200, 880
    body: list[str] = []
    heading(
        body,
        "Agentic Vision Loop",
        "The perception–decision–action loop. The confidence gate is the defining behaviour: insufficient evidence loops back for another observation instead of producing a conclusion.",
    )

    left_x, left_w = 80, 340
    right_x, right_w = 700, 420

    for y, title, sub in [
        (120, "1 · Image acquisition", "upload, camera capture, or scripted demo step"),
        (214, "2 · OpenCV 5 measurement", "quality, regions, indicators, gauge, annotations"),
        (308, "3 · Confidence assessment", "per-measurement criteria; needs_reinspection flags"),
    ]:
        body += box(left_x, y, left_w, 64,
                    [(title, 14, "#FFFFFF", "700"), (sub, 11, ON_DARK)],
                    fill=NAVY, stroke=NAVY2, sw=1.3, rx=9, pad=13)
    for y in (184, 278):
        body.append(line(left_x + left_w / 2, y, left_x + left_w / 2, y + 30, stroke=BLUE, marker="blue"))

    dcx, dcy, hw, hh = left_x + left_w / 2, 470, 168, 78
    body += diamond(dcx, dcy, hw, hh,
                    [("4 · Evidence", 13.5, "#FFFFFF", "700"), ("sufficient?", 13.5, "#FFFFFF", "700")],
                    fill=AMBER, stroke=AMBER_DARK, sw=2.2)
    body.append(line(dcx, 372, dcx, dcy - hh, stroke=BLUE, marker="blue"))
    body.append(text(dcx + 10, 404, "the confidence gate", size=11, fill=AMBER_DARK, weight="600"))

    for y, title, sub in [
        (150, "5 · Agent reasoning", "choose the next tool from the measurements"),
        (244, "6 · Tool execution", "typed, validated, recorded with its result"),
        (338, "7 · Diagnosis", "stated with the evidence and its confidence"),
        (432, "8 · Safe action", "guidance, incident, approval request"),
    ]:
        body += box(right_x, y, right_w, 64,
                    [(title, 14, "#FFFFFF", "700"), (sub, 11, ON_DARK)],
                    fill=BLUE, stroke=NAVY2, sw=1.3, rx=9, pad=13)
    for y in (214, 308, 402):
        body.append(line(right_x + right_w / 2, y, right_x + right_w / 2, y + 30, stroke=BLUE, marker="blue"))

    body.append(path(f"M {dcx + hw:g} {dcy:g} H 552 V 182 H {right_x:g}", stroke=GOOD, sw=2.0, marker="good"))
    body.append(text(424, dcy - 10, "yes — evidence is good enough", size=11, fill=GOOD, weight="600"))

    body.append(line(dcx, dcy + hh, dcx, 620, stroke=AMBER, marker="amber"))
    body.append(text(dcx + 12, 604, "no", size=11.5, fill=AMBER_DARK, weight="700"))
    body += box(left_x, 620, 580, 76,
                [("Reinspection requested", 14, "#FFFFFF", "700"),
                 ("request_new_view: a closer photo, a different angle, or another region", 11, ON_DARK)],
                fill=AMBER, stroke=AMBER_DARK, sw=1.6, rx=9, pad=13)
    body.append(path(f"M {left_x:g} 658 H 44 V 152 H {left_x:g}", stroke=AMBER, sw=1.8, dash="6 4", marker="amber"))
    body.append(text(52, 500, "observe", size=10.5, fill=AMBER_DARK, weight="600"))

    body += box(right_x, 560, right_w, 136,
                [("Bounded execution", 13.5, NAVY, "700"),
                 ("max 8 agent steps", 11.5, SLATE),
                 ("max 12 tool calls", 11.5, SLATE),
                 ("max 2 reinspection rounds", 11.5, SLATE),
                 ("90 s timeout per step", 11.5, SLATE)],
                fill="#F2F6FA", stroke=SLATE, sw=1.3, rx=9, pad=13)

    body += box(left_x, 730, W - 2 * left_x, 112,
                [("Two brains, one loop", 14, NAVY, "700"),
                 ("LIVE — the Nebius model selects tools and receives each result back; if the provider fails the run continues and says so.", 11.5, SLATE),
                 ("DEMO — a deterministic policy over the same OpenCV measurements, labelled DEMO MODE everywhere; the measurements are equally real.", 11.5, SLATE),
                 ("Either way, low-confidence evidence triggers a new observation, and the new evidence changes the next action.", 11.5, NAVY2, "600")],
                fill="#FFFFFF", stroke=BLUE, sw=1.6, rx=10, pad=16)

    return document(
        W, H, "SightOps agentic vision loop",
        "The perception, measurement, confidence assessment, reasoning and action loop, with a confidence gate that requests another observation when the evidence is insufficient, plus the bounds that keep the loop finite.",
        body,
    )


# --------------------------------------------------------------------------
# diagram 3 — active perception sequence
# --------------------------------------------------------------------------


def active_perception_sequence() -> str:
    W = 1200
    participants = [
        ("User", "#FFFFFF", SLATE),
        ("SightOps UI", "#F2F6FA", BLUE),
        ("FastAPI + Agent", "#F2F6FA", BLUE),
        ("OpenCV 5 vision", "#F2F6FA", NAVY),
        ("Nebius model", "#FFFDF8", AMBER),
    ]
    xs = [146.0, 373.0, 600.0, 827.0, 1054.0]

    messages = [
        (0, 1, "uploads photo 1 of the panel", "solid"),
        (1, 2, "POST /inspections/{id}/images", "solid"),
        (2, 3, "inspect_panel(image 1)", "solid"),
        (3, 3, "measure quality + every region", "self"),
        (3, 2, "warning LED RED 0.97 · gauge UNKNOWN", "dashed"),
        (2, 2, "evidence insufficient to conclude", "self"),
        (2, 1, "request_new_view(pressure_gauge_01)", "dashed"),
        (1, 0, "state WAITING_FOR_USER · re-image square-on", "dashed"),
        (0, 1, "uploads photo 2", "solid"),
        (1, 2, "POST .../images (run_agent=true)", "solid"),
        (2, 3, "inspect_panel(image 2)", "solid"),
        (3, 2, "gauge 87.16 PSI HIGH 0.96", "dashed"),
        (2, 4, "compare_observations + diagnose", "dashed"),
        (4, 2, "abnormal condition confirmed", "dashed"),
        (2, 2, "create_incident + request_human_approval", "self"),
        (2, 1, "state AWAITING_APPROVAL", "dashed"),
        (1, 0, "approve the simulated action?", "dashed"),
        (0, 1, "approves", "solid"),
        (1, 2, "POST /approve", "solid"),
        (2, 2, "simulated remediation · COMPLETED", "self"),
    ]

    top, step = 200, 38
    bottom = top + (len(messages) - 1) * step + 40
    footer_y = bottom + 30
    H = int(footer_y + 108)

    body: list[str] = []
    heading(
        body,
        "Active Perception Sequence",
        "How SightOps recognises that it cannot yet answer, obtains a better observation, and lets the new evidence change the decision.",
    )

    for (label, fill, stroke), x in zip(participants, xs):
        body += box(x - 100, 104, 200, 54, [(label, 13, NAVY, "700")],
                    fill=fill, stroke=stroke, sw=1.6, rx=9,
                    dash="6 4" if stroke == AMBER else None, align="center")
        body.append(lifeline(x, 158, bottom + 16))

    body.append(text(1054, 174, "demo mode:", size=10.5, fill=AMBER_DARK, anchor="middle", weight="700"))
    body.append(text(1054, 188, "the deterministic policy replaces it", size=10.5, fill=AMBER_DARK, anchor="middle"))

    for index, (src, dst, label, kind) in enumerate(messages):
        y = top + index * step
        if kind == "self":
            x = xs[src]
            body.append(path(f"M {x:g} {y - 7:g} H {x + 44:g} V {y + 7:g} H {x + 2:g}",
                             stroke=NAVY2, sw=1.6, dash="5 3", marker="navy"))
            body.append(text(x + 54, y + 4, label, size=12, fill=NAVY2, weight="600"))
            continue

        x1, x2 = xs[src], xs[dst]
        solid = kind == "solid"
        body.append(line(x1, y, x2, y,
                         stroke=BLUE if solid else BLUE_LIGHT, sw=1.8 if solid else 1.6,
                         dash=None if solid else "6 4", marker="blue" if solid else "muted"))
        body.append(text(min(x1, x2) + 6, y - 7, label, size=12, fill=INK if solid else SLATE))

    body += box(32, footer_y, W - 64, 96,
                [("All remediation in this sequence is SIMULATED.", 13.5, BAD, "700"),
                 ("SightOps is decision support. It never controls real machinery, and the industrial panel is a mock with no connection to plant equipment.", 12, SLATE),
                 ("The approval at the end is a real human decision recorded in the audit trail: it authorises a record, not a command.", 12, SLATE)],
                fill="#FDF3F3", stroke=BAD, sw=1.5, rx=10, pad=16)

    return document(
        W, H, "SightOps active perception sequence",
        "A sequence diagram over the user, SightOps UI, FastAPI and agent layer, OpenCV vision engine and Nebius model, covering two observations, a reinspection request, diagnosis, incident creation and the human approval gate.",
        body,
    )


# --------------------------------------------------------------------------
# diagram 4 — deployment architecture
# --------------------------------------------------------------------------


def deployment_architecture() -> str:
    W, H = 1200, 830
    body: list[str] = []
    heading(
        body,
        "Deployment Architecture",
        "One existing Azure virtual machine, CPU only. AWS is documented as a portability path and is not deployed.",
    )

    vm_x, vm_y, vm_w, vm_h = 32, 120, 700, 520
    body.append(rect(vm_x, vm_y, vm_w, vm_h, fill="#FFFFFF", stroke=NAVY, sw=2.0, rx=14))
    body.append(text(vm_x + 20, vm_y + 34, "Azure VM — existing host, CPU only, no GPU", size=16, fill=NAVY, weight="700"))
    body.append(text(vm_x + 20, vm_y + 56, "Ubuntu · Python 3.12.3 · Node 22 · Docker 29.8.1 · ffmpeg 6.1.1", size=11.5, fill=SLATE))

    ix, iw = vm_x + 20, vm_w - 40
    body += box(ix, vm_y + 74, iw, 84,
                [("FastAPI process — port 8000", 14, "#FFFFFF", "700"),
                 ("uvicorn · /health · /api/docs · request-id middleware", 11.5, ON_DARK),
                 ("agent loop, tool registry, provider clients", 11.5, ON_DARK)],
                fill=BLUE, stroke=NAVY2, sw=1.2, rx=9, pad=13)
    body += box(ix, vm_y + 170, iw, 74,
                [("OpenCV 5.0.0 — in process, CPU", 14, "#FFFFFF", "700"),
                 ("opencv-python==5.0.0.93 · NumPy 2.5.3 · no GPU code paths", 11.5, ON_DARK)],
                fill=NAVY, stroke=NAVY2, sw=1.2, rx=9, pad=13)
    body += box(ix, vm_y + 256, iw, 74,
                [("React static bundle — port 5173 (dev)", 13.5, "#FFFFFF", "700"),
                 ("Vite build · Tailwind · calls /api on the same origin", 11.5, ON_DARK)],
                fill=NAVY2, stroke=NAVY, sw=1.2, rx=9, pad=13)

    half = (iw - 16) / 2
    body += box(ix, vm_y + 342, half, 76,
                [("SQLite file", 12.5, NAVY, "700"),
                 ("data/sightops.db", 10.5, SLATE),
                 ("inspection + incident state", 10.5, SLATE)],
                fill="#F2F6FA", stroke=MIST, sw=1.2, rx=9, pad=12)
    body += box(ix + half + 16, vm_y + 342, half, 76,
                [("Evidence directory", 12.5, NAVY, "700"),
                 ("data/evidence/", 10.5, SLATE),
                 ("originals + annotations", 10.5, SLATE)],
                fill="#F2F6FA", stroke=MIST, sw=1.2, rx=9, pad=12)
    body += box(ix, vm_y + 430, iw, 72,
                [("Docker Compose — docker compose up --build", 12.5, NAVY, "700"),
                 ("backend and frontend services, project-local volumes and ports", 10.5, SLATE)],
                fill="#F2F6FA", stroke=MIST, sw=1.2, rx=9, pad=12)

    ext_x, ext_w = 772, 396
    body.append(rect(ext_x, vm_y, ext_w, 236, fill="#FFFDF8", stroke=AMBER, sw=1.8, rx=14, dash="7 5"))
    body.append(text(ext_x + 18, vm_y + 32, "Boundary — outbound HTTPS only", size=14, fill=NAVY, weight="700"))
    body.append(text(ext_x + 18, vm_y + 52, "Credentials are read server-side from ~/.hermes/.env", size=10.5, fill=SLATE))
    body += box(ext_x + 18, vm_y + 66, ext_w - 36, 74,
                [("Nebius AI Studio", 12.5, NAVY, "700"),
                 ("Qwen/Qwen3.5-397B-A17B reasoning", 10.5, SLATE),
                 ("openbmb/MiniCPM-V-4_5 vision", 10.5, SLATE)],
                fill="#FFFFFF", stroke=AMBER, sw=1.2, rx=8, pad=11)
    body += box(ext_x + 18, vm_y + 150, ext_w - 36, 70,
                [("ElevenLabs", 12.5, NAVY, "700"),
                 ("text-to-speech, British female", 10.5, SLATE),
                 ("optional — text works without it", 10.5, SLATE)],
                fill="#FFFFFF", stroke=AMBER, sw=1.2, rx=8, pad=11)

    body.append(line(vm_x + vm_w, vm_y + 100, ext_x, vm_y + 100, stroke=AMBER, sw=2.0, marker="amber"))
    body.append(text(vm_x + vm_w + 20, vm_y + 92, "egress", size=10, fill=AMBER_DARK, weight="600", anchor="middle"))

    aws_y = vm_y + 266
    body.append(rect(ext_x, aws_y, ext_w, 254, fill="#F4F5F6", stroke=MUTED, sw=1.8, rx=14, dash="9 6"))
    body.append(text(ext_x + 18, aws_y + 32, "AWS — NOT DEPLOYED", size=14, fill=BAD, weight="700"))
    body.append(text(ext_x + 18, aws_y + 52, "NOT PROVISIONED · NOT BENCHMARKED", size=10, fill=BAD, weight="600"))
    body.append(text(ext_x + 18, aws_y + 78, "The compute grant was not awarded, so there", size=10.5, fill=SLATE))
    body.append(text(ext_x + 18, aws_y + 96, "is no AWS account and no spend. These are", size=10.5, fill=SLATE))
    body.append(text(ext_x + 18, aws_y + 114, "interface and documentation targets only:", size=10.5, fill=SLATE))
    for index, service in enumerate(
        ["AWS Graviton + COOL", "Amazon Bedrock", "Amazon S3", "Amazon DynamoDB", "AWS Lambda", "CloudWatch"]
    ):
        body.append(text(ext_x + 26, aws_y + 142 + index * 18, f"·  {service}", size=10.5, fill=MUTED))

    body += box(32, vm_y + 550, W - 64, 128,
                [("Development-environment notes", 13.5, NAVY, "700"),
                 ("Hindsight memory service on port 8888 is a development aid and is not part of the product runtime.", 11.5, SLATE),
                 ("Ports 8000 and 5173 are free for SightOps; 8888 is already in use by Hindsight, so nothing is started there.", 11.5, SLATE),
                 ("No unrelated service on this host is modified, and remediation actions are simulated rather than executed.", 11.5, SLATE)],
                fill="#FFFFFF", stroke=BLUE, sw=1.5, rx=10, pad=16)

    return document(
        W, H, "SightOps deployment architecture",
        "A single existing Azure virtual machine running the FastAPI backend, OpenCV 5, the React bundle, SQLite and a local evidence directory, with outbound HTTPS to Nebius and ElevenLabs, and AWS clearly marked as not deployed.",
        body,
    )


# --------------------------------------------------------------------------
# diagram 5 — inspection state machine
# --------------------------------------------------------------------------


def inspection_state_machine() -> str:
    W, H = 1200, 880
    body: list[str] = []
    heading(
        body,
        "Inspection State Machine",
        "Generated from app/agent/state.py, the single transition table the agent loop validates against. Every state below appears in a real inspection trace.",
    )

    nodes = {
        "CREATED": (70, 180, 150, 50),
        "OBSERVING": (70, 255, 150, 50),
        "ANALYZING": (70, 330, 150, 50),
        "REASONING": (70, 455, 150, 58),
        "DIAGNOSING": (320, 150, 180, 50),
        "ACTION_PROPOSED": (320, 235, 180, 50),
        "NEEDS_MORE_EVIDENCE": (320, 360, 220, 50),
        "WAITING_FOR_USER": (320, 435, 220, 50),
        "REOBSERVING": (320, 510, 220, 50),
        "COMPLETED": (660, 150, 180, 50),
        "AWAITING_APPROVAL": (660, 235, 210, 50),
        "FAILED": (900, 300, 160, 50),
        "CANCELLED": (900, 390, 160, 50),
    }

    for name, (x, y, w, h) in nodes.items():
        if name == "REASONING":
            fill, stroke, sw, colour = NAVY, AMBER, 2.6, "#FFFFFF"
        elif name == "AWAITING_APPROVAL":
            fill, stroke, sw, colour = "#FFF6EC", AMBER, 2.6, NAVY
        elif name in {"FAILED", "CANCELLED"}:
            fill, stroke, sw, colour = "#FDF3F3", BAD, 1.8, BAD
        elif name == "COMPLETED":
            fill, stroke, sw, colour = "#EEF8F1", GOOD, 2.0, NAVY
        else:
            fill, stroke, sw, colour = "#FFFFFF", BLUE, 1.6, NAVY
        body += box(x, y, w, h, [(name, 12, colour, "700")],
                    fill=fill, stroke=stroke, sw=sw, rx=9, pad=10, align="center")

    def edge(d: str, *, stroke: str = BLUE, dash: str | None = None,
             marker: str = "blue", sw: float = 1.7) -> None:
        body.append(path(d, stroke=stroke, sw=sw, dash=dash, marker=marker))

    # forward chain
    edge("M 145 230 V 255")
    edge("M 145 305 V 330")
    edge("M 145 380 V 455")

    # REASONING branches; corridors at x=262 and x=288 keep them apart
    edge("M 220 468 H 262 V 175 H 320")
    edge("M 220 484 H 288 V 260 H 320")
    edge("M 175 513 V 535 H 300 V 385 H 320", stroke=NAVY2, marker="navy")

    # diagnosis and action chains
    edge("M 500 175 H 660")
    edge("M 500 260 H 660")
    edge("M 430 410 V 435")
    edge("M 430 485 V 510")
    edge("M 430 560 V 585 H 56 V 355 H 70", stroke=NAVY2, marker="navy")

    # return edges (no crossings: they use the free corridor between columns)
    edge("M 320 165 V 112 H 240 V 430 H 190 V 455", stroke=BLUE_LIGHT, dash="7 5", marker="muted")
    edge("M 320 255 H 296 V 505 H 220", stroke=BLUE_LIGHT, dash="7 5", marker="muted")

    # failure and recovery
    edge("M 145 513 V 660 H 855 V 325 H 900", stroke=BAD, dash="6 4", marker="bad")
    edge("M 765 285 V 340 H 900", stroke=BAD, dash="6 4", marker="bad")
    edge("M 150 513 V 680 H 880 V 415 H 900", stroke=BAD, dash="6 4", marker="bad")
    edge("M 1060 325 H 1120 V 700 H 40 V 280 H 70", stroke=GOOD, dash="6 4", marker="good")

    body += box(32, 730, W - 64, 122,
                [("Legend", 13, NAVY, "700"),
                 ("Solid blue forward · dashed blue return and re-entry · red dashed failure · green dashed recovery (FAILED → OBSERVING).", 11.5, SLATE),
                 ("AWAITING_APPROVAL is the human gate: no simulated remediation is recorded as approved without it, and nothing is executed on real machinery.", 11.5, SLATE),
                 ("The two dashed blue edges are the return paths: DIAGNOSING → REASONING and ACTION_PROPOSED → REASONING. A recorded diagnosis can still become an incident and an approval request.", 11.5, SLATE),
                 ("FAILED and CANCELLED are reachable from every active state. The table also permits WAITING_FOR_USER → REASONING and WAITING_FOR_USER → DIAGNOSING.", 11.5, SLATE),
                 ("FAILED → OBSERVING (green) recovers a faulted run. COMPLETED → REASONING re-opens a finished inspection when the user reports the problem is still present.", 11.5, SLATE)],
                fill="#FFFFFF", stroke=SLATE, sw=1.4, rx=10, pad=16)

    return document(
        W, H, "SightOps inspection state machine",
        "The thirteen inspection states with their forward, return, failure and recovery transitions, including the human approval gate.",
        body,
    )


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------

DIAGRAMS = {
    "system-architecture.svg": system_architecture,
    "agentic-vision-loop.svg": agentic_vision_loop,
    "active-perception-sequence.svg": active_perception_sequence,
    "deployment-architecture.svg": deployment_architecture,
    "inspection-state-machine.svg": inspection_state_machine,
}


def rasterise(svg_path: Path, png_path: Path) -> tuple[bool, str]:
    """Convert one SVG to PNG, reporting which tool was used."""
    if shutil.which("rsvg-convert"):
        result = subprocess.run(
            ["rsvg-convert", "-w", "1600", "-o", str(png_path), str(svg_path)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return True, "rsvg-convert"
        return False, f"rsvg-convert failed: {result.stderr.strip()[:200]}"

    if shutil.which("cairosvg"):
        result = subprocess.run(
            ["cairosvg", str(svg_path), "-o", str(png_path), "-s", "1.6"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return True, "cairosvg"
        return False, f"cairosvg failed: {result.stderr.strip()[:200]}"

    try:
        import cairosvg  # type: ignore
    except Exception:
        pass
    else:
        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), scale=1.6)
        return True, "cairosvg (python module)"

    if shutil.which("inkscape"):
        result = subprocess.run(
            ["inkscape", str(svg_path), "--export-type=png",
             f"--export-filename={png_path}", "--export-width=1600"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return True, "inkscape"
        return False, f"inkscape failed: {result.stderr.strip()[:200]}"

    return False, "no rasteriser found (looked for rsvg-convert, cairosvg, inkscape)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=".", help="output directory for the SVGs and PNGs")
    parser.add_argument("--no-png", action="store_true", help="skip PNG fallbacks")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for filename, builder in DIAGRAMS.items():
        svg_path = out / filename
        svg_path.write_text(builder(), encoding="utf-8")
        print(f"wrote {svg_path}")

    if args.no_png:
        print("PNG fallbacks skipped by request (--no-png).")
        return 0

    used: set[str] = set()
    for filename in DIAGRAMS:
        png_path = (out / filename).with_suffix(".png")
        ok, detail = rasterise(out / filename, png_path)
        if ok:
            used.add(detail)
        else:
            print(
                f"PNG fallback for {filename} was SKIPPED: {detail}.\n"
                "  Install one of these and re-run:\n"
                "    sudo apt-get install -y librsvg2-bin      # provides rsvg-convert\n"
                "    python3 -m pip install cairosvg",
                file=sys.stderr,
            )
    if used:
        print(f"PNG fallbacks written with: {', '.join(sorted(used))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
