/**
 * Investigation path on a live stack (docs/TESTING.md §E2E): a real event's Sentinel-2 and weather evidence, then the
 * facility it is attributed to, from the map and back. Needs an analyst+ account:
 *   E2E_BASE_URL (default http://localhost:5173), E2E_EMAIL, E2E_PASSWORD, E2E_EVENT (optional public id)
 * Nothing here assumes a particular facility name or a future satellite scene: whatever the providers return is
 * accepted as long as the page states it truthfully (a result, "no suitable scene", "no observation", or a failure).
 */
import { expect, test, type Page } from "@playwright/test";

const EMAIL = process.env.E2E_EMAIL ?? "";
const PASSWORD = process.env.E2E_PASSWORD ?? "";
const IGNORED_CONSOLE = /tiles|basemaps|fonts|eox|cartocdn|Failed to load resource/i;

interface Bundle {
  id: string; public_id: string; latitude: number; longitude: number;
  facilities: { id: string; name: string | null; latitude: number; longitude: number; distance_m: number; rank: number }[];
}

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/synced/).first()).toBeVisible({ timeout: 15_000 });
  await page.waitForURL((u) => u.pathname !== "/", { timeout: 15_000 });
  await page.waitForLoadState("networkidle");
}

/** Authenticated API read from the page (the session's own token; nothing is stored by the test). */
const apiGet = <T,>(page: Page, path: string) =>
  page.evaluate(async (p) => {
    const r = await fetch(`/api/v1${p}`, { headers: { Authorization: `Bearer ${localStorage.getItem("tt.token")}` } });
    if (!r.ok) throw new Error(`${p}: ${r.status} (token ${localStorage.getItem("tt.token") ? "present" : "missing"})`);
    return r.json();
  }, path) as Promise<T>;

/** A real event with an attributed facility within 3 km: E2E_EVENT, or the highest-priority one in the data. */
async function pickEvent(page: Page): Promise<Bundle> {
  const refs = process.env.E2E_EVENT
    ? [process.env.E2E_EVENT]
    : (await apiGet<{ items: { public_id: string }[] }>(page, "/events?sort=priority&limit=40&facility_type=power_plant_coal&facility_type=steel_plant&facility_type=refinery&facility_type=cement_plant")).items.map((e) => e.public_id);
  for (const ref of refs) {
    const b = await apiGet<Bundle>(page, `/events/${ref}`);
    if (b.facilities.some((f) => f.distance_m < 3000)) return b;
  }
  throw new Error("no event with an attributed facility within 3 km in this dataset");
}

test.describe("investigation path", () => {
  test.skip(!EMAIL || !PASSWORD, "E2E_EMAIL / E2E_PASSWORD not set");
  test.use({ viewport: { width: 1440, height: 900 } });

  test("event imagery and weather state, facility from the map, relationship back to the event", async ({ page }) => {
    test.setTimeout(300_000);
    const errors: string[] = [];
    page.on("console", (m) => { if (m.type() === "error" && !IGNORED_CONSOLE.test(m.text())) errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push(e.message));
    await login(page);
    const ev = await pickEvent(page);
    const fac = ev.facilities.filter((f) => f.distance_m < 3000).sort((a, b) => a.rank - b.rank)[0];

    // 1-5. Satellite: the page states what it knows; a search, if offered, ends in a truthful state
    await page.goto(`/events/${ev.public_id}`);
    const satState = page.getByTestId("satellite-state").or(page.getByTestId("satellite-search-info")).first();
    await expect(satState).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/run enrichment/)).toHaveCount(0); // the old dead-end wording is gone
    const search = page.getByRole("button", { name: "Search Sentinel-2 imagery" });
    if (await search.count()) {
      await search.first().click();
      await expect(page.getByText("Searching Sentinel-2 imagery…").first()).toBeHidden({ timeout: 120_000 });
    }
    await expect(page.getByTestId("satellite-search-info").or(page.getByTestId("satellite-state")).first())
      .toContainText(/Searched|No suitable Sentinel-2 scene|search failed|did not complete/, { timeout: 30_000 });
    if (await page.getByTestId("satellite-search-info").count()) {
      await expect(page.getByText(/Sentinel-2|sentinel-2/).first()).toBeVisible(); // scene metadata shown with the images
    }
    await expect(page.getByTestId("spectral-state").or(page.getByTestId("spectral-result")).first()).toBeVisible();

    // 6-8. Weather: retrieve if needed; the result is real values, or an explicit no-data / provider state
    const retrieve = page.getByTestId("weather-request");
    if (await retrieve.count()) await retrieve.first().click();
    const weather = page.getByTestId("weather-result").or(page.getByTestId("weather-state")).first();
    await expect(weather).not.toContainText("Retrieving weather…", { timeout: 90_000 });
    const wx = await weather.innerText();
    if (await page.getByTestId("weather-result").count()) {
      expect(wx).toMatch(/°C|m\/s|hPa/);
      expect(wx).toContain("supporting environmental context");
    } else {
      expect(wx).toMatch(/No weather observation available|temporarily unavailable|did not complete/);
    }

    // 9-12. Map: centre on the attributed facility, click it, open its details
    await page.goto(`/map?lat=${fac.latitude}&lon=${fac.longitude}&z=15`);
    await expect(page.locator('.maplibregl-map[data-india="loaded"]')).toBeVisible({ timeout: 40_000 });
    await expect(page.getByText(/events in view/)).toBeVisible({ timeout: 40_000 });
    // the fly-to animates, then the viewport query loads facility icons: click the centre until the card opens
    const box = (await page.locator(".maplibregl-canvas").boundingBox())!;
    const card = page.getByTestId("facility-card");
    await expect(async () => {
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      await expect(card).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 30_000, intervals: [1_000, 2_000, 3_000] });
    if (fac.name) await expect(card).toContainText(fac.name);
    await expect(card).toContainText("not proof");
    await page.getByTestId("facility-open").click();
    await expect(page).toHaveURL(new RegExp(`/facilities/${fac.id}`));
    if (fac.name) await expect(page.getByTestId("facility-name")).toHaveText(fac.name);
    await expect(page.getByText("Provenance")).toBeVisible();
    await expect(page.getByTestId("facility-map")).toBeVisible();

    // 13-14. Back to the event; the facility is linked from it, with the relationship explained
    await page.goto(`/events/${ev.public_id}`);
    const link = page.getByTestId("event-facility-link").filter({ hasText: fac.name ?? "Unnamed" }).first();
    await link.click();
    const rel = page.getByTestId("facility-relationship");
    await expect(rel).toContainText(ev.public_id, { timeout: 20_000 });
    await expect(rel).toContainText(`Candidate #${fac.rank}`);
    await expect(rel).toContainText("not proof of causation");
    await expect(page.getByRole("link", { name: `Back to ${ev.public_id}` })).toBeVisible();
    expect(errors, errors.join("\n")).toEqual([]);
  });
});
