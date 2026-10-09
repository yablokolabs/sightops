# SightOps — Implementation Progress

Last updated: 2026-10-09.

This file is written so another agent session can resume without reconstructing the
development history. It records what actually runs, what was measured, and what is
still missing.

---

## Current Phase

**Phase 9 (publication) — the product is complete and verified; documenting and
publishing remain.** Backend, vision engine, agent loop, HTTP API, frontend, Docker
deployment, evaluation harness and the demo video are all built and verified. The
repository still has **no remote configured**.

---

## Completed

### Phase 0 — Discovery and environment verification

| Item | Verified value |
|---|---|
| Python | 3.12.3 (`/usr/bin/python3`), venv at `.venv` via `uv 0.12.14` |
| OpenCV | **5.0.0** (`opencv-python==5.0.0.93`) — `cv2.__version__ == "5.0.0"` |
| NumPy | 2.5.3 |
| Node / npm | v22.23.2 / 10.9.8 |
| Docker | 29.8.1 |
| ffmpeg / ffprobe | 6.1.1 |
| GitHub CLI | 2.45.0, authenticated as `yablokolabs` |
| Hindsight | healthy on `localhost:8888`, bank `sightops` |

**Nebius** (`https://api.studio.nebius.com/v1`) — 25 models served; tool calling
verified on `Qwen/Qwen3.5-397B-A17B`, `zai-org/GLM-5.3`, `deepseek-ai/DeepSeek-V4-Pro`
and `moonshotai/Kimi-K3`. Defaults: `Qwen/Qwen3.5-397B-A17B` (reasoning),
`openbmb/MiniCPM-V-4_5` (vision).

**ElevenLabs** — 24 voices. The brief's preferred voice, Beth
(`zH7TN9vEZAsEway9xWev`), is a **library** voice and this free-tier account refuses
library voices over the API with `HTTP 402 paid_plan_required`. The demo narration
therefore uses the closest premade British female voice, Alice
(`Xb7hH8MSUJpSbSDYk0k2`). See `demo/docs/narration.md`.

**Skills** — `ponytail`, `headroom`, `diagram-design`, `nori`, `senior-swe`,
`full-send` and `adhd` are **not installed** in this workspace and no MCP server for
them is configured; recorded as a limitation rather than worked around by inventing
interfaces. Available and used: Serena MCP, `novgraph`, Tavily skills, Hindsight MCP.

### Phase 1–2 — Foundation and the OpenCV 5 vision engine

`app/config.py` (secret loader reading only the three provider keys from
`~/.hermes/.env`, never mutating `os.environ`, never logging values),
`app/models/schemas.py`, `app/storage/` (SQLite + `EvidenceStorage`), and the vision
pipeline: `preprocess.py` (rescale, denoise, CLAHE, perspective detect and rectify),
`quality.py` (normalised Laplacian-variance blur, exposure, resolution),
`regions.py`, `indicators.py` (HSV lamps, PCA switch, stroke-level display),
`gauges.py` (Hough dial, radial scan, parabolic sub-step, needle shape validation),
`change.py`, `annotate.py`, and `fixtures/generate_panels.py` with **exact ground
truth** because the fixture drew the values.

### Phase 3–7 — Agent, API, frontend, Docker, evaluation

- `providers/` — provider abstractions plus Nebius and ElevenLabs clients.
- `agent/` — 11 typed tools, an evidence-driven deterministic policy, a 13-state
  transition table (only `COMPLETED` and `CANCELLED` terminal), and a bounded loop
  (8 steps, 12 tool calls, 2 reinspection rounds, 90 s per step).
- `app/api/` — full HTTP surface including `/health`, `/api/system/status`,
  inspections, observations, timeline, tool calls, evidence (`?annotated=true`) and
  the approve/reject gate.
- Frontend — React 18 + TypeScript + Tailwind, built and typechecked.
- Diagrams — five rendered SVG+PNG architecture diagrams in `docs/diagrams/`, with
  their generator in `docs/diagrams/src/generate_diagrams.py`.

### Phase 8 — Demo video (built this session)

