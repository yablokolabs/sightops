/**
 * Captures the real SightOps application for the README and the demo video.
 *
 * Every image here is the application's own pixels, served by the built client
 * and measured by the running backend — the same components, labels and numbers a
 * user sees. Nothing is mocked up: the script starts the scripted demonstration
 * flows, waits for the agent to finish each turn, and screenshots the result, so
 * a screenshot cannot drift away from what the app actually renders.
 *
 *   node scripts/capture_app_screens.mjs [outDir]
 *
 * Environment:
 *   SIGHTOPS_WEB_BASE   page origin, default http://127.0.0.1:4173
 *
 * Needs the backend on 127.0.0.1:8000 and the client preview server (which
 * proxies /api and /health) on 4173. Both are started by demo/README.md.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(process.argv[2] ?? path.join(scriptDir, "../../screenshots"));
const BASE = process.env.SIGHTOPS_WEB_BASE ?? "http://127.0.0.1:4173";

// 1600x900 is 16:9, so a viewport shot drops into a 1920x1080 frame without
// letterboxing, and is still wide enough for the three-column workspace.
const VIEWPORT = { width: 1600, height: 900 };

mkdirSync(OUT, { recursive: true });

const state = {
  counts: { viewport: 0, fullpage: 0 },
  bytes: {},
};

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: VIEWPORT,
  deviceScaleFactor: 2,
  colorScheme: "light",
  reducedMotion: "reduce",
});
const page = await context.newPage();

page.on("console", (message) => {
  if (message.type() === "error") console.log("[page error]", message.text().slice(0, 300));
});
page.on("pageerror", (error) => console.log("[page exception]", String(error).slice(0, 300)));

/**
 * Screenshot the viewport, and report what is on screen.
 *
 * Full-page variants are opt-in with ``SIGHTOPS_CAPTURE_FULLPAGE=1``. They are
 * three to seven times the bytes of the viewport shot, and neither the README nor
 * the video uses them: the frame is 16:9, so a taller image would be letterboxed
 * anyway. They are kept available for auditing anything below the fold.
 */
async function shot(name, { fullPage = process.env.SIGHTOPS_CAPTURE_FULLPAGE === "1" } = {}) {
  const viewportPath = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: viewportPath });
  state.counts.viewport += 1;

  if (fullPage) {
    const fullPath = path.join(OUT, `${name}.full.png`);
    await page.screenshot({ path: fullPath, fullPage: true });
    state.counts.fullpage += 1;
  }

  const text = (await page.locator("body").innerText()).replace(/\s+/g, " ").trim();
  console.log(`${name}  ->  ${text.slice(0, 220)}`);
}

/** Wait for a visible control whose text matches, then click it. */
async function click(name, timeout = 30_000) {
  const target = page.getByRole("button", { name }).first();
  await target.waitFor({ state: "visible", timeout });
  await target.click();
}

/**
 * Wait until the page body contains one of `needles`, i.e. the agent turn
 * finished. Passing several accepted states keeps the script working whichever
 * way a flow ends (the industrial flow pauses for approval, the home flow may
 * simply wait for the user, and a clean panel can finish outright).
 */
async function waitForText(needles, timeout = 120_000) {
  const values = Array.isArray(needles) ? needles : [needles];
  await page.waitForFunction(
    (list) => list.some((value) => document.body.innerText.includes(value)),
    values,
    { timeout, polling: 250 },
  );
}

const agentFinished = ["Waiting for you", "Awaiting your approval", "Completed"];

/**
 * Screenshot one Panel by its title.
 *
 * The workspace scrolls inside its own container, so a viewport shot of a panel
 * further down a column can come out identical to the shot above it. Capturing
 * the panel element itself makes the measurement table legible whatever the
 * window height happens to be.
 */
async function shotPanel(name, panelTitle) {
  const panel = page.locator("section", { hasText: panelTitle }).first();
  await panel.waitFor({ state: "visible", timeout: 15_000 });
  await panel.screenshot({ path: path.join(OUT, `${name}.png`) });
  state.counts.viewport += 1;
  console.log(`${name}  ->  panel "${panelTitle}" element screenshot`);
}

