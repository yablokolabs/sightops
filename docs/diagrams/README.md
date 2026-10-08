# SightOps Architecture Diagrams

Rendered, standalone SVG diagrams for the SightOps README, plus the generator
that produces them.

| File | Shows |
|---|---|
| `system-architecture.svg` | React client, FastAPI backend, OpenCV 5 vision engine, agent orchestration, local storage, and the external Nebius and ElevenLabs services behind a trust boundary, with AWS marked as planned and not deployed. |
| `agentic-vision-loop.svg` | The perception → measure → assess → reason → act loop, with the confidence gate that sends the agent back for another observation, and the bounds that keep the loop finite. |
| `active-perception-sequence.svg` | The two-observation industrial walkthrough: insufficient evidence, a reinspection request, a better photograph, a measured gauge, an incident and the human approval gate. |
| `deployment-architecture.svg` | The single existing Azure VM, its processes, storage and ports, outbound HTTPS to the external services, and the AWS region explicitly marked not deployed. |
| `inspection-state-machine.svg` | The thirteen inspection states with forward, return, failure and recovery transitions, generated from the same table the agent loop validates against. |

## Regenerating

```bash
cd docs/diagrams
python3 src/generate_diagrams.py --out .
```

The script uses only the Python standard library, so it needs no install. It
writes the five SVGs and then attempts PNG fallbacks via `rsvg-convert`,
`cairosvg` or `inkscape`, whichever is present:

```bash
sudo apt-get install -y librsvg2-bin   # provides rsvg-convert
```

If no rasteriser is available the script prints exactly which one it looked for
and skips the PNGs rather than failing silently. The SVGs are the committed
artefacts; the PNGs are a convenience for viewers that cannot render SVG.

## Palette

Sampled from the official `SightOps.png` logo so the diagrams match the product:

| Token | Hex | Use |
|---|---|---|
| Navy | `#051D35` | page surface, dark boxes |
| Navy 2 | `#053B6E` | secondary dark, borders |
| Blue | `#075CA7` | primary action, forward flow |
| Blue light | `#3B8FD4` | return and re-entry edges |
| Slate | `#3E4D5C` | body text |
| Mist | `#D4DADF` | hairlines, lifelines |
| Paper | `#F7F9FB` | diagram background |
| Amber | `#FF7A1A` | confidence gate, external boundary, plans |
| Green | `#2E9E5B` | sufficient evidence, recovery |
| Red | `#D13B3B` | failure, not-implemented |

## Notes on the sources

`src/generate_diagrams.py` is the editable source. It lays each diagram out by
hand rather than through a layout engine, and auto-fits every label to its box
using an estimated glyph advance, so text stays inside its container at GitHub
README width.

The SVGs have no external dependencies: no web fonts, no scripts, no images, no
`@import`. Each root element carries `<title>`, `<desc>`, `role="img"` and an
`aria-label`. The only `http` string in the output is the SVG namespace.

Nothing in these diagrams is aspirational. Components marked as implemented are
running on the Azure VM; the AWS region is deliberately drawn dashed and grey
and labelled NOT DEPLOYED / NOT PROVISIONED, because no AWS resource exists.
