/**
 * Final acceptance scenario (docs/TESTING.md §E2E). Runs against a live stack:
 *   E2E_BASE_URL (default http://localhost:5173), E2E_EMAIL, E2E_PASSWORD (analyst+ account), E2E_EVENT (optional public id)
 *   E2E_SEARCH (optional search term; default "TT-")
 * Screenshots → e2e/screenshots/ (git-ignored; curated copies live in docs/screenshots/).
 */
import { expect, test, type Page } from "@playwright/test";

const EMAIL = process.env.E2E_EMAIL ?? "";
const PASSWORD = process.env.E2E_PASSWORD ?? "";
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e/screenshots/${name}.png`, fullPage: false });
// Basemap/tile/font fetch noise from third-party CDNs is not an application error.
const IGNORED_CONSOLE = /tiles|basemaps|fonts|eox|cartocdn|Failed to load resource/i;

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/synced/).first()).toBeVisible({ timeout: 15_000 });
}

async function noHorizontalOverflow(page: Page, where: string) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over, `horizontal overflow on ${where}`).toBeLessThanOrEqual(1);
}

function trackConsole(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error" && !IGNORED_CONSOLE.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test.describe("desktop analyst workflow", () => {
  test.skip(!EMAIL || !PASSWORD, "E2E_EMAIL / E2E_PASSWORD not set");
  test.use({ viewport: { width: 1440, height: 900 } });

  test("search → map → event → evidence → review → report → alert → all screens", async ({ page }) => {
    const errors = trackConsole(page);
    await login(page);

    // Live map with real events
    await expect(page.getByRole("status").filter({ hasText: /events in view/ })).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(1500);
    await shot(page, "01-live-map");

    // Global search: a term with results, then event id → investigation. The default matches event
    // ids, which exist in any processed database; district names (e.g. E2E_SEARCH=Dhanbad) need
    // geocoding enrichment first.
    const search = page.getByRole("combobox", { name: /Search events/ });
    await search.fill(process.env.E2E_SEARCH ?? "TT-");
    await expect(page.getByRole("option").first()).toBeVisible({ timeout: 10_000 });
    await shot(page, "02-global-search");
    const first = page.locator("aside .mono").first();
    const publicId = process.env.E2E_EVENT ?? (await first.textContent())!.trim();
    await search.fill(publicId);
    await page.getByRole("option", { name: new RegExp(publicId) }).click();
    await expect(page.getByRole("heading", { name: publicId, level: 1 })).toBeVisible({ timeout: 15_000 });

    // Map + evidence panel with every tab
    await page.goto(`/map?event=${publicId}`);
    await expect(page.getByText("Evidence chain")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Why is this prioritised?")).toBeVisible();
    await page.waitForTimeout(2500);
    await shot(page, "03-map-event-selected");
    for (const tab of ["Evidence", "Facilities", "History", "Satellite", "Weather", "Model", "Review", "Provenance"]) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByRole("tabpanel")).toBeVisible();
    }
    await page.getByRole("tab", { name: "History" }).click();
    await expect(page.getByRole("list", { name: "Detections per day" })).toBeVisible();
    await shot(page, "04-evidence-history");

    // Full investigation page
    await page.goto(`/events/${publicId}`);
    await expect(page.getByRole("heading", { name: "Analyst review" })).toBeVisible();
    await noHorizontalOverflow(page, "event page");
    await shot(page, "05-event-page");

    // Review + note
    await page.getByRole("radio", { name: "Escalate" }).click();
    await page.locator("#rnotes").fill("E2E: escalated for supervisor check of facility attribution.");
    await page.getByRole("button", { name: "Record decision" }).click();
    await expect(page.getByText("Decision recorded: Escalate")).toBeVisible();
    await page.getByLabel("New note").fill("E2E note: compare with Sentinel-2 SWIR when credentials are configured.");
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByText("Note added")).toBeVisible();

    // Report
    await page.getByRole("button", { name: /Generate report/ }).click();
    await expect(page.getByRole("button", { name: "Download PDF" })).toBeVisible({ timeout: 30_000 });

    // Alert on area (prefilled) with cooldown
    await page.getByRole("link", { name: /Alert on area/ }).click();
    await expect(page.getByRole("heading", { name: "New alert rule" })).toBeVisible();
    await expect(page.getByLabel("Email/push cooldown (minutes)")).toHaveValue("60");
    await page.getByRole("button", { name: "Create rule" }).click();
    await expect(page.getByText(/Rule created/)).toBeVisible();
    await shot(page, "06-alerts");

    // Events list: priority-sorted queue
    await page.goto("/events");
    await expect(page.getByRole("columnheader", { name: "Priority" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByLabel("Sort")).toHaveValue("priority");
    // Guard against refetch storms (unstable query keys once caused ~8 requests/s from this page).
    let listCalls = 0;
    const count = (r: { url(): string }) => { if (/\/api\/v1\/events\?/.test(r.url())) listCalls++; };
    page.on("request", count);
    await page.waitForTimeout(5000);
    page.off("request", count);
    expect(listCalls, "events list requests while idle for 5 s").toBeLessThanOrEqual(1);
    await shot(page, "07-events");

    // Every other screen renders with real data and no overflow
    for (const [path, heading] of [["/overview", "Overview"], ["/facilities", "Facilities"], ["/analytics", "Analytics"],
      ["/sources", "Data sources"], ["/watchlists", "Watchlists"], ["/reports", "Reports"], ["/settings", "Settings"]] as const) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
      await page.waitForTimeout(1200);
      await noHorizontalOverflow(page, path);
      await shot(page, `08-${heading.toLowerCase().replace(/\s+/g, "-")}`);
    }
    await page.goto("/facilities");
    await page.locator("tbody tr").first().click();
    await expect(page.getByRole("heading", { name: /Thermal history within 3 km/ })).toBeVisible();
    await page.waitForTimeout(800);
    await shot(page, "09-facility-profile");

    expect(errors, errors.join("\n")).toEqual([]);
  });
});

test.describe("tablet layout", () => {
  test.skip(!EMAIL || !PASSWORD, "E2E_EMAIL / E2E_PASSWORD not set");
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true });

  test("icon-rail navigation, map + evidence panel, tables", async ({ page }) => {
    await login(page);
    await expect(page.getByRole("link", { name: "Live map" })).toBeVisible();
    await page.waitForTimeout(1500);
    await noHorizontalOverflow(page, "tablet map");
    await shot(page, "t01-map");
    await page.getByRole("link", { name: "Events" }).click();
    await expect(page.getByRole("heading", { name: "Thermal events" })).toBeVisible();
    await shot(page, "t02-events");
  });
});

test.describe("mobile investigation", () => {
  test.skip(!EMAIL || !PASSWORD, "E2E_EMAIL / E2E_PASSWORD not set");
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("map, search, priority queue, event, evidence cards, review, alerts, watchlist, more", async ({ page }) => {
    const errors = trackConsole(page);
    await login(page);
    await page.waitForTimeout(2000);
    await noHorizontalOverflow(page, "mobile map");
    await shot(page, "m01-map");
    await page.getByRole("link", { name: "Events" }).click();
    await expect(page.getByRole("button", { name: "Priority" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: /Search events/ })).toBeVisible();
    await shot(page, "m02-events");
    await page.locator(".m-list .item").first().click();
    await expect(page.getByRole("list", { name: /Evidence cards/ })).toBeVisible({ timeout: 15_000 });
    await noHorizontalOverflow(page, "mobile event");
    await shot(page, "m03-event");
    await page.getByRole("list", { name: /Evidence cards/ }).evaluate((el) => el.scrollBy({ left: 700 }));
    await page.waitForTimeout(400);
    await shot(page, "m04-evidence");
    await page.getByRole("button", { name: "Review" }).click();
    await expect(page.getByRole("button", { name: "Record decision" })).toBeVisible();
    await page.getByRole("link", { name: "Alerts" }).click();
    await shot(page, "m05-alerts");
    await page.getByRole("link", { name: "Watchlist" }).click();
    await shot(page, "m06-watchlist");
    await page.getByRole("link", { name: "More" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    expect(errors, errors.join("\n")).toEqual([]);
  });
});
