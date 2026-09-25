/**
 * Final acceptance scenario (docs/TESTING.md §E2E). Runs against a live stack:
 *   E2E_BASE_URL (default http://localhost:5173), E2E_EMAIL, E2E_PASSWORD (analyst account), E2E_EVENT (optional public id)
 * Screenshots are written to e2e/screenshots/ for visual review.
 */
import { expect, test, type Page } from "@playwright/test";

const EMAIL = process.env.E2E_EMAIL ?? "";
const PASSWORD = process.env.E2E_PASSWORD ?? "";
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e/screenshots/${name}.png`, fullPage: false });

test.skip(!EMAIL || !PASSWORD, "E2E_EMAIL / E2E_PASSWORD not set");

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/synced/)).toBeVisible({ timeout: 15_000 });
}

test.describe("desktop analyst workflow", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("map → event → evidence → review → alert → watchlist → report", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (m) => { if (m.type() === "error" && !/tiles|basemaps|fonts|eox/i.test(m.text())) consoleErrors.push(m.text()); });
    await login(page);

    // 1–2: live map with real events
    await expect(page.getByRole("status").filter({ hasText: /events in view/ })).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(1500);
    await shot(page, "01-live-map");

    // 3–14: select the top persistent source from the side panel and inspect it
    const first = page.locator("aside .mono").first();
    const publicId = process.env.E2E_EVENT ?? (await first.textContent())!.trim();
    await page.goto(`/map?event=${publicId}`);
    await expect(page.getByRole("heading", { name: publicId })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Investigation summary")).toBeVisible();
    await expect(page.getByText("Evidence confidence matrix")).toBeVisible();
    await page.waitForTimeout(2500);
    await shot(page, "02-map-event-selected");
    for (const tab of ["Evidence", "Facilities", "History", "Satellite", "Weather", "Model", "Provenance"]) {
      await page.getByRole("tab", { name: tab }).click();
      await page.waitForTimeout(300);
    }
    await page.getByRole("tab", { name: "Satellite" }).click();
    await shot(page, "03-satellite-tab");

    // full investigation page
    await page.goto(`/events/${publicId}`);
    await expect(page.getByRole("heading", { name: "Analyst review" })).toBeVisible();
    await shot(page, "04-event-page");

    // 15–16: review + note
    await page.getByRole("radio", { name: "Escalate" }).click();
    await page.locator("#rnotes").fill("E2E: escalated for supervisor check of facility attribution.");
    await page.getByRole("button", { name: "Record decision" }).click();
    await expect(page.getByText("Decision recorded: Escalate")).toBeVisible();
    await page.getByLabel("New note").fill("E2E note: compare with Sentinel-2 SWIR when credentials are configured.");
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByText("Note added")).toBeVisible();

    // 18: report
    await page.getByRole("button", { name: /Generate report/ }).click();
    await expect(page.getByRole("button", { name: "Download PDF" })).toBeVisible({ timeout: 30_000 });

    // 17: alert on area (prefilled rule form)
    await page.getByRole("link", { name: /Alert on area/ }).click();
    await expect(page.getByRole("heading", { name: "New alert rule" })).toBeVisible();
    await page.getByRole("button", { name: "Create rule" }).click();
    await expect(page.getByText(/Rule created/)).toBeVisible();
    await shot(page, "05-alerts");

    // other screens render without errors
    for (const [path, heading] of [["/overview", "Overview"], ["/events", "Thermal events"], ["/facilities", "Facilities"], ["/analytics", "Analytics"],
      ["/sources", "Data sources"], ["/watchlists", "Watchlists"], ["/reports", "Reports"]] as const) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
      await page.waitForTimeout(1200);
      await shot(page, `06-${heading.toLowerCase().replace(/\s+/g, "-")}`);
    }
    expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
  });
});

test.describe("mobile investigation", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("map, event sheet, evidence cards, review", async ({ page }) => {
    await login(page);
    await page.waitForTimeout(2000);
    await shot(page, "m01-map");
    await page.getByRole("link", { name: "Events" }).click();
    await page.getByRole("button", { name: "Persistent" }).click();
    await page.locator(".m-list .item").first().click();
    await expect(page.getByRole("list", { name: /Evidence cards/ })).toBeVisible({ timeout: 15_000 });
    await shot(page, "m02-event");
    await page.getByRole("button", { name: "Review" }).click();
    await expect(page.getByRole("button", { name: "Record decision" })).toBeVisible();
    await shot(page, "m03-review");
    await page.getByRole("link", { name: "Alerts" }).click();
    await shot(page, "m04-alerts");
  });
});
