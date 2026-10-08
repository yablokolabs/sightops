# SightOps web client

React + TypeScript + Tailwind single-page application for SightOps.

## Running

The API must be running first (see `backend/`). Then:

```bash
cp ../SightOps.png public/SightOps.png   # the official logo, served at /SightOps.png
npm install
npm run dev                              # http://localhost:5173
```

Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`, so the browser only
ever talks to one origin. Point the proxy somewhere else with
`SIGHTOPS_BACKEND=http://host:port npm run dev`.

## Checks

```bash
npm run typecheck   # tsc --noEmit
npm run build       # typecheck, then a production bundle in dist/
npm run preview     # serve the built bundle on :4173
```

## Structure

| Path | What lives there |
|---|---|
| `src/lib/types.ts` | Typed mirror of the backend Pydantic models, in snake_case. |
| `src/lib/api.ts` | The only place that calls `fetch`; turns error payloads into `ApiError`. |
| `src/lib/format.ts` | Display formatting: values with units, provenance badges, state colours. |
| `src/hooks/` | `useAsync` (fetch state), `useInspection` (one inspection plus its mutations), `useVoice` (ElevenLabs playback). |
| `src/components/` | Header, evidence viewer, measurement table, agent timeline, assessment and approval panels, composer. |
| `src/routes/` | Landing, intake, workspace, history, incidents, system status. |

## Notes on behaviour

- **Nothing is faked.** Every control calls a real endpoint; there are no
  placeholder buttons.
- **Provenance is shown.** A measurement tagged `measured` came from OpenCV on
  that image; `inferred` is interpretation. The UI never presents one as the
  other.
- **Demo mode is labelled.** A demo inspection shows a banner and every
  deterministic timeline entry carries a `DEMO MODE` chip.
- **Voice is optional.** If the provider is unconfigured or fails, the audio
  controls report it and the written guidance is unaffected.
- **Approval is a gate.** The simulated remediation panel is visually distinct
  and says plainly that no machinery is being controlled.
