# SightOps demo assets

Everything in this folder is produced from the real application. Nothing here is a
mock-up, and the scripts that build it are committed next to the output.

```
screenshots/          captured from the running app by videowright/scripts/capture_app_screens.mjs
videos/sightops-demo.mp4   the rendered demonstration (4:41, 1920x1080, H.264)
subtitles/            WebVTT subtitles timed from the narration's own word alignment
videowright/          the VideoWright project that renders the video
docs/                 storyboard, narration notes and transcript
```

## The video

`videos/sightops-demo.mp4` is a 4-minute-41-second walkthrough with narration. It is rendered
frame-by-frame from the VideoWright project in `videowright/`, which uses the real
SightOps screenshots as its visual evidence.

The narration is one continuous voice track. Every scene change and every on-screen
reveal is cued to the spoken words by `videowright/scripts/sync_audio.py`, which
converts the provider's per-character alignment into segment-relative frame times.
Nothing is hand-timed.

### What is real and what is simulated

- The **screen content** is real: the screenshots are the running application, and
  every measurement, confidence and state name on screen was produced by it.
- The **equipment** is simulated. The panels are generated fixtures and the proposed
  shutdown is a simulated action that requires approval. The video says so on screen.
- The **numbers** in the evaluation scene come from `docs/evaluation/results.md`,
  except the frame latency, which is what the running application reports per
  observation. The scene labels the two sources separately.

## Regenerating it

Prerequisites: Docker (or a running backend and client), Node 22, Python 3, `ffmpeg`,
and `ELEVENLABS_API_KEY` in the environment for the narration step.

```bash
# 1. capture the application screenshots (needs backend :8000 and client :4173)
cd demo/videowright && npm install && npm run screens

# 1b. copy the refreshed captures into the video project's assets
cd demo/videowright && npm run assets

# 2. narration -> timing
cd videos/sightops-demo/audio/originals/voiceovers/v1
bash generate.sh                  # writes audio.mp3 + timing.json
cd ../../../../.. && python3 scripts/sync_audio.py   # writes track.ts + segment advances

# 3. render
npx videowright render sightops-demo --output ../videos/sightops-demo.mp4

# 4. subtitles
python3 scripts/build_subtitles.py
```

`npm install` runs `scripts/apply-videowright-fix.mjs`, which writes the library
re-export modules that the published `videowright@0.1.1` tarball omits. Without it the
render fails with `page.waitForFunction: Timeout 30000ms exceeded`.

`npm run screens` writes one 16:9 viewport shot per screen. Full-page variants are
opt-in with `SIGHTOPS_CAPTURE_FULLPAGE=1`; they are three to seven times the bytes and
nothing here uses them, because a frame that is taller than 16:9 would be letterboxed
in the video anyway.

`npm run assets` renames the captures to the names the scenes import, and fails rather
than falling back to an older image if a capture is missing.

Before a render, run the layout check as well, because it is the only way to see a panel
that overflows the frame without waiting half an hour for the video:

```bash
npx videowright dev --port 5199          # in one shell
npm run layout                           # in another; exits non-zero on overflow
```

## Voice

The brief asks for a young adult British female voice: **Beth**
(`zH7TN9vEZAsEway9xWev`). Beth is a *library* voice, and this ElevenLabs account is on
the free tier, which refuses library voices over the API:

```
HTTP 402 paid_plan_required
Free users cannot use library voices via the API.
```

The narration therefore uses **Alice** (`Xb7hH8MSUJpSbSDYk0k2`), the closest *premade*
British female voice on the account, with `eleven_multilingual_v2`. This is a
documented substitution, not an oversight; see `docs/narration.md` for the full
record, including the character budget and the one repair that was needed.

## Repair tooling

`videowright/scripts/resplice_voiceover.py` exists because the free tier has a fixed
character allowance (10,000) and re-running `generate.sh` speaks the whole script
again, so once the allowance is spent an edit cannot be recorded at all. It can:

- `--replace 4,5,6` — speak only the blocks that changed and splice them into the
  existing recording at the silence between blocks, and
- `--drop-words 398:400` — excise a word range from the recording and the timing
  without spending anything.

Both keep `timing.json` consistent with `provider_script.md`, and `sync_audio.py`
still refuses to run if the recording and the written script disagree. The finished
track did **not** need either: it is one uninterrupted take. See `docs/narration.md`.

`scripts/check_scene_layout.mjs` plays the timeline in the dev server and measures the
live DOM, reporting any settled element that crosses an edge of the 1920×1080 frame.
It is worth running before a render, which takes about half an hour and is the only
other way to see a panel that overflows.

## Screenshots

`npm run screens` drives the built client on `http://127.0.0.1:4173` with Playwright,
starts each scripted demonstration, waits for the agent to finish its turn, and
captures the result — plus the annotated evidence PNGs fetched from the API. Because
the images come from the app itself, they cannot describe a state the app never
reaches.
