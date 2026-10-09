# Demo narration

Provider: **ElevenLabs**, model `eleven_multilingual_v2`, voice **Alice**
(`Xb7hH8MSUJpSbSDYk0k2`) — British English, female.

The finished track is a **single uninterrupted take** of the whole script. Source of
truth: `videowright/videos/sightops-demo/audio/originals/voiceovers/v1/provider_script.md`.
The spoken audio and the written script are checked against each other by
`videowright/scripts/sync_audio.py`, which fails if they differ by even one word.

## Voice substitution

The brief asks for a young adult British female voice, which is **Beth**
(`zH7TN9vEZAsEway9xWev`, labels `british` / `female` / `young`). Beth is a *library*
voice, and library voices are refused over the API on the free tier:

```
HTTP 402 {"type":"payment_required","code":"paid_plan_required",
          "message":"Free users cannot use library voices via the API."}
```

This was re-tested against a second free-tier key and refused identically, so it is a
plan restriction rather than an account problem. The narration therefore uses Alice, a
**premade** British female voice the free tier does allow, listed by the account for
the `informative_educational` use case.

Alice is middle-aged rather than young: that is the one deviation from the brief's voice
description. `VOICE_ID` overrides it, so recording with Beth is a one-line change once
a paid plan is available:

```bash
VOICE_ID=zH7TN9vEZAsEway9xWev bash generate.sh
```

## Character budget

The free tier allows 10,000 characters per period, and the alignment it returns is
what the video's reveals are timed to, so the narration cannot be patched with a
different engine without losing the timing.

| | |
|---|---|
| First key | exhausted: 9,975 of 10,000 used, and a full re-render needed 4,427 more |
| Second key (supplied afterwards) | fresh 10,000 |
| Final recording | 4,140 characters, one pass; 8,485 of 10,000 used, 1,515 remaining |

An earlier revision of the script had to be edited after the first key was exhausted.
That edit was made by speaking only the changed blocks and splicing them into the
existing recording (`videowright/scripts/resplice_voiceover.py`), and the first splice
cut 22 words out of the diagnosis block. With a fresh key the whole script was
re-recorded in one pass instead, which removed both the splice and the damage.

`resplice_voiceover.py` is kept because the constraint is a property of the plan rather
than of that one day: it supports `--replace <blocks>` (speak only what changed and
splice it in at the silence between blocks) and `--drop-words <start:end>` (excise a
word range without spending anything). Both keep `timing.json` consistent with
`provider_script.md`, and `sync_audio.py` still refuses to run if they disagree.

## Blocks

| # | Segment | Spoken length | Cue phrase for the first reveal |
|---|---|---|---|
| 1 | `title` | 19.7 s | "it does not" |
| 2 | `problem` | 26.9 s | "SightOps turns" |
| 3 | `vision` | 37.7 s | "Perspective is detected", "A gauge reading" |
| 4 | `uncertainty` | 26.0 s | "A confident wrong" |
| 5 | `active` | 28.2 s | "The agent compares", "The inspection pauses" |
| 6 | `remeasure` | 28.3 s | "The gauge reads", "The agent diffs" |
| 7 | `diagnosis` | 25.1 s | "Every claim" |
| 8 | `approval` | 30.8 s | "Consequential actions", "A human decides" |
| 9 | `evaluation` | 35.3 s | "On the gauge", "the agent completes" |
| 10 | `outro` | 23.6 s | "It is open source" |

Total video length: **4:41** (16,885 frames at 60 fps), inside the 5-minute ceiling and
inside the 4–4.5 minute target.

## Accuracy of the spoken claims

Each factual claim in the narration is traceable to a measurement:

| Claim | Source |
|---|---|
| gauge 83.7 PSI at 57% confidence, two of four components below the floor | demo observation 1: `83.68` at `0.5669`; quality reason *"2 of 4 components need a better view: pressure_gauge_01 (57%); status_led_01 (52%)"* |
| gauge 87.2 PSI at 96% confidence, above the 75 PSI threshold | demo observation 2: `87.16` at `0.9589`, profile limit 75 PSI |
| confidence climbing from 0.57 to 0.96 | the two observations above |
| the request wording | the stored `request_new_view` instruction, verbatim |
| 0.47 PSI mean absolute error, 112 published, 24 refused | `docs/evaluation/results.md` |
| wrong-value escape rate under 1% | 0.9% (1 of 112), same document |
| better than 98% indicator precision and recall | 0.9861 / 0.9853, same document |
| about 22 ms per frame | the running application's reported per-observation latency (13–34 ms across runs) |

Two claims were deliberately removed during writing because the measurement did not
support them: that the first frame was too blurred to measure (its blur score is `1.0`
— the frame is sharp, it is the gauge confidence that is low), and that the gauge value
was withheld (83.68 was published, because 0.5669 clears the 0.50 reporting floor).
