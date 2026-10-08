# SightOps — Implementation Progress

Last updated: 2026-10-08.

This file is written so another agent session can resume without reconstructing
the development history. It records what actually runs, what was measured, and
what is still missing.

---

## Current Phase

Phase 3 (agentic inspection engine) — backend vision and agent loops are
working and verified; the HTTP API and frontend are next.

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
| Hindsight | healthy on `localhost:8888` (`{"status":"healthy","database":"connected"}`) |
| Ports in use | 8888 only (Hindsight). 8000 and 5173 are free for SightOps. |

**Nebius** (`https://api.studio.nebius.com/v1`) — 25 models served. Tool calling
was tested against a real function schema and works on `Qwen/Qwen3.5-397B-A17B`,
`zai-org/GLM-5.3`, `deepseek-ai/DeepSeek-V4-Pro` and `moonshotai/Kimi-K3`
(each returned a well-formed `tool_calls` array with
`finish_reason="tool_calls"`). `openbmb/MiniCPM-V-4_5` is served for multimodal
interpretation. Chosen defaults: `Qwen/Qwen3.5-397B-A17B` (reasoning) and
`openbmb/MiniCPM-V-4_5` (vision).

**ElevenLabs** — voices listed from the account with `GET /v1/voices`. Chosen
voice: `zH7TN9vEZAsEway9xWev` (**Beth**, labels `british` / `female` / `young`) —
the only entry carrying all three, and an exact match for the brief.

**Skills and MCP tools** — `ponytail`, `headroom`, `diagram-design`, `nori`,
`senior-swe`, `full-send` and `adhd` are **not installed** in this workspace and
no MCP server for them is configured; this is recorded as a limitation rather
than worked around by inventing interfaces. Available and used: Serena MCP
(semantic navigation), `novgraph` skill, Tavily skills, Hindsight MCP.

### Phase 1 — Foundation

- `backend/pyproject.toml` with pinned dependencies.
- `app/config.py` — settings plus a secret loader that reads only
  `NEBIUS_API_KEY`, `ELEVENLABS_API_KEY` and `TAVILY_API_KEY` from
  `~/.hermes/.env`; it never copies the whole file into the process, and
  `provider_status()` reports presence rather than values.
- `app/models/schemas.py` — typed contracts for the whole system.
- `app/storage/` — SQLite schema, repository, and an `EvidenceStorage`
  abstraction with a local implementation.
- `.gitignore` covering secrets, virtualenvs and runtime data.

### Phase 2 — OpenCV 5 vision engine

Real, measured operations (no step is decorative):

- `preprocess.py` — rescale to a working copy, gray/alpha normalisation,
  bilateral denoise, CLAHE on the L channel, ROI cropping, perspective
  detection and rectification (`auto_perspective`).
- `quality.py` — normalised Laplacian-variance blur score, exposure quality from
  clipping fractions and mean luma, resolution sufficiency.
- `indicators.py` — HSV lamp segmentation with contour selection and hue-band
  classification; switch orientation by PCA on the lever blob; display
  lit/blank detection from stroke level and lit fraction.
- `gauges.py` — Hough dial localisation with a calibrated fallback, radial scan
  over the 0.28R–0.72R band, dual-polarity peak search, sub-step parabolic
  refinement, then **needle shape validation** (ray coverage and angular width).
- `regions.py` — panel detection by contour rectangularity.
- `change.py` — structured measurement diff plus a pixel-difference metric.
- `annotate.py` — evidence overlays drawn from the same numbers the agent used.
- `fixtures/generate_panels.py` — synthetic panels and dishwasher fascias with
  **exact ground truth**, because the fixture drew them, plus degradations
  (blur, exposure, glare, rotation, perspective, resolution, noise).

Verified measurements (see `Tests and Results` below): every indicator, switch
and display state matches ground truth across all six fixtures; gauge absolute
error is 0.04 PSI and 0.16 PSI on the two clean fixtures.

### Phase 3 — Agentic engine (in progress, core working)

- `providers/` — `ModelProvider` / `VoiceProvider` abstractions, a Nebius client
  (timeouts, retries with backoff, tool calling, multimodal call) and an
  ElevenLabs client.
- `agent/tools.py` — 11 typed tools with Pydantic argument models:
  `inspect_panel`, `inspect_region`, `read_gauge`, `detect_indicator`,
  `check_image_quality`, `compare_observations`, `request_new_view`,
  `record_diagnosis`, `create_incident`, `request_human_approval`, `ask_user`.
