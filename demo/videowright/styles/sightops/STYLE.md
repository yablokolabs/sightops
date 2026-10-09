---
title: SightOps
slug: sightops
picker_description: 'Light technical workspace. Navy ink on mist, one blue accent, amber for caution — the product UI at 1080p.'
font_sources:
  - npm:@fontsource/inter (latin 400, 500, 600, 700)
  - npm:@fontsource/jetbrains-mono (latin 400, 500)
---

# Style: SightOps

## When to use

Videos about SightOps: the competition demonstration, walkthroughs, release notes.
The look comes from `SightOps.png` and from the application itself, so a screenshot
of the real UI sits on the background without a visible seam.

## Aesthetic rules

- **Colour.** Background `--color-bg` (mist, just off white). Text `--color-fg` (navy
  ink), with `--color-steel` and `--color-muted` for secondary text. Blue
  `--color-accent` marks one idea per scene: the active loop stage, the measured
  number, the thing that is correct. Amber `--color-warn` is a caution that needs a
  better look. Green `--color-good` is a healthy measurement; red `--color-bad` is a
  fault. Never a second accent colour.
- **Type.** Inter for headings and body, JetBrains Mono for measured values, region
  ids, state names, thresholds and anything that came from OpenCV or a log. The fonts
  are npm packages imported by `tokens.css`; `defineScene()` waits for them before a
  scene plays.
- **Sizes at 1080p.** Headline 72px or more, body 36px or more, mono 30px or more,
  small labels 24px or more. No text below 20px.
- **Layout.** One subject in each scene. Content uses the full width inside the safe
  area (`--safe-x`, `--safe-y`). Panels are white with a `--color-border` line and
  `--radius-lg` corners.
- **Real data only.** Every number, state name and threshold on screen comes from a
  real run: the committed evaluation in `docs/evaluation/results.md`, the screenshots
  in `demo/screenshots/`, and the actual demo trace. Do not invent a measurement, a
  confidence value or a benchmark.
- **Simulation is labelled.** Where the demonstration proposes an action, the scene
  says it is simulated. No scene implies SightOps operated machinery.
- **Glyphs.** The fonts are the latin subset. Do not type arrows or check marks as
  characters; draw them with CSS or inline SVG.

## Motion vocabulary

- Elements enter with opacity 0 to 1 and a 24px upward move, 500ms, easing
  `cubic-bezier(0.22, 1, 0.36, 1)`, with a 90ms stagger inside a group.
- Animation uses `element.animate()` only. The render clock does not drive CSS
  transitions or CSS keyframes.
- Each reveal that the narration cues is a beat behind `ctx.waitForNext()`.
- Scenes change with `fade`.

## Don'ts

- No bounce, no spin, no slide transitions between scenes.
- No looping animations: the render clock stops them after one iteration.
- No emoji. No fake UI: if a control is on screen it is a screenshot of the real one.
- No `rem`, `vw` or `vh` units: dev and render resolve them differently.
