# SightOps — Architecture Overview

This describes the system as it runs today on the Azure VM: a React client, a
FastAPI backend, an OpenCV 5 vision engine, a bounded agent loop, SQLite, and a
filesystem evidence store. AWS is **not** part of it — see
`docs/architecture/aws.md`.

- OpenCV `5.0.0` (`opencv-python==5.0.0.93`)
- Python 3.12.3, NumPy 2.5.3
- FastAPI 0.143.0, Pydantic 2.14.0, aiosqlite 0.22.1, httpx 0.28.1
- React 18 + TypeScript + Tailwind, built with Vite 5

---

## 1. Request lifecycle

A single inspection turn, from the browser to the trace:

```
browser (React)
    │  POST /api/inspections/{id}/images   (multipart, image bytes)
    ▼
FastAPI route  app/api/inspections.py
    │  · content-type allow-list
    │  · VisionEngine.decode()  — size, decode, 32px minimum, pixel cap
    │  · EvidenceStorage.put()  — original bytes, key <inspection_id>/<image_id>.img
    │  · Repository.add_image / add_observation / add_timeline
    │  · clears any outstanding ReinspectionRequest
    ▼
InspectionAgent.run()   app/agent/loop.py
    │  · resolves the brain: live model, or the deterministic policy
    │  · walks the inspection state machine (app/agent/state.py)
    │  └─ per step: choose a tool → validate arguments → execute → persist
    ▼
Tool execution   app/agent/tools.py
    │  inspect_panel / inspect_region / read_gauge / detect_indicator /
    │  check_image_quality / compare_observations / request_new_view /
    │  record_diagnosis / create_incident / request_human_approval / ask_user
    ▼
VisionEngine   app/vision/engine.py
    │  decode → working copy → per-region quality → per-region measurement
    │  → annotation → AnalysisResult
    ▼
Repository (SQLite)  +  EvidenceStorage (filesystem)
    │  observations, timeline entries, tool-call records, incidents
    ▼
browser
   GET /api/inspections/{id}            inspection + state + assessment
   GET /api/inspections/{id}/timeline   the agent's observable trace
   GET /api/inspections/{id}/tool-calls raw tool calls with arguments and timings
   GET /api/inspections/{id}/evidence/{image_id}?annotated=true
```

Every response carries `X-Request-ID`; the middleware in `app/main.py` sets it
(accepting an inbound one) and logs `method path -> status (ms) request_id=`.
An unhandled exception becomes a JSON 500 with the same id rather than a bare
traceback, so a user can quote a request id in a bug report.

All external AI calls originate in the backend. The browser never sees an API
key: `GET /api/system/status` returns `providers` as booleans only.

---

## 2. Module map