`demo/videowright/` is a VideoWright 0.1.1 project with a SightOps style
(`styles/sightops/`), shared scene components, ten segments, a timeline, and its own
audio toolchain: `generate.sh` (ElevenLabs), `sync_audio.py` (loudness normalise, word
timing, segment advances), `resplice_voiceover.py` (budget-limited repair),
`build_subtitles.py`, and `capture_app_screens.mjs` (Playwright capture of the real
app). Output: `demo/videos/sightops-demo.mp4`, 1920×1080, 60 fps, **4:33**, plus
SRT and WebVTT subtitles.

---

## In Progress

- Root `README.md` and `demo/README.md` written; a final read-through against the
  rendered video is still to do.
- `docs/PROGRESS.md` (this file) and Hindsight sync.

---

## Next Actions

1. Verify the rendered MP4 (duration, resolution, audio track, playable) and commit it.
2. Configure the `Yabloko-Labs/sightops` remote and push clean conventional commits.
3. Confirm the committed README renders (diagram and screenshot links resolve on GitHub).

---

## Blockers

None functional. Two constraints are carried as known limitations:

- **ElevenLabs free tier: 9,975 of 10,000 characters consumed** (25 remaining,
  reset 2026-10-24). The narration is complete, so nothing is blocked; a re-recording
  at full quality needs a paid plan or the next reset.
- **No AWS authorisation**, handled by design: the AWS-shaped seams exist and nothing
  AWS-specific is claimed as built.

---

## Tests and Results

Latest verified runs (2026-10-09):

- **Backend tests** — `cd backend && ../.venv/bin/python -m pytest -q` → 165 passed.
- **Vision demo scenarios** — `scripts/verify_demo_scenarios.py` → **17/17 PASS**.
- **Providers** — `scripts/check_providers.py` → **9/9 PASS** (OpenCV 5.0.0, 25 Nebius
  models, a live tool call returning `read_gauge`, 24 ElevenLabs voices).
- **Quality calibration** — `scripts/calibrate_quality.py --json` → exit 0; every
  in-focus fixture clears the 0.35 blur threshold and a `blur_sigma` 4.5 frame falls
  to 0.045 (0.13× the threshold), with a monotone ladder and no trend breaks.
- **COOL benchmark harness** — `scripts/bench_cool.py --arm x86-baseline --repetitions
  12 --warmup 3` → exit 0, real per-operation split (HoughCircles 4.7 ms median,
  radial scan 0.22 ms, panel detection 1.6 ms). This is an **x86-64 measurement of
  this development machine, not a COOL or Graviton result**, and no number from it is
  published as a performance claim.
- **Docker** — `docker compose build` succeeds for both images and
  `docker compose up -d` reports both services **healthy**. Verified through nginx on
  `:8080`: the SPA and its client-side routes return 200, `/health` proxies to the
  backend, `/api/system/status` reports `opencv_version: "5.0.0"` from inside the
  container, and a full industrial demo flow run through the proxy advanced
  `WAITING_FOR_USER` → `AWAITING_APPROVAL` with two observations. Provider keys are
  correctly absent in the container, and the app still runs.
- **Frontend** — `npm run build` exit 0; `tsc --noEmit` clean.
- **Evaluation** — full detail in `docs/evaluation/results.md`: gauge MAE 0.4724 PSI
  (median 0.185, p95 1.54, max 3.32), **112 published / 24 refused**, **wrong-value
  escape rate 0.9%**, indicator macro precision 0.9861 / recall 0.9853, display
  lit/blank 79.4%, switch 100%, ROI 100%, agent tasks 4/4, active-perception
  precision/recall 1.0/1.0, vision latency 9.67 ms mean (23.27 ms max) per 1280×720
  frame.
- **Demo video** — `sync_audio.py` word check passes; video length 4:33 (16,405
  frames); 61 subtitle cues ending at 04:33.119.

### A correction to an earlier claim in this file

An earlier revision of this document said the `industrial_fault_distant` fixture
(panels with `perspective=0.13` and `glare=0.30`) **"returns `UNKNOWN` with no value
for the gauge"**. That is no longer true and was not true when it was written. The
live measurement is:

| | |
|---|---|
| Gauge | `83.68 PSI` at confidence **0.5669**, state `HIGH` — published, because 0.5669 clears the 0.50 reporting floor |
| Warning lamp | `RED` at 0.9694 |
| Quality gate | `requires_new_view: true`, reason *"2 of 4 components need a better view: pressure_gauge_01 (57%); status_led_01 (52%)"* |