- `agent/state.py` — the inspection state machine as a single transition table.
- `agent/policy.py` — the deterministic, evidence-driven demo policy.
- `agent/loop.py` — the bounded agent loop (steps, tool calls, reinspection
  rounds, per-step timeout), with the deterministic policy as both the demo
  brain and the degraded fallback when the model is unavailable.
- Human approval is enforced: the industrial trace stops in `AWAITING_APPROVAL`
  and no remediation can be recorded as executing.

---

## In Progress

- `app/api/` and `main.py` — the FastAPI surface.
- Frontend (React + TypeScript + Tailwind).

---

## Next Actions

1. FastAPI routes, OpenAPI models, request IDs, structured logging.
2. React frontend: landing, home workspace, industrial workspace, inspection
   history, incident view, settings/status.
3. ElevenLabs voice playback in the UI.
4. Test suite and the evaluation harness producing `docs/evaluation/`.
5. Rendered SVG architecture diagrams and README.
6. Demo video.
7. GitHub publication.

---

## Blockers

None. AWS credits were not awarded, which is handled by design (see below)
rather than blocking anything.

---

## Tests and Results

Latest verified run (`2026-10-08`), full detail in `docs/evaluation/results.md`:

- **Vision, all six fixtures** — every indicator, switch and display
  classification matches ground truth.
- **Gauge accuracy** — `industrial_normal` true 42.0 PSI, measured 42.04
  (error 0.04, confidence 0.983); `industrial_fault_closeup` true 87.0,
  measured 87.16 (error 0.16, confidence 0.959).
- **Honest failure** — `industrial_fault_distant` (perspective 0.13, glare 0.30)
  returns `UNKNOWN` with no value for the gauge rather than a wrong number.
- **Active perception** — the industrial demo trace is:
  measure → gauge unreadable, warning lamp `RED` → request a better view
  (state `WAITING_FOR_USER`) → new image → re-measure → compare observations
  (2 changes) → diagnosis → incident → `AWAITING_APPROVAL`.

### A defect found and fixed during development

The first gauge implementation produced a **confident wrong reading**: with a
rotated or perspective-distorted frame whose circle Hough could not find, the
radial scan from a displaced centre still returned a peak, and the confidence
formula scored it 0.72 while reporting **28 PSI for a true 87 PSI**. A needle is
now accepted only if the sampled ray is consistently on the needle's side
(coverage ≥ 0.60) and the angular peak is narrow (≤ 14°), and no value is
published below 0.50 confidence. Sweep evidence is in
`docs/evaluation/results.md`.

---

## Architecture Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | OpenCV is the only source of measurements; the model is tagged `inferred`. | A VLM guess must never overwrite a measured value. Enforced by `Provenance` on every `Measurement`. |
| 2 | Provider abstractions from day one. | The Bedrock adapter in `docs/architecture/aws.md` becomes a drop-in; the deterministic policy also runs on the same interface. |
| 3 | The deterministic demo policy is a real policy over real measurements, not a replay. | The brief forbids canned behaviour; `tests/test_policy.py` asserts a healthy panel and a faulty panel produce different traces. |
| 4 | Regions are *configured* by equipment profile and marked `source="configured"`. | The build spec permits calibrated regions for the demonstrator; automatic panel detection exists as a separate, clearly-labelled capability. |
| 5 | SQLite + on-disk evidence behind interfaces. | Reproducible on a CPU-only VM, with a documented path to S3/DynamoDB. |
| 6 | Unknown is a first-class result. | `GaugeState.UNKNOWN` and below-threshold readings withhold the number entirely. A wrong pressure reading is worse than "unreadable". |

---

## Known Limitations

- **AWS integration is NOT IMPLEMENTED.** No AWS resource has been created and
  no AWS credentials are required. `docs/architecture/aws.md` documents the
  intended design only. COOL on Graviton has **not** been benchmarked.
- Regions are calibrated per equipment profile, not discovered generically.
  Automatic panel detection exists but does not identify which component is
  which on an unseen panel.
- A VLM cannot yet read a seven-segment display in this build; display
  interpretation stops at lit/blank, and this is stated in the UI.
- The competition voices the brief lists (`ponytail`, `headroom`,
  `diagram-design`, `nori`, `senior-swe`, `full-send`, `adhd`) are not installed.
- Frontend, diagrams, demo video and GitHub publication are not complete yet.

---

## Git Commit / Repository Status

- Repository initialised at `/home/azureuser/sightops` (no remote configured yet).
- No AWS resources provisioned at any point.