| Path | Role |
|---|---|
| `app/main.py` | App factory, request-ID middleware, CORS, startup/shutdown, error handling |
| `app/config.py` | `Settings` (all overridable with `SIGHTOPS_*`) and `load_secrets()`, which reads only the three provider keys out of `~/.hermes/.env` |
| `app/api/deps.py` | The single `AppContext` built at startup: repository, engine, evidence store, agent, providers |
| `app/api/system.py` | `/health`, `/api/system/status`, `/api/system/opencv`, incidents, voice |
| `app/api/inspections.py` | Inspection CRUD, image upload, analyse, messages, evidence, approve/reject, resolve |
| `app/api/demo.py` | Scripted demonstration flows backed by generated fixtures |
| `app/models/schemas.py` | Every typed contract: `Measurement`, `AnalysisResult`, `Inspection`, `Incident`, `TimelineEntry`, `ToolCallRecord`, enums, provenance |
| `app/vision/engine.py` | The only place pixels become measurements; also `version_report()` |
| `app/vision/preprocess.py` | Working-copy normalisation, denoise, CLAHE, ROI crop, perspective detect/rectify |
| `app/vision/quality.py` | Blur, exposure and resolution scoring, and the `requires_new_view` decision |
| `app/vision/indicators.py` | HSV lamp classification, PCA switch orientation, display lit/blank |
| `app/vision/gauges.py` | Dial localisation, radial scan, needle shape validation, angle→value |
| `app/vision/regions.py` | Automatic panel detection by contour rectangularity |
| `app/vision/change.py` | Structured measurement diff and a pixel-difference metric |
| `app/vision/annotate.py` | Evidence overlays drawn from the same numbers the agent reasoned over |
| `app/vision/profiles.py` | Equipment profiles: the configured regions and gauge calibration |
| `app/agent/tools.py` | The 11 tools, each with a Pydantic argument model and a JSON schema |
| `app/agent/loop.py` | `InspectionAgent`, the bounded loop, mode resolution, annotation |
| `app/agent/state.py` | The inspection state machine as one transition table |
| `app/agent/policy.py` | The deterministic, evidence-driven demo policy |
| `app/agent/prompts.py` | System prompts and the evidence digest |
| `app/providers/base.py` | `ModelProvider`, `VoiceProvider`, `ModelResponse`, `ToolCall`, `ProviderError` |
| `app/providers/nebius.py` | Nebius AI Studio client (OpenAI-compatible) with retries and backoff |
| `app/providers/elevenlabs.py` | ElevenLabs TTS client and voice listing |
| `app/storage/db.py` | SQLite schema and connection |
| `app/storage/repo.py` | `Repository`: the only code that touches the database |
| `app/storage/evidence.py` | `EvidenceStorage` interface and `LocalEvidenceStorage` |
| `app/fixtures/generate_panels.py` | Synthetic panels with exact ground truth, plus degradations |

---

## 3. Vision pipeline

### 3.1 Ingestion and preprocessing

| Stage | OpenCV operation | Notes |
|---|---|---|
| Decode | `cv2.imdecode` | After a size check (`max_upload_bytes`, 12 MiB) and before a pixel-count check (`max_image_pixels`, 40 M). Both run *before* the pipeline so a decompression bomb cannot exhaust the box. |
| Working copy | `cv2.cvtColor` (GRAY2BGR / BGRA2BGR), `cv2.resize` with `INTER_AREA` | Longest edge reduced to 1280 px. The original upload is stored byte-for-byte and never modified. |
| Denoise | `cv2.bilateralFilter` | Edge-preserving, so LED and needle edges survive. Applied inside the measurement paths that need it, not blindly to the whole frame. |
| Contrast | `cv2.createCLAHE` on the L channel of `cv2.cvtColor(..., COLOR_BGR2LAB)` | Gauge and indicator crops only. |
| Rectification (opt-in) | `cv2.Canny`, `cv2.morphologyEx(MORPH_CLOSE)`, `cv2.findContours`, `cv2.approxPolyDP`, `cv2.getPerspectiveTransform`, `cv2.warpPerspective` | `auto_perspective()` recovers an axis-aligned panel when the panel is the dominant quadrilateral. When nothing convincing is found the frame is returned **unchanged**, because an honest quality score beats a badly warped frame. |

Preprocessing is recorded: `AnalysisResult.preprocessing` lists the operations
that actually ran, so a measurement can be traced back to the pixels it came
from.

### 3.2 Region of interest

Regions are **configured**, not discovered. `app/vision/profiles.py` defines each
equipment profile's components as normalised boxes with a `kind`
(`gauge`, `indicator`, `switch`, `display`, `panel`) and `source="configured"`.
The UI never presents them as detected. Two profiles ship today:
`industrial_panel_v1` (gauge, warning lamp, status lamp, selector) and
`dishwasher_panel_v1` (status display, power lamp, start lamp).

Automatic detection exists as a separate capability:
`app/vision/regions.py::detect_panel` finds the dominant panel-shaped
quadrilateral by contour area and rectangularity, and `inspect_panel` reports it
alongside the configured measurements with `source: "detected"`. It finds *a
panel*; it does not identify which component is which on an unseen panel.

### 3.3 Indicator classification

