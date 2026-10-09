# Provider Script

> Provider: ElevenLabs v2 (eleven_multilingual_v2)
> Voice: Alice (Xb7hH8MSUJpSbSDYk0k2), British English, female
> Style notes: Clear technical explainer. Numbers, units and state names are read as
> written; the alignment keeps the written characters, so `87.2`, `PSI` and `OpenCV`
> stay legible in the transcript.
> Voice substitution: the brief asks for a young adult British female voice, which is
> Beth (zH7TN9vEZAsEway9xWev). Beth is a library voice, and library voices are refused
> over the API on the free tier with `HTTP 402 paid_plan_required`, so the narration
> uses Alice — the closest premade British female voice. See `demo/docs/narration.md`.

---

SightOps is an agentic visual reliability engineer. You give it a photograph of a machine; it measures what the image actually shows with OpenCV, reasons about what it can and cannot see, and decides what still needs to be inspected. And critically, it does not guess.

<break time="0.6s" />

The project began with a phone call about a broken dishwasher. A photograph of a control panel is easy to take and hard to read from a distance, and the person on the other end of that call could not tell which light was on. SightOps turns that photograph into evidence: what is lit and what is blank, where a needle points, how sharp and how well exposed the frame is, and how much of all of that you should actually trust.

<break time="0.6s" />

Every measurement is real computer vision, not a language model's impression. Perspective is detected and corrected, the panel is located, blur and exposure are scored, and each region of interest is rectified. A gauge reading comes from a radial scan across the dial, with needle shape validation. A lamp is classified by hue segmentation and peak brightness, a switch from the angle of its lever, and a display from its stroke level. When the vision model does speak, its answer is labelled as inferred and never overwrites a measured value.

<break time="0.6s" />

Every measurement carries a confidence, and the agent is allowed to distrust one. On the first photograph the gauge came back at 83.7 PSI with only 57 percent confidence, and two of the four components sat below the floor. So SightOps marked the frame as needing a better view, and wrote down why. A confident wrong pressure reading is far worse than no reading at all.

<break time="0.6s" />

This is the part that matters most. The agent compares image quality and measurements across observations, decides that the gauge cannot be trusted from this angle, and asks for a better photograph. The inspection pauses in a waiting state, with a specific request rather than a vague shrug: re-image the gauge square-on, filling most of the frame, with diffuse light and no specular reflection across the dial.

<break time="0.6s" />

A new photograph arrives, and this time the view is clean. The gauge reads 87.2 PSI, above the 75 PSI warning threshold, at 96 percent confidence. The agent diffs the two observations, sees the frame stop asking for a better view and the confidence on the gauge climb from 0.57 to 0.96, and replaces its earlier uncertainty with a measurement it can defend.

<break time="0.6s" />

That measurement is recorded as a diagnosis, with its evidence attached: the region ids, the values, the confidences, and the annotated image they came from. An incident is raised and a remediation is proposed. Every claim in the trace is traceable to a number that OpenCV produced, and to an image that a person can open and check for themselves.

<break time="0.6s" />

Then SightOps stops. Consequential actions require a person, so the agent requests approval and waits for it. In this demonstration the proposed action is simulated, and the interface says so plainly. Nothing is switched, no valve is turned, and no safety interlock is ever bypassed, because a troubleshooting assistant that can reach out and touch machinery is a hazard, not a product. A human decides what happens next.

<break time="0.6s" />

The vision pipeline is measured on a reproducible fixture set with exact ground truth, across perspective, glare, blur, noise and resolution. On the gauge, the mean absolute error is under half a PSI, and fewer than one in a hundred published readings is wrong by more than a few PSI. Indicators are classified at better than 98 percent precision and recall. A frame is analysed in about 22 milliseconds on a CPU, and the agent completes every scripted task inside its bounds.

<break time="0.6s" />

SightOps runs on a single CPU machine, with a real OpenCV 5 pipeline, a bounded agent loop, an approval gate, and a complete audit trail. It is open source and a working product rather than a prototype. You take a photograph. It measures, it reasons, it asks, and it acts safely. See. Diagnose. Act.