async function scrollTo(text) {
  const target = page.getByText(text, { exact: false }).first();
  try {
    await target.scrollIntoViewIfNeeded({ timeout: 5_000 });
  } catch {
    console.log(`(could not scroll to "${text}")`);
  }
  await page.waitForTimeout(300);
}

/** Save a response body (the annotated evidence PNG) to the screenshots folder. */
async function saveEvidence(inspectionId, imageId, name, annotated) {
  const url = `/api/inspections/${inspectionId}/evidence/${imageId}${annotated ? "?annotated=true" : ""}`;
  const response = await page.request.get(`${BASE}${url}`);
  if (!response.ok()) {
    console.log(`${name}: evidence fetch returned ${response.status()}`);
    return;
  }
  const body = await response.body();
  writeFileSync(path.join(OUT, `${name}.png`), body);
  state.bytes[name] = body.length;
  console.log(`${name}  ->  ${body.length} bytes (${response.headers()["content-type"]})`);
}

// ---------------------------------------------------------------- landing ----
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await page.waitForTimeout(800);
await shot("01-landing");

// ------------------------------------------------- industrial intake form ----
await page.goto(`${BASE}/industrial`, { waitUntil: "networkidle" });
await page.waitForTimeout(500);
await shot("02-industrial-intake");

// ---------------------------- observation 1: the gauge cannot be measured ---
await click(/Start the pump-station demonstration/i);
await waitForText(agentFinished);
await page.waitForTimeout(1200);
await shot("03-industrial-observation-1");

// The evidence and the measurements side by side, without the page scrolled.
const inspection1 = await (
  await page.request.get(`${BASE}/api/inspections/${await currentInspectionId(page)}`)
).json();
await saveEvidence(inspection1.id, newestImageId(inspection1), "evidence-1-annotated", true);

await shotPanel("04-industrial-observation-1-measurements", "Measurement detail");

// --------------------- observation 2: the gauge now measures a real value ---
await page.evaluate(() => window.scrollTo(0, 0));
await click(/Run next scripted observation/i);
await waitForText(agentFinished);
await page.waitForTimeout(1500);
await shot("05-industrial-observation-2");

const inspection2 = await (
  await page.request.get(`${BASE}/api/inspections/${inspection1.id}`)
).json();
await saveEvidence(inspection2.id, newestImageId(inspection2), "evidence-2-annotated", true);

await scrollTo("Simulated action");
await shot("06-industrial-approval");

// ------------------------------------------------------- human approval -----
await click(/Approve simulated action/i);
await page.waitForTimeout(2500);
await shot("07-industrial-completed");

// --------------------------------------------------------- home mode --------
await page.goto(`${BASE}/home`, { waitUntil: "networkidle" });
await page.waitForTimeout(500);
await shot("08-home-intake");

await click(/Start the dishwasher demonstration/i);
await waitForText(agentFinished);
await page.waitForTimeout(1200);
await shot("09-home-observation-1");

// ------------------------------------------------- history and incidents ----
await page.goto(`${BASE}/inspections`, { waitUntil: "networkidle" });
await page.waitForTimeout(800);
await shot("10-inspection-history");

await page.goto(`${BASE}/incidents`, { waitUntil: "networkidle" });
await page.waitForTimeout(800);
await shot("11-incidents");

await page.goto(`${BASE}/system`, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);
await shot("12-system-status");

await browser.close();

console.log(
  `\nwrote ${state.counts.viewport} viewport + ${state.counts.fullpage} full-page screenshots to ${OUT}`,
);
for (const [name, bytes] of Object.entries(state.bytes)) console.log(`  ${name}.png  ${bytes} bytes`);

/** The inspection id the workspace is showing, read from the URL. */
async function currentInspectionId(currentPage) {
  const match = /\/inspections\/([0-9a-f]+)/.exec(currentPage.url());
  if (!match) throw new Error(`not on an inspection page: ${currentPage.url()}`);
  return match[1];
}

/** The image id of the most recent observation, which is the frame to annotate. */
function newestImageId(inspection) {
  const observations = inspection.observations ?? [];
  if (observations.length === 0) throw new Error("the inspection has no observations");
  return observations[observations.length - 1].image_id;
}