| Step | Operation |
|---|---|
| Colour space | `cv2.cvtColor(BGR2HSV)` |
| Lamp segmentation | Threshold on V and S, with the V floor set relative to the ROI's own 99th percentile so it works on a bright or a dark panel |
| Morphology | `cv2.morphologyEx` open then close with an elliptical kernel |
| Blob selection | `cv2.findContours` + `cv2.contourArea`, then `cv2.drawContours` to render the largest blob as a clean mask |
| Hue bands | A 180-bin `np.bincount` histogram of the blob's hue, grouped into RED (two bands, pooled), AMBER, GREEN, BLUE, VIOLET |

Three special cases sit before the hue decision, each because a test or a
measurement caught them:

- **Unlit.** A region with no lamp-like pixels is evidenced by the *gap* between
  its brightest pixels and the levels a lit lamp reaches, not by the lit-lamp
  formula. Reusing the lit formula reported a confident `OFF` as unsure, purely
  because a uniform dark crop has little detail for the blur metric to measure.
- **White.** A bright, hue-less lamp needs its own branch; otherwise the `OFF`
  test fires on its low saturation and reports a clearly lit white indicator as
  unlit. Saturation is measured over the lamp's own bright pixels — a dark bezel
  supplies a high HSV saturation of its own.
- **Unknown.** A blob too small to place in a hue band yields `UNKNOWN` with a
  low confidence, which is what drives the agent to ask for a better view.

### 3.4 Switch and display

**Switch** (`classify_switch`) — `cv2.cvtColor(BGR2GRAY)`,
`cv2.GaussianBlur`, `cv2.threshold(THRESH_OTSU)`, `cv2.morphologyEx`,
`cv2.findContours`, then `cv2.PCACompute2` over the blob pixels for the lever's
principal axis. PCA is used rather than `cv2.fitEllipse` because the ellipse
angle convention is version-dependent. Within 30° of vertical reads `UP`/`DOWN`;
within 30° of horizontal reads `LEFT`/`RIGHT`; in between reads `UNKNOWN`, since
a two-position switch has no mid position to report.

**Display** (`classify_display`) — luminance only. The 99th percentile of grey
tracks the glyph strokes (a seven-segment glyph covers one to three percent of
the window, so p95 reports the dark background and calls a lit display blank).
Lit requires a stroke level above 110, a dynamic range above 60 and a lit
fraction between 0.2 % and 60 %. **No OCR**: digit interpretation is left to the
multimodal model and tagged as inferred.

### 3.5 Analog gauge

The most involved path, and the one with the most scar tissue. Five stages:

1. **Preprocess** — `cv2.cvtColor(BGR2GRAY)`, `cv2.createCLAHE(2.0, (8,8))`,
   `cv2.bilateralFilter(7, 40, 40)`.
2. **Dial localisation** — `cv2.medianBlur` then `cv2.HoughCircles` with
   `HOUGH_GRADIENT`. A circle is accepted only if it is plausibly concentric
   with the configured region and within ±30 % of the inscribed radius;
   otherwise the inscribed circle of the configured ROI is used and
   `details.dial_source` records `configured_roi_inscribed`. The confidence is
   multiplied by 0.85 in that case, because profile geometry is weaker evidence
   than geometry measured from the image.
3. **Radial scan** — for each angle at `ANGLE_STEP_DEG = 0.5°` from −180° to
   +180°, 24 samples are taken along a ray from `0.28 R` to `0.72 R`, and the
   per-angle mean forms an angular profile. That radial band is the whole trick:
   printed ticks live beyond `0.8 R` and the hub sits inside `0.25 R`, so the
   needle is the only feature spanning the sampled band.
4. **Peak selection** — the angular median is subtracted, the residual is
   normalised by its own median absolute deviation, and both polarities are
   tested (a dark needle on a pale dial, or a light one on a dark dial). The
   stronger peak wins. A rival peak more than `RIVAL_SEPARATION_DEG = 20°` away
   constrains the confidence through `margin_score`. A parabolic fit through the
   peak and its two neighbours refines the angle to roughly half a step.
