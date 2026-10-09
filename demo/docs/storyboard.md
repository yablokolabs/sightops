# SightOps demo — storyboard

Ten scenes, 1920×1080 at 60 fps, 4:41 total. Scene order and durations match
`videowright/videos/sightops-demo/timeline.ts` and the advances written by
`scripts/sync_audio.py`; the timings below were read from that file, not estimated.

| # | Scene | In | Length | On screen | Spoken beat |
|---|---|---|---|---|---|
| 1 | `title` | 0:00 | 19.7 s | logo, wordmark, SEE / DIAGNOSE / ACT, then the promise: *"A confident wrong reading is worse than no reading. It does not guess."* | the project in one paragraph |
| 2 | `problem` | 0:20 | 26.9 s | the home troubleshooting workspace as a real screenshot; four kinds of evidence it extracts | the dishwasher phone call |
| 3 | `vision` | 0:47 | 37.7 s | the real Measurement detail panel; the pipeline table; then perspective correction and the provenance rule | every measurement is real CV, not a VLM impression |
| 4 | `uncertainty` | 1:24 | 26.0 s | the angled, glaring first frame; gauge 83.7 PSI at 0.57 confidence; the quality gate's own reason string | it reports a number it does not trust |
| 5 | `active` | 1:50 | 28.2 s | the loop bar moving Reason → Investigate; the names of all seven tool calls; then the reason and the verbatim request block with `WAITING_FOR_USER` | it asks for a better look |
| 6 | `remeasure` | 2:18 | 28.3 s | the clean second frame; gauge 87.2 PSI at 0.96, `HIGH`; the observation diff under the frame; then the conclusion | the second look produces the measurement |
| 7 | `diagnosis` | 2:47 | 25.1 s | the annotated panel; recorded findings; the auditability list | incident raised, every claim traceable |
| 8 | `approval` | 3:12 | 30.8 s | the incident and approval panel; `SIMULATED ACTION — REQUIRES APPROVAL`; what it will not do | it stops for a person |
| 9 | `evaluation` | 3:43 | 35.3 s | 0.47 PSI MAE, 112 published / 24 refused, 98.6% precision, 22 ms; honest failure modes; the state strip | measured, not claimed |
| 10 | `outro` | 4:18 | 23.6 s | logo, the stack, the closing promise | See. Diagnose. Act. |

## Narrative arc

The video is built around the one behaviour that distinguishes SightOps from a
classifier: **it gets a second look when the first one is not good enough.**

Scenes 1–3 establish what the system is and that its numbers come from pixels.
Scene 4 shows a disappointing first observation — a gauge reading the agent will not
stand behind. Scene 5 is the turn: the agent works out that it needs new evidence,
says exactly what to photograph, and waits. Scene 6 shows the payoff, with the
confidence climbing from 0.57 to 0.96 on a better frame. Scenes 7–8 show what happens
once the evidence is good, and where the system deliberately stops. Scenes 9–10
replace claims with measurements, and close.

## Rules the scenes follow

- **Real data only.** Every number on screen comes from a run recorded in
  `docs/evaluation/results.md`, from the demo trace, or from the running app's own
  per-observation latency. Nothing is illustrative.
- **Simulation is labelled.** The approval scene says the action is simulated.
- **Each scene fits its frame.** A scene holds only as much as 1080 lines can show with
  every reveal visible. `scripts/check_scene_layout.mjs` fails if two blocks overlap.
- **Screenshots, not mock-ups.** The framed images are the real application, captured
  by `scripts/capture_app_screens.mjs`.
- **One idea per scene.** Reveals are cued to the narration by word timing, so a panel
  arrives when it is being talked about.
