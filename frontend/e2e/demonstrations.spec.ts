import { expect, test } from "@playwright/test";

/**
 * The two scripted demonstrations, driven through the interface.
 *
 * These are the end-to-end tests of the capability the project is built around, so
 * they assert on measurements rather than on prose: a run that produced the right
 * words over the wrong numbers would fail here.
 *
 * Nothing is mocked. The backend measures real generated panel images with OpenCV,
 * and the agent is the application's own agent, so what these tests prove is that the
 * whole path - upload, measure, decide, ask for a better view, measure again, record a
 * diagnosis, stop for approval - works in a browser.
 */

test.describe("industrial pump-station demonstration", () => {
  test("asks for a better view, then measures, diagnoses and stops for approval", async ({
    page,
  }) => {
    await page.goto("/industrial");

    const start = page.getByRole("button", { name: /Start the pump-station demonstration/i });
    await expect(start).toBeVisible();
    await start.click();

    // ---- Observation 1: the angled frame -------------------------------------
    // The warning lamp is measured confidently, the gauge is not, so the agent
    // publishes what it has and asks for a photograph it can measure.
    await expect(page.getByText("Waiting for you")).toBeVisible({ timeout: 180_000 });
    // `exact` because the same reading is quoted in the assessment, the timeline and
    // the persisted tool results, and this asserts on the measurement itself.
    await expect(page.getByText("83.68 PSI", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/SightOps needs a better view/i)).toBeVisible();
    await expect(page.getByText(/Target region:\s*pressure_gauge_01/i)).toBeVisible();

    // ---- Observation 2: the same panel, square on ----------------------------
    const next = page.getByRole("button", { name: /Run next scripted observation/i });
    await expect(next).toBeVisible();
    await next.click();

    await expect(page.getByText("Awaiting your approval")).toBeVisible({ timeout: 180_000 });
    await expect(page.getByText("87.16 PSI", { exact: true }).first()).toBeVisible();

    // The proposed action is labelled as simulated, and the interface offers a
    // decision rather than performing one.
    await expect(page.getByText(/simulated action/i).first()).toBeVisible();
    const approve = page.getByRole("button", { name: /Approve simulated action/i });
    await expect(approve).toBeVisible();
    await expect(page.getByRole("button", { name: /^Reject$/ })).toBeVisible();

    // ---- The human decision ---------------------------------------------------
    await approve.click();
    await expect(page.getByText("Completed").first()).toBeVisible({ timeout: 60_000 });
  });
});

test.describe("household dishwasher demonstration", () => {
  test("asks for a closer photograph and reports the second observation", async ({ page }) => {
    await page.goto("/home");

    const start = page.getByRole("button", { name: /Start the dishwasher demonstration/i });
    await expect(start).toBeVisible();
    await start.click();

    // Too far away to read, so the agent stops and says what to photograph instead.
    await expect(page.getByText("Waiting for you")).toBeVisible({ timeout: 180_000 });
    await expect(page.getByText(/SightOps needs a better view/i)).toBeVisible();

    const next = page.getByRole("button", { name: /Run next scripted observation/i });
    await expect(next).toBeVisible();
    await next.click();

    // The close-up is readable, so the display is now *classified* rather than left
    // unreadable, and the agent's own measurement summary carries the state into its
    // reasoning. That is the whole point of the second look.
    await expect(page.getByText(/display_01=LIT/).first()).toBeVisible({ timeout: 180_000 });
  });
});

test.describe("the interface states what it cannot do", () => {
  test("system status reports the real OpenCV version and no AWS integration", async ({ page }) => {
    await page.goto("/system");

    await expect(page.getByText("5.0.0").first()).toBeVisible();
    await expect(page.getByText(/NOT IMPLEMENTED/i).first()).toBeVisible();
  });
});