5. **Needle shape validation** — described below, because it is the reason a
   wrong reading cannot be published.

### 3.6 Confidence model

Every measurement carries its confidence *criteria* in `details.criteria`, so a
low figure can be read back to the term that caused it.

**Indicator** (`_WEIGHTS` in `indicators.py`), `confidence = Σ criterion × weight`:

| Criterion | Weight | Meaning |
|---|---|---|
| `hue_purity` | 0.40 | Share of lamp pixels inside the winning hue band |
| `area_score` | 0.20 | Lamp area relative to the ROI, ramping to 1.0 at 3 % |
| `saturation_score` | 0.20 | Mean saturation of the lamp against `SATURATION_REFERENCE = 120` |
| `value_score` | 0.15 | Mean brightness above `VALUE_FLOOR = 60`, saturating at +120 |
| `quality_factor` | 0.05 | `0.5 × blur_score + 0.5 × exposure_quality` of the lamp crop |

`requires_reinspection` is set when confidence is below 0.55, or when the region
quality asks for a new view *and* confidence is below 0.85 — a strong colour
reading survives a marginal quality flag; a marginal one does not.

**Gauge** (`_WEIGHTS` in `gauges.py`):

| Criterion | Weight | Meaning |
|---|---|---|
| `coverage_score` | 0.25 | Ray consistency, ramping from `COVERAGE_FLOOR = 0.60` to 1.0 |
| `peak_score` | 0.25 | Peak prominence over angular noise, saturating at `PEAK_PROMINENCE_FULL = 3.0` |
| `width_score` | 0.15 | Angular FWHM, 1.0 at `WIDTH_GOOD_DEG = 3°` falling to 0 at `WIDTH_BAD_DEG = 14°` |
| `contrast_score` | 0.15 | Peak depth in grey levels, saturating at `CONTRAST_FULL = 60` |
| `margin_score` | 0.10 | Separation from the rival peak, saturating at `MARGIN_FULL_DEG = 30°` |
| `quality_factor` | 0.10 | `0.6 × blur_score + 0.4 × exposure_quality` of the gauge crop |

The result is then scaled by `0.85 + 0.15 × dial_confidence`, so a dial located
from profile geometry rather than from the image scores lower.

**Display**: `0.6 × stroke_score + 0.4 × coverage_score` when lit; a uniformly
dark window scores `0.5 + 0.5 × (1 − min(p99/110, 1))`, floored at 0.5, because
darkness there *is* the evidence.

**Switch**: `0.6 × layout_score + 0.4 × angle_score`, capped at 0.35 when the
lever is aligned with neither position.

### 3.7 The shape check that stops a confident wrong reading

The first gauge implementation reported **28 PSI for a true 87 PSI at
confidence 0.72**. When the dial centre is wrong — a rotated or
perspective-distorted frame whose circle Hough could not find — the radial scan
from a displaced centre still produces a peak, and the original confidence
formula liked it. A confidently wrong pressure reading is the worst possible
output for a reliability tool, so a peak must now survive two further tests:

- **`coverage`** — the share of the sampled ray on the needle's side of the
  midpoint between the ray and the dial. A real needle passes through the whole
  band; a ray from a displaced centre crosses the bezel and is half dial-face.
  Below `COVERAGE_FLOOR = 0.60` the reading is withheld.
- **`width_deg`** — the angular full width at half maximum. A needle is a few
  degrees wide; a misplaced-centre artefact is a smear. Above
  `WIDTH_BAD_DEG = 14°` the reading is withheld.

Two further rules complete the gate:

- **`REPORT_FLOOR = 0.50`** — no value is published below this confidence. The
  measured value is discarded and the state becomes `UNKNOWN`; the reason is
  written into `notes`. The criteria and raw geometry are still returned in
  `details` so the refusal itself is auditable.