The demonstration's active perception therefore comes from the **quality gate on the
regions**, not from a withheld value: the agent publishes the low-confidence reading,
refuses to conclude from it, and asks for a better view. Values *are* withheld
entirely when confidence falls below 0.50 — that is a real code path exercised by 24
of the 136 evaluation frames — but it is not what happens on this fixture. The demo
video and `demo/docs/narration.md` state the corrected version.

### Defects found and fixed during development

1. **Gauge confident wrong reading** — a rotated frame whose Hough circle failed let
   the radial scan run from a displaced centre and publish **28 PSI for a true 87** at
   0.72 confidence. Fixed with needle shape validation (ray coverage ≥ 0.60, angular
   peak ≤ 14°, confidence ≥ 0.50), plus sub-step refinement and a modulo-aware sweep
   tolerance so an end-stop reading is clamped rather than refused.
2. **Indicator `OFF` mis-scored** using lit-lamp criteria — now scored from
   `brightness_gap` / `saturation_gap`.
3. **Region quality used the frame's `min_short_edge`** — added a region-level
   threshold.
4. **Display lit/blank used p95** — moved to p99 with a lit-fraction bound, because
   seven-segment glyphs cover only 1–3% of the window.
5. **Bright unsaturated lamp read as `OFF`** — now measured from the saturation of
   pixels near peak brightness.
6. **Agent state machine gaps** — added the missing `→ REASONING` edges and removed
   `FAILED` from the terminal set, because it has a recovery edge.
7. **Demo narration splice (this session)** — the repair tool calculated block offsets
   from the edited script instead of the recording and cut 22 words out of the
   diagnosis narration. Repaired with `--drop-words`, and the consequence (the
   diagnosis block opens at its second sentence) is documented in
   `demo/docs/narration.md` rather than hidden.

---

## Architecture Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | OpenCV is the only source of measurements; the model is tagged `inferred`. | Enforced by `Provenance` on every `Measurement`. |
| 2 | Provider abstractions from day one. | A Bedrock adapter becomes a drop-in; the deterministic policy runs on the same interface. |
| 3 | The deterministic demo policy is a real policy over real measurements. | `tests/test_policy.py` asserts a healthy and a faulty panel produce different traces. |
| 4 | Regions are *configured* by equipment profile, marked `source="configured"`. | Automatic panel detection exists as a separate, clearly-labelled capability. |
| 5 | SQLite + on-disk evidence behind interfaces. | Reproducible on a CPU-only VM, with a documented path to S3/DynamoDB. |
| 6 | Unknown is a first-class result. | Below the reporting floor the value is withheld and the reason recorded. |
| 7 | The video's reveals are cued by the provider's word alignment. | Nothing is hand-timed, so a narration edit moves the reveals automatically. |
| 8 | The demo video commits its own repair tooling. | The free-tier character budget is a real constraint; making the repair reproducible beats a one-off edit. |

---

## Known Limitations

- **AWS integration is NOT IMPLEMENTED.** No AWS resource has been created and no AWS
  credential is required. Bedrock, S3, DynamoDB, Lambda, CloudWatch and COOL on
  Graviton are **designed, not deployed and not benchmarked**.
- **Display reading is the weakest vision class** (79.4% lit/blank); a seven-segment
  value is not decoded by the vision engine and is left to the multimodal model,
  tagged `inferred`.
- **Regions are calibrated per profile**, not discovered generically.
- **Fixtures are synthetic** with exact ground truth; they are not photographs.
- **Tool-failure recovery is unmeasured** — no scenario forces a tool to fail.
- **ElevenLabs voice substitution** — Alice rather than Beth, and the free tier's
  character budget has forced the diagnosis narration to open at its second sentence.
- The competition skill set named in the brief is not installed in this workspace.

---

## Git Commit / Repository Status

- Repository at `/home/azureuser/sightops`, branch `main`, **no remote configured**.
- Two commits exist: `00c6f3e` (vision engine and agent loop) and `5b800b7` (HTTP
  surface, web client, diagrams, tests).
- Uncommitted at the time of writing: the vision fixes, `backend/scripts/`,
  `docs/{architecture,benchmarks,competition,evaluation}/`, `demo/`, the Docker files
  and `README.md`. These are being folded into conventional commits.
- `.gitignore` excludes secrets, `data/`, virtualenvs, `node_modules/` and
  `frontend/dist/`. No AWS resource has been provisioned at any point.
