/**
 * Guided exploration ("Explore as Analyst / Admin"). Runs against a live stack with EXPLORE_MODE_ENABLED=true;
 * skipped otherwise. No credentials are needed or used. Screenshots → e2e/screenshots/explore-*.png (git-ignored).
 */
import { expect as baseExpect, test, type Page } from "@playwright/test";

// Pages load real data from a live stack; allow for a busy server (e.g. while a backfill is processing).
const expect = baseExpect.configure({ timeout: 25_000 });

const IGNORED_CONSOLE = /tiles|basemaps|fonts|eox|cartocdn|Failed to load resource|WebGL/i;
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e/screenshots/explore-${name}.png` });

async function exploreEnabled(page: Page): Promise<boolean> {
  const r = await page.request.get("/api/v1/auth/demo");
  return r.ok() && (await r.json()).enabled === true;
}

function trackConsole(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error" && !IGNORED_CONSOLE.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function noHorizontalOverflow(page: Page, where: string) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over, `horizontal overflow on ${where}`).toBeLessThanOrEqual(1);
}

/** The tour card is fully inside the viewport. */
async function cardInViewport(page: Page, where: string) {
  const r = await page.locator(".tour-card").boundingBox();
  const vp = page.viewportSize()!;
  expect(r, `tour card on ${where}`).not.toBeNull();
  expect(r!.x, where).toBeGreaterThanOrEqual(-1);
  expect(r!.y, where).toBeGreaterThanOrEqual(-1);
  expect(r!.x + r!.width, where).toBeLessThanOrEqual(vp.width + 1);
  expect(r!.y + r!.height, where).toBeLessThanOrEqual(vp.height + 1);
}

/** The explanation must not cover most of what it explains (full-screen targets such as the map excepted). */
async function cardDoesNotHideTarget(page: Page, where: string) {
  const card = await page.locator(".tour-card").boundingBox();
  const spot = await page.locator(".tour-spotlight").boundingBox();
  const vp = page.viewportSize()!;
  if (!card || !spot) return;
  const visible = { x0: Math.max(spot.x, 0), y0: Math.max(spot.y, 0), x1: Math.min(spot.x + spot.width, vp.width), y1: Math.min(spot.y + spot.height, vp.height) };
  const area = Math.max(0, visible.x1 - visible.x0) * Math.max(0, visible.y1 - visible.y0);
  if (area === 0 || area > vp.width * vp.height * 0.5) return;
  const ix = Math.max(0, Math.min(visible.x1, card.x + card.width) - Math.max(visible.x0, card.x));
  const iy = Math.max(0, Math.min(visible.y1, card.y + card.height) - Math.max(visible.y0, card.y));
  expect((ix * iy) / area, `card covers the target on ${where}`).toBeLessThanOrEqual(0.5);
}

async function enter(page: Page, role: "analyst" | "admin") {
  await page.goto("/");
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await page.goto("/");
  await page.getByRole("button", { name: role === "admin" ? "Explore as Admin" : "Explore as Analyst", exact: true }).click();
  await expect(page.getByRole("region", { name: "Demo mode" })).toContainText(role === "admin" ? "Admin" : "Analyst", { timeout: 20_000 });
}

/** Walk every step with Next; returns [title, spotlighted] per step. */
async function walk(page: Page, label: string): Promise<[string, boolean][]> {
  const seen: [string, boolean][] = [];
  const card = page.locator(".tour-card");
  for (let i = 0; i < 40; i++) {
    const title = page.locator("#tour-step-title, #tour-done-title");
    await expect(title).toBeVisible({ timeout: 20_000 });
    if (await page.locator("#tour-done-title").count()) break;
    const progress = await card.locator(".tour-progress").textContent();
    const text = (await title.textContent()) ?? "";
    // Wait for the spotlight to settle on steps that have one (it follows the target each frame).
    await page.waitForTimeout(250);
    const lit = (await page.locator(".tour-spotlight").count()) > 0;
    seen.push([text, lit]);
    await shot(page, `${label.replace(/\s+/g, "-")}-${String(seen.length).padStart(2, "0")}`);
    await noHorizontalOverflow(page, `${label} · ${text}`);
    await cardInViewport(page, `${label} · ${text}`);
    if (lit) await cardDoesNotHideTarget(page, `${label} · ${text}`);
    expect(progress).toMatch(/^Step \d+ of \d+/);
    await card.getByRole("button", { name: /^(Next|Finish)$/ }).click();
  }
  await expect(page.locator("#tour-done-title")).toBeVisible();
  return seen;
}

test.describe("explore modes", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await exploreEnabled(page)), "EXPLORE_MODE_ENABLED is off on this stack");
  });

  test("login page keeps normal sign-in and offers both explore modes", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Explore without an account" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Explore as Analyst", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Explore as Admin", exact: true })).toBeVisible();
    await page.getByLabel("Email").fill("nobody@example.org");
    await page.getByLabel("Password").fill("wrong-password-123");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toContainText(/Invalid email or password/);
    await shot(page, "login");
  });

  test("desktop analyst tour: full walk, back, restart, skip, read-only, exit", async ({ page }) => {
    test.setTimeout(300_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    const errors = trackConsole(page);
    await enter(page, "analyst");
    await expect(page.locator("#tour-step-title")).toHaveText("Welcome to ThermalTrace", { timeout: 20_000 });
    await expect(page).toHaveURL(/\/overview$/);
    await shot(page, "analyst-01-welcome");

    // Next / Back
    await page.locator(".tour-card").getByRole("button", { name: "Next" }).click();
    await expect(page.locator("#tour-step-title")).toHaveText("A satellite sees heat, not causes");
    await page.locator(".tour-card").getByRole("button", { name: "Back" }).click();
    await expect(page.locator("#tour-step-title")).toHaveText("Welcome to ThermalTrace");

    // The search step opens real results; leaving the step must close them again.
    for (const title of ["A satellite sees heat, not causes", "Where the evidence comes from", "Events, not thousands of raw pixels", "Search across the platform"]) {
      await page.locator(".tour-card").getByRole("button", { name: "Next" }).click();
      await expect(page.locator("#tour-step-title")).toHaveText(title);
    }
    await expect(page.getByRole("combobox", { name: /Search events/ })).toHaveValue(/^TT-/);
    await page.locator(".tour-card").getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("combobox", { name: /Search events/ })).toHaveValue("");
    await page.getByRole("region", { name: "Demo mode" }).getByRole("button", { name: "Restart tour" }).click();

    const steps = await walk(page, "desktop analyst");
    test.info().annotations.push({ type: "analyst steps", description: steps.map(([t, l]) => `${l ? "●" : "○"} ${t}`).join(" | ") });
    expect(steps.length).toBe(19);
    expect(steps.filter(([, lit]) => lit).length, "spotlighted steps").toBeGreaterThanOrEqual(17);
    await shot(page, "analyst-done");

    // Restart from the completion card, then skip
    await page.getByRole("button", { name: "Restart analyst tour" }).click();
    await expect(page.locator("#tour-step-title")).toHaveText("Welcome to ThermalTrace");
    await page.locator(".tour-card").getByRole("button", { name: "Skip tour" }).click();
    await expect(page.locator(".tour-card")).toHaveCount(0);

    // Read-only: a review is refused by the server with a clear message
    await page.goto("/events");
    await page.locator("tbody tr").first().click();
    await expect(page.getByRole("heading", { name: "Analyst review" })).toBeVisible({ timeout: 20_000 });
    await page.getByRole("radio", { name: "Escalate" }).click();
    await page.getByRole("button", { name: "Record decision" }).click();
    await expect(page.getByText(/Changes are disabled in demo mode/).first()).toBeVisible();

    // Restart from the banner
    await page.getByRole("region", { name: "Demo mode" }).getByRole("button", { name: "Restart tour" }).click();
    await expect(page.locator("#tour-step-title")).toHaveText("Welcome to ThermalTrace");

    // Exit revokes the demo session on the server, clears tour state and returns to the login page
    const oldToken = await page.evaluate(() => localStorage.getItem("tt.token"));
    await page.getByRole("region", { name: "Demo mode" }).getByRole("button", { name: "Exit demo" }).click();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    const stillValid = await page.request.get("/api/v1/auth/me", { headers: { Authorization: `Bearer ${oldToken}` } });
    expect(stillValid.status(), "demo token must be revoked on exit").toBe(401);
    const state = await page.evaluate(() => ({ token: localStorage.getItem("tt.token"), progress: sessionStorage.getItem("thermaltrace_tour_progress") }));
    expect(state).toEqual({ token: null, progress: null });
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("desktop admin tour, keyboard control, and explicit role switch", async ({ page }) => {
    test.setTimeout(300_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    const errors = trackConsole(page);
    await enter(page, "admin");
    await expect(page.locator("#tour-step-title")).toHaveText("Behind the investigation", { timeout: 20_000 });
    await expect(page).toHaveURL(/\/system$/);
    await shot(page, "admin-01-overview");

    // Keyboard: → next, ← back, Esc closes
    await page.keyboard.press("ArrowRight");
    await expect(page.locator("#tour-step-title")).toHaveText("Data-source health");
    await expect(page).toHaveURL(/\/sources$/);
    await page.keyboard.press("ArrowLeft");
    await expect(page.locator("#tour-step-title")).toHaveText("Behind the investigation");
    await page.keyboard.press("Escape");
    await expect(page.locator(".tour-card")).toHaveCount(0);

    // Admin controls are visible; the server refuses them
    const r = await page.evaluate(async () => {
      const t = localStorage.getItem("tt.token");
      const res = await fetch("/api/v1/ingestion/trigger", { method: "POST", headers: { Authorization: `Bearer ${t}`, "Content-Type": "application/json" }, body: JSON.stringify({ kind: "firms_poll", payload: {} }) });
      return { status: res.status, body: await res.json() };
    });
    expect(r.status).toBe(403);
    expect(r.body.error.code).toBe("demo_read_only");

    await page.getByRole("region", { name: "Demo mode" }).getByRole("button", { name: "Restart tour" }).click();
    const steps = await walk(page, "desktop admin");
    test.info().annotations.push({ type: "admin steps", description: steps.map(([t, l]) => `${l ? "●" : "○"} ${t}`).join(" | ") });
    expect(steps.length).toBe(14);
    expect(steps.every(([, lit]) => lit), "every admin step spotlights its target").toBe(true);
    await shot(page, "admin-done");
    await page.getByRole("button", { name: "Explore ThermalTrace" }).click();

    // Explicit switch: asks first, then starts the analyst tour with analyst (not admin) privileges
    const banner = page.getByRole("region", { name: "Demo mode" });
    await banner.getByRole("button", { name: "Switch to analyst demo" }).click();
    await expect(banner).toContainText("Switch to the analyst demo?");
    await banner.getByRole("button", { name: "Switch", exact: true }).click();
    await expect(banner).toContainText("Analyst", { timeout: 20_000 });
    await expect(page.locator("#tour-step-title")).toHaveText("Welcome to ThermalTrace", { timeout: 20_000 });
    const me = await page.evaluate(async () => (await fetch("/api/v1/auth/me", { headers: { Authorization: `Bearer ${localStorage.getItem("tt.token")}` } })).json());
    expect(me.role).toBe("analyst");
    const adminApi = await page.evaluate(async () => (await fetch("/api/v1/admin/system", { headers: { Authorization: `Bearer ${localStorage.getItem("tt.token")}` } })).status);
    expect(adminApi).toBe(403);
    expect(errors, errors.join("\n")).toEqual([]);
  });

  for (const [name, width, height] of [["tablet", 820, 1180], ["mobile-360", 360, 780], ["mobile-390", 390, 844], ["mobile-430", 430, 932]] as const) {
    test(`${name}: analyst and admin tours fit the screen`, async ({ browser }) => {
      test.setTimeout(420_000); // both tours, every step checked
      const mobile = width < 768;
      const context = await browser.newContext({ viewport: { width, height }, hasTouch: mobile, isMobile: mobile, reducedMotion: "reduce" });
      const page = await context.newPage();
      const errors = trackConsole(page);
      await enter(page, "analyst");
      await expect(page.locator("#tour-step-title")).toHaveText("Welcome to ThermalTrace", { timeout: 20_000 });
      if (mobile) await expect(page.locator(".tour-card.tour-sheet")).toBeVisible();
      const analyst = await walk(page, `${name} analyst`);
      expect(analyst.length).toBe(19);
      test.info().annotations.push({ type: `${name} analyst`, description: analyst.map(([t, l]) => `${l ? "●" : "○"} ${t}`).join(" | ") });
      await shot(page, `${name}-analyst-done`);
      await page.getByRole("button", { name: "Explore ThermalTrace" }).click();
      const banner = page.getByRole("region", { name: "Demo mode" });
      await banner.getByRole("button", { name: "Switch to admin demo" }).click();
      await banner.getByRole("button", { name: "Switch", exact: true }).click();
      await expect(page.locator("#tour-step-title")).toHaveText("Behind the investigation", { timeout: 20_000 });
      const admin = await walk(page, `${name} admin`);
      expect(admin.length).toBe(14);
      test.info().annotations.push({ type: `${name} admin`, description: admin.map(([t, l]) => `${l ? "●" : "○"} ${t}`).join(" | ") });
      await banner.getByRole("button", { name: "Exit demo" }).click();
      await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
      expect(errors, errors.join("\n")).toEqual([]);
      await context.close();
    });
  }
});