- **`SWEEP_TOLERANCE_DEG = 3.0`** — a reading within 3° beyond the printed scale
  is clamped to the endpoint; beyond that the needle is genuinely off-scale and
  the value is withheld. This exists because sub-step refinement placed a
  legitimate 0 PSI reading 0.4° outside a sweep starting at −135°, and refusing
  it was pedantry rather than safety.

Measured outcome: gauge mean absolute error **0.4724 PSI** over 112 published
readings, with a **0.9 % wrong-value escape rate** — one reading, listed by name
in `docs/evaluation/results.md`. Before the shape check the escape rate was not
measurable because the failure was invisible.

### 3.8 Quality scoring

Defined in `app/vision/quality.py` and thresholded in `Settings`:

- **blur_score** — `var(Laplacian(gray)) / std(gray)²`, divided by
  `BLUR_REFERENCE = 0.0022` and clipped to 0..1. Dividing by the image's own
  standard deviation makes the metric respond to *detail* rather than to
  contrast, so a low-contrast but sharp frame is not mistaken for a blurry one.
  Frame threshold `blur_threshold = 0.35`.
- **exposure_quality** — starts at 1.0 and subtracts penalties for the fraction
  of pixels clipped at each end (`≤ 8`, `≥ 247`) and for mean luma away from
  mid-grey.
- **resolution_sufficient** — the frame needs a 480 px short edge; a component
  crop needs `min_region_short_edge = 24` px and `min_region_pixels = 400`.
  A crop is judged against the crop bound deliberately: judged against the frame
  rule, every 140×90 px indicator window would be flagged as too small to read.

`assess()` returns a reason string for every failed test, and the engine rolls
the region results up into a frame-level `requires_new_view` naming the
components that need a better view.

### 3.9 Change detection

`app/vision/change.py` uses two layers. The **structured diff** compares
measurements component by component in engineering units — indicator state
transitions carry a severity from a documented table (GREEN→RED is HIGH,
OFF→RED is HIGH, RED→GREEN is INFO), gauge changes report the delta and escalate
to CRITICAL when a reading crosses its configured warning threshold, and switch
position changes are MEDIUM. The **pixel diff** (`cv2.absdiff`) is reported as
context only: a pixel difference cannot say whether a red lamp is a warning or a
reflection.

### 3.10 Annotation

`app/vision/annotate.py` draws region boxes coloured by state, the dial circle
and a needle arrow, indicator circles, a header with the OpenCV version and
image id, a footer with blur/exposure/resolution, and a reinspection banner when
the frame needs a new view. Annotations are produced by the vision engine rather
than by the frontend, so the picture a user sees is drawn from the same numbers
the agent reasoned over. Originals are never modified.

---

## 4. Provenance

`Measurement.provenance` is one of four values and the distinction is part of
the type, not a convention:

| Value | Meaning |
|---|---|
| `measured` | Produced by OpenCV from pixels. Treated as fact about the image. |
| `inferred` | A model's interpretation. Tagged as such wherever it appears. |
| `user_reported` | Stated by the user; not verified visually. |
| `unknown` | Not established. |

**The rule: a model never overwrites a measurement.** The vision tools return
measurements; the model's job is to decide whether the evidence is sufficient,
not to produce values. When the model answers in prose instead of calling a
tool, the loop records it as an `Assessment` with `provenance: inferred` and
says so in the timeline ("Model response (inferred, no tool call)"). The gauge
path enforces the converse too: an unmeasurable needle produces no number at all
rather than a low-confidence guess.

---

## 5. The agent

### 5.1 Tools

Eleven tools in `app/agent/tools.py`, each a class with a Pydantic `Arguments`
model, a JSON schema for the model, and an async `run`. Arguments are validated
from untrusted model output *before* anything executes.

