/**
 * Copies the captured application screenshots into the video project's assets.
 *
 * The scenes import their images from `videos/sightops-demo/assets/`, while
 * `scripts/capture_app_screens.mjs` writes to `demo/screenshots/`. This is the
 * step in between: it renames each capture to the name the scene imports, so the
 * assets a render uses are always the screenshots the README shows.
 *
 *   node scripts/sync_screens_to_assets.mjs
 *
 * Exits non-zero if a source capture is missing, so a render cannot silently use
 * last week's image for one of the panels.
 */

import { copyFileSync, existsSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = path.resolve(scriptDir, "../../screenshots");
const TARGET = path.resolve(scriptDir, "../videos/sightops-demo/assets");

/** capture name (without extension) -> asset name the scenes import. */
const MAPPING = {
  "01-landing": "landing.png",
  "02-industrial-intake": "industrial-intake.png",
  "03-industrial-observation-1": "observation-1.png",
  "04-industrial-observation-1-measurements": "measurements-1.png",
  "05-industrial-observation-2": "observation-2.png",
  "06-industrial-approval": "approval.png",
  "07-industrial-completed": "completed.png",
  "09-home-observation-1": "home-observation-1.png",
  "12-system-status": "system-status.png",
  "evidence-1-annotated": "evidence-1.png",
  "evidence-2-annotated": "evidence-2.png",
};

// sightops-logo.png is a brand asset, not a capture, so it is not in the mapping.

let failed = false;
let copied = 0;

for (const [capture, asset] of Object.entries(MAPPING)) {
  const from = path.join(SOURCE, `${capture}.png`);
  if (!existsSync(from)) {
    console.error(`missing capture: ${from}`);
    failed = true;
    continue;
  }
  const to = path.join(TARGET, asset);
  copyFileSync(from, to);
  console.log(`${capture}.png  ->  ${asset}  ${statSync(to).size} bytes`);
  copied += 1;
}

if (failed) {
  console.error(
    `\n${Object.keys(MAPPING).length - copied} capture(s) missing. ` +
      "Run `npm run screens` first, against a running backend and client.",
  );
  process.exit(1);
}

console.log(`\n${copied} assets refreshed in ${TARGET}`);
