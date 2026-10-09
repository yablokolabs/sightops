# SightOps — Evaluation Methodology

This document defines every metric SightOps reports and how it is obtained.
`backend/scripts/evaluate.py` produces `results.json` and `results.md`; the
markdown is rendered by the script itself, so the published numbers are never
copied by hand.

```bash
cd backend
python3 scripts/evaluate.py --out ../docs/evaluation
```

## 1. Why the dataset is generated, not collected

Every fixture is drawn by `app/fixtures/generate_panels.py` from known
parameters. A gauge fixture knows its needle sits at 87.0 PSI because the
generator *drew* the needle at that angle.

This matters for the same reason a benchmark needs labels: if ground truth were
hand-annotated, the gauge error reported here would be measuring two things at
once — the vision engine and the annotator. Generated ground truth is exact, so
the absolute error is entirely attributable to the measurement.

The trade-off is stated plainly: synthetic panels are cleaner than a real
photograph. The degradations below exist to claw that back, and the limitation
is recorded in `docs/PROGRESS.md` rather than hidden.

## 2. Controlled variations

Each variation is applied to the finished panel, so it never moves a component
away from the region the profile declares.

| Variation | What it simulates | Implementation |
|---|---|---|
| `clean` | a good photograph | none |
| `sensor_noise` | a small sensor in low light | additive Gaussian, σ = 4 |
| `mild_blur`, `moderate_blur`, `strong_blur` | missed focus | Gaussian σ = 1.2 / 2.2 / 4.5 |
| `underexposed`, `overexposed` | wrong exposure | brightness ×0.42 / ×1.75 |
| `glare`, `heavy_glare` | a reflection across the panel | additive blurred disc, 0.55 / 0.85 |
| `low_resolution`, `very_low_resolution` | subject far away or a coarse sensor | resample down to 0.35 / 0.18 and back up |
| `perspective`, `strong_perspective` | photographed at an angle | projective warp, 0.07 / 0.20 |
| `rotation`, `strong_rotation` | camera roll | 4° / 11° |
| `occlusion_40`, `occlusion_80` | a hand, cable or bracket over the dial | opaque patch over 40 % / 80 % of the dial diameter |

Pressures: 0, 12.5, 28, 43.5, 61, 74.5, 88, 97 PSI — spanning both sides of the
75 PSI warning limit and both scale endpoints.

## 3. Computer-vision metrics

### Gauge absolute error
`|measured − true|` over published readings, reported as mean, median, 95th
percentile and maximum, in PSI and as a percentage of full scale (100 PSI).

### Refusal rate
The share of attempts where the engine published no value. SightOps withholds a
reading below `gauges.REPORT_FLOOR = 0.50` confidence, or when the needle fails
shape validation. A refusal is a correct outcome, not a failure: it is the
behaviour that stops the system reporting a number it cannot support.

### Wrong-value escape rate
**The metric that matters.** The share of *published* readings whose error
exceeds `WRONG_VALUE_TOLERANCE_PSI = 3.0`. It is measured against exact ground
truth and depends on no readability assumption. A reliability tool has to keep
this at zero; where it is not zero, `results.md` lists every escaping reading by
variation, true value, measured value, error and confidence.

### Indicator precision, recall and F1
Per state (RED, GREEN, AMBER, OFF) over every indicator region in every
variation, with macro averages. Both lamps on the industrial panel are counted,
so GREEN has a much larger support than the others; support is reported alongside
each figure so a small-sample class cannot hide behind a macro average.

### Display accuracy
Lit-versus-blank agreement. Digit or segment *interpretation* is not measured,
because OpenCV does not perform it in this build — see the limitation in
`results.md`, which lists every failure with the measurement that caused it.

### Switch accuracy
Agreement on the lever position (UP / DOWN / LEFT / RIGHT).

### ROI localisation success rate
The share of analyses where the configured region for the gauge resolved to a
box of at least 8×8 px fully inside the image. Regions are *configured* from the
equipment profile, so this measures that configuration and bounds handling are
sound — it is not a claim of generic component discovery. Automatic panel
detection is a separate, clearly-labelled capability
(`app.vision.regions.detect_panel`).

### Quality-gate detection rate and false-refusal rate
The gate is evaluated against a documented **analysis assumption**, stated as a
rule in `scripts/evaluate.py::unreadable_by_construction`: a frame is called
unreadable when the degradation destroys the needle's information — occlusion
above 0.40 of the dial diameter, brightness outside 0.50–1.50, blur σ above 4.0,
rotation above 8°, perspective above 0.12, or resolution scale below 0.30.

This is an assumption, not measured truth, and the results say so. Several
frames the rule calls unreadable are in fact measurable, which inflates the
missed-rejection count. The wrong-value escape rate is the figure to trust,
because it needs no such rule.

## 4. Agent metrics

Four scenarios are driven through the real bounded loop with the deterministic
policy, so no API spend is involved and the run is reproducible:

| Scenario | Expected behaviour |
|---|---|
| `industrial_fault_two_observations` | poor framing → request a better view; then a clean frame confirms the fault → incident → approval |
| `industrial_healthy_single_observation` | every component in range → diagnosis, no incident, no reinspection |
| `industrial_fault_clear_first_try` | the fault is legible immediately → no reinspection needed |
| `home_unpowered_dishwasher` | two observations, home mode → advice, never an incident |

- **Task success** — the inspection reached a state its evidence justifies, *and*
  requested a new view exactly when the evidence warranted it, *and* created an
  incident exactly when one was expected. All three conditions must hold.
- **Active-perception precision and recall** — the agent asking for another view
  is treated as a positive prediction of "the evidence is insufficient", with the
  scenario definition as ground truth. Precision is the share of requests that
  were necessary; recall the share of necessary requests that were made.
- **Escalation** — incidents created versus expected, plus incorrect and missed
  escalations.
- **Bounded execution** — asserted, not assumed: every run's tool-call and step
  counts are compared against `max_tool_calls` and `max_agent_steps`.
- **Tool-failure recovery** — reported as `null` with a reason. No scripted
  scenario forces a tool to fail, so it is not claimed as measured; the failure
  paths are covered by `backend/tests/test_tools.py` and the loop's
  repeated-failure guard.

## 5. Performance metrics

Thirty analyses of the same 1280×720 frame after three warm-up runs. Reported:
mean, median, p95 and maximum analysis latency; analyses per second; CPU seconds
consumed; CPU utilisation expressed as a percentage of one core; and peak
resident set size from `resource.getrusage`.

The frame and region configuration are the same as the accuracy runs, so the
latency figures describe the workload the accuracies were measured on. The
environment table records OpenCV and NumPy versions, CPU model and count, memory
and the absence of a GPU — no throughput claim is made for hardware other than
the machine reported.

## 6. What is deliberately not claimed

- **No AWS or COOL benchmark.** No AWS resource was provisioned, no Graviton
  instance was used, and COOL was not measured. `docs/benchmarks/cool-methodology.md`
  describes the intended method only.
- **No real-world photograph accuracy.** All fixtures are synthetic.
- **No digit interpretation accuracy.** The display test is lit/blank only.
- **No tool-failure-recovery rate.** Not exercised end to end; see above.