| Tool | Returns |
|---|---|
| `inspect_panel` | Every configured measurement in one pass, plus the detected panel box |
| `inspect_region` | One named region with its own quality assessment |
| `read_gauge` | Value, unit, confidence, the criteria behind it, and `readable` |
| `detect_indicator` | State, confidence and HSV criteria |
| `check_image_quality` | Blur/exposure/resolution for a frame or a region |
| `compare_observations` | Structured change report with per-change severity |
| `request_new_view` | Records a request for the user, with a specific instruction |
| `record_diagnosis` | Summary, confidence, next step, user-facing message |
| `create_incident` | Raises an incident; severity is validated against the enum |
| `request_human_approval` | Escalates a consequential action |
| `ask_user` | Asks what visual evidence cannot answer |

`ToolContext` is deliberately small: the engine, the profile, the images, the
analyses so far, the ordered image ids, and five output fields the terminal
tools write. It exposes no actuation surface of any kind.

### 5.2 State machine

Thirteen states, one transition table in `app/agent/state.py`, and the loop
routes through it by breadth-first search for the shortest legal path — so the
loop cannot drift from the documented transitions.

```
CREATED ─▶ OBSERVING ─▶ ANALYZING ─▶ REASONING
                                       │
    ┌──────────────────────────────────┼──────────────────────────┐
    ▼                                  ▼                          ▼
NEEDS_MORE_EVIDENCE            ACTION_PROPOSED                DIAGNOSING
    │                                  │                          │
    ▼                                  ▼                          ▼
WAITING_FOR_USER              AWAITING_APPROVAL             (COMPLETED)
    │                                  │                          │
    ▼                                  ▼                          │
 REOBSERVING ─▶ ANALYZING        COMPLETED ◀──────────────────────┘
                                      │
                                      └─▶ REASONING (re-opened)
```

Three edges point back to `REASONING`, and each earns its place:

- `DIAGNOSING → REASONING` and `ACTION_PROPOSED → REASONING` — a recorded
  diagnosis is not necessarily the end. An abnormal measurement still has to
  become an incident and an approval request, and without these edges the loop
  could record a diagnosis and then have no legal way to act on it.
- `COMPLETED → REASONING` — re-opens a finished inspection when the user reports
  the problem is still present. "It is still not working" is new evidence, not a
  new case.

`FAILED` has one outgoing edge (`FAILED → OBSERVING`) and is deliberately **not**
in `TERMINAL_STATES`: a state the loop can retry is faulted, not ended. Only
`COMPLETED` and `CANCELLED` end an inspection. An earlier version had `FAILED` in
both places, which made the API's terminal-state reporting wrong.

### 5.3 Bounded execution

| Bound | Value | Where |
|---|---|---|
| Steps per run | `max_agent_steps = 8` | loop `while` condition |
| Tool calls per run | `max_tool_calls = 12` | loop `while` condition |
| Reinspection rounds | `max_reinspection_rounds = 2` | policy gate; counted from the persisted trace, so re-running after a new upload cannot reset the budget |
| Per-step timeout | `agent_step_timeout_seconds = 90` | `asyncio.wait_for` around both the model call and the tool call |

Repeated-failure guard: a deterministic decision that repeats a tool already
failed in the same run stops the loop and writes a timeline entry saying why,
rather than retrying a call that cannot succeed. A model-step failure degrades
the run to the deterministic policy and says so in the timeline instead of
pretending to have reasoned.

### 5.4 Two brains, one loop

- **Live mode** — Nebius selects the next tool; results are fed back as
  `role="tool"` messages; the chosen tool and the model's own summary are both
  written to the timeline.
- **Demo mode** — `app/agent/policy.py` selects, from the *same* measurements.
  It is a real policy over real evidence, not a replay: `decide()` reads the
  latest analysis, defers to each measurement's own `requires_reinspection` flag
  rather than re-deciding with its own threshold, and a healthy panel produces a
  completely different trace from a faulty one. Every value it acts on came from
  OpenCV; only the *timing* of the photographs in a scripted flow is scripted.
  Demo mode is labelled in the UI and in every timeline entry it produces.

The policy is also the degraded fallback: with no provider configured, or after a
model failure, the same loop continues in deterministic mode and the timeline
records why.

