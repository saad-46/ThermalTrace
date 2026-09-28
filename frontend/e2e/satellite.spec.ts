/**
 * Facility satellite view, through the analyst demo (no credentials; read-only). Provider failures are simulated by
 * intercepting the EOX tile requests, so every state is deterministic: available, no imagery (404), access denied (403),
 * rate limited (429), timeout, and recovery with Retry. Also: the facility popup's "Satellite view" link and phone widths.
 * Runs against a live stack with EXPLORE_MODE_ENABLED=true; skipped otherwise. Writes nothing.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const TILES = "https://tiles.maps.eox.at/**";

async function demo(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore as Analyst", exact: true }).click();
  await expect(page.getByRole("region", { name: "Demo mode" })).toContainText("Analyst", { timeout: 20_000 });
  // close the tour so it does not navigate while the test drives the app
  await page.evaluate(() => sessionStorage.setItem("thermaltrace_tour_progress", JSON.stringify({ role: "analyst", index: 0, status: "closed" })));
}

async function featured(page: Page): Promise<{ event: string; facility: string; lat: number; lon: number } | null> {
  return page.evaluate(async () => {
    const h = { Authorization: `Bearer ${localStorage.getItem("tt.token")}` };
    const f = await (await fetch("/api/v1/events/featured", { headers: h })).json();
    if (!f?.nearest_facility_id) return null;
    const fac = await (await fetch(`/api/v1/facilities/${f.nearest_facility_id}`, { headers: h })).json();
    return { event: f.public_id, facility: f.nearest_facility_id, lat: fac.latitude, lon: fac.longitude };
  });
}

const status = (page: Page) => page.getByTestId("satellite-status");

test.describe("facility satellite view", () => {
  test.beforeEach(async ({ page }) => {
    const r = await page.request.get("/api/v1/auth/demo");
    test.skip(!(r.ok() && (await r.json()).enabled === true), "explore mode is disabled");
    await demo(page);
  });

  test("toggle, real imagery, no refetch, URL, card wording", async ({ page }) => {
    const f = await featured(page);
    test.skip(!f, "no featured event with a facility");
    const tiles: string[] = [];
    page.on("request", (r) => { if (r.url().includes("tiles.maps.eox.at")) tiles.push(r.url()); });
    await page.goto(`/facilities/${f!.facility}`);
    await expect(page.locator("[data-testid=facility-map][data-ready='1']")).toBeVisible({ timeout: 30_000 });
    expect(tiles, "Map is the default and requests no imagery").toHaveLength(0);
    await page.getByTestId("view-satellite").click();
    await expect(page).toHaveURL(/view=satellite/);
    await expect(page.locator(".sr-only[aria-live]")).toContainText("mosaic loaded", { timeout: 30_000 });
    const card = page.getByTestId("satellite-card");
    await expect(card).toContainText("annual mosaic · no single acquisition date");
    await expect(card).toContainText("EOX");
    await expect(card).toContainText("does not show, confirm or date any fire or burn");
    // tiles are requested around the facility's own coordinates (z/y/x of the first tile contains the facility)
    const [z, y, x] = tiles[0].match(/\/g\/(\d+)\/(\d+)\/(\d+)\.jpg/)!.slice(1).map(Number);
    expect(Math.floor(((f!.lon + 180) / 360) * 2 ** z)).toBeGreaterThanOrEqual(x - 2);
    expect(Math.floor(((f!.lon + 180) / 360) * 2 ** z)).toBeLessThanOrEqual(x + 2);
    const latR = (f!.lat * Math.PI) / 180;
    const ty = Math.floor(((1 - Math.log(Math.tan(latR) + 1 / Math.cos(latR)) / Math.PI) / 2) * 2 ** z);
    expect(Math.abs(ty - y)).toBeLessThanOrEqual(2);
    const n = tiles.length;
    await page.getByTestId("view-map").click();
    await expect(card).toHaveCount(0);
    await page.getByTestId("view-satellite").click();
    await page.waitForTimeout(1000);
    expect(tiles.length, "switching back does not refetch").toBe(n);
  });

  for (const [code, text] of [[403, "refused the request"], [429, "rate-limiting"]] as const) {
    test(`provider ${code} shows a retryable failure without imagery metadata`, async ({ page }) => {
      const f = await featured(page);
      test.skip(!f, "no featured event with a facility");
      await page.route(TILES, (r: Route) => r.fulfill({ status: code, body: "" }));
      await page.goto(`/facilities/${f!.facility}?view=satellite`);
      await expect(status(page)).toHaveAttribute("data-state", "failed", { timeout: 20_000 });
      await expect(status(page)).toContainText("Satellite imagery could not be loaded.");
      await expect(status(page)).toContainText(text);
      await expect(page.getByTestId("satellite-card")).toContainText("Date unavailable");
      await page.unroute(TILES);
      await status(page).getByRole("button", { name: "Retry" }).click();
      await expect(page.locator(".sr-only[aria-live]")).toContainText("mosaic loaded", { timeout: 30_000 });
      await expect(status(page)).toHaveCount(0);
    });
  }

  test("no imagery (every tile 404) is reported as unavailable, not as an error", async ({ page }) => {
    const f = await featured(page);
    test.skip(!f, "no featured event with a facility");
    await page.route(TILES, (r: Route) => r.fulfill({ status: 404, body: "" }));
    await page.goto(`/facilities/${f!.facility}?view=satellite`);
    await expect(status(page)).toHaveAttribute("data-state", "none", { timeout: 20_000 });
    await expect(status(page)).toContainText("No suitable satellite imagery available for this location.");
    await expect(status(page).getByRole("button", { name: "Retry" })).toHaveCount(0);
  });

  test("timeout gives a retryable state", async ({ page }) => {
    test.setTimeout(90_000);
    const f = await featured(page);
    test.skip(!f, "no featured event with a facility");
    await page.route(TILES, () => { /* never answer */ });
    await page.goto(`/facilities/${f!.facility}?view=satellite`);
    await expect(status(page)).toContainText("Loading satellite imagery…", { timeout: 20_000 });
    await expect(status(page)).toContainText("did not respond in time", { timeout: 35_000 });
    await expect(status(page).getByRole("button", { name: "Retry" })).toBeVisible();
  });

  test("facility popup links to the satellite view", async ({ page }) => {
    const f = await featured(page);
    test.skip(!f, "no featured event with a facility");
    await page.goto(`/map?lat=${f!.lat}&lon=${f!.lon}&z=15`);
    await expect(page.locator('.maplibregl-map[data-india="loaded"]')).toBeVisible({ timeout: 40_000 });
    await expect(page.getByText(/events in view/)).toBeVisible({ timeout: 40_000 });
    const box = (await page.locator(".maplibregl-canvas").boundingBox())!;
    const card = page.getByTestId("facility-card");
    await expect(async () => {
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      await expect(card).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 30_000, intervals: [1_000, 2_000, 3_000] });
    await expect(page.getByTestId("facility-open")).toBeVisible();
    await page.getByTestId("facility-satellite").click();
    await expect(page).toHaveURL(new RegExp(`/facilities/${f!.facility}.*view=satellite`));
    await expect(page.getByTestId("view-satellite")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("satellite-card")).toBeVisible();
  });

  for (const width of [360, 390, 430]) {
    test(`phone ${width}px: controls usable, no horizontal overflow`, async ({ page }) => {
      const f = await featured(page);
      test.skip(!f, "no featured event with a facility");
      await page.setViewportSize({ width, height: 844 });
      await page.goto(`/facilities/${f!.facility}?view=satellite`);
      await expect(page.locator(".sr-only[aria-live]")).toContainText("mosaic loaded", { timeout: 30_000 });
      const sat = await page.getByTestId("view-satellite").boundingBox();
      expect(sat!.height).toBeGreaterThanOrEqual(32);
      await page.getByTestId("satellite-year").selectOption("2020");
      await expect(page.getByTestId("satellite-card")).toContainText("2020 annual mosaic", { timeout: 30_000 });
      await page.getByTestId("view-map").click();
      await expect(page.getByTestId("view-map")).toHaveAttribute("aria-pressed", "true");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }
});