---

## 6. Persistence

SQLite via `app/storage/db.py`, WAL mode, foreign keys on. Nothing outside
`Repository` opens the database.

| Table | Contents |
|---|---|
| `inspections` | Id, mode, profile, state, problem statement, demo flag, incident id, assessment, pending request, outcome, resolved, step and tool-call counters, error, timestamps |
| `images` | Id, inspection, original name, content type, SHA-256, dimensions, stored key, annotated key, role, sequence, timestamp |
| `observations` | Id, inspection, image, the serialised `AnalysisResult`, timestamp |
| `timeline` | Auto-increment id, inspection, kind, title, detail, state, JSON data, timestamp |
| `tool_calls` | Auto-increment id, inspection, step, tool, arguments, ok, result, error, duration, source (`model` or `policy`), timestamp |
| `incidents` | Id, inspection, title, summary, severity, status, evidence image ids, measurements, proposed action, approval required, resolution note, timestamps |

Images are **not** in the database. `EvidenceStorage` (`LocalEvidenceStorage`
today) stores bytes at `<inspection_id>/<image_id><suffix>` and returns the key;
`_resolve()` resolves against the root and rejects anything that escapes it.
Metadata and blobs are separated so an object store can be substituted without a
schema change — see `docs/architecture/aws.md`.

---

## 7. Safety architecture

- **The approval gate is enforced in the data model.** `create_incident`
  defaults `requires_approval` to true, and the industrial trace stops in
  `AWAITING_APPROVAL`. There is no code path that reaches `COMPLETED` with a
  remediation recorded as approved except `/approve`, which is a human call.
- **Remediation is simulated and labelled.** The proposed action is stored and
  rendered inside a block headed `SIMULATED ACTION — REQUIRES APPROVAL`; the
  approval outcome text states that nothing was executed and that the panel is a
  mock. Nothing in the system sends a control signal anywhere.
- **No actuation surface.** `ToolContext` has no control, execute, shutdown or
  actuate member, and `backend/tests/test_safety.py` asserts that.
- **Untrusted input is validated before use.** Uploads pass a content-type
  allow-list, a 12 MiB size cap, decode validation, a 32 px minimum and a 40 M
  pixel cap. Captured errors become 415/422 responses, and a malformed file
  creates no image row.
- **Tool arguments are validated** from model output against Pydantic models
  before execution; a bad argument is a recorded tool failure, not an exception.
- **Bounded loops** (section 5.3) prevent a runaway agent.
- **Escalation over guessing.** The system is built to say "I could not read
  this" — `UNKNOWN` states, withheld values, reinspection requests — rather than
  to produce an unsupported answer.
- **Privacy.** Fixtures are synthetic and generated in-repo; there is no
  biometric identification and no person surveillance. Image retention is the
  local evidence directory, and the original upload is preserved unmodified for
  audit.

---

## 8. What is not built

Stated plainly, because the rest of this document is precise:

- **AWS.** Nothing is deployed, provisioned or benchmarked. No AWS account is
  used. See `docs/architecture/aws.md`.
- **Real-world photograph accuracy.** Every fixture is synthetic. The
  degradations in the evaluation exist to claw back some of that difference, and
  the limitation is recorded rather than hidden.
- **Digit interpretation by OpenCV.** The display measurement is lit/blank only.
- **Generic component discovery.** Regions are configured per equipment profile;
  automatic detection finds the panel but not which component is which.
- **Tool-failure recovery as a measured rate.** The paths are covered by tests
  and by the loop's repeated-failure guard, but no scripted scenario forces a
  failure, so `docs/evaluation/results.md` reports it as `null` with a reason.
- **The competition skills and MCP servers** named in `AGENTS.md` (`ponytail`,
  `headroom`, `diagram-design`, `nori`, `senior-swe`, `full-send`, `adhd`) are
  not installed in this workspace. Serena MCP, the `novgraph` skill and the
  Tavily skills are available and were used.
