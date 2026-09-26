/**
 * Landing page (signed out): hero, live statistics, sign-in and both Explore modes at desktop, tablet and phone sizes.
 * Runs against a live stack. Explore steps are skipped unless EXPLORE_MODE_ENABLED=true; normal sign-in is covered with
 * a wrong password here and with a real account in acceptance.spec.ts.
 */
import { expect as baseExpect, test, type Page } from "@playwright/test";

const expect = baseExpect.configure({ timeout: 25_000 });
const IGNORED_CONSOLE = /tiles|basemaps|fonts|Failed to load resource|WebGL/i;
const VIEWPORTS = [["desktop", 1440, 900], ["tablet", 768, 1024], ["mobile-360", 360, 800], ["mobile-390", 390, 844], ["mobile-430", 430, 932]] as const;

async function fresh(page: Page) {
  await page.goto("/");
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await page.goto("/");
}

async function exploreEnabled(page: Page): Promise<boolean> {
  const r = await page.request.get("/api/v1/auth/demo");
  return r.ok() && (await r.json()).enabled === true;
}

test.describe("landing page", () => {
  for (const [name, width, height] of VIEWPORTS) {
    test(`${name}: hero, sign-in and explore in the first viewport, live stats, no overflow`, async ({ page }) => {
      const errors: string[] = [];
      page.on("console", (m) => { if (m.type() === "error" && !IGNORED_CONSOLE.test(m.text())) errors.push(m.text()); });
      await page.setViewportSize({ width, height });
      await fresh(page);

      await expect(page.getByRole("heading", { level: 1 })).toContainText("From heat signals to actionable intelligence.");
      const signIn = page.getByRole("button", { name: "Sign in", exact: true });
      await expect(signIn).toBeInViewport();
      if (await exploreEnabled(page)) {
        await expect(page.getByRole("button", { name: "Explore as Analyst", exact: true })).toBeInViewport();
        await expect(page.getByRole("button", { name: "Explore as Admin", exact: true })).toBeInViewport();
      }

      // Live statistics come from the public endpoint; the page shows either its figures or an explicit message.
      const pub = await page.request.get("/api/v1/public/landing");
      const snapshot = page.locator("#snapshot");
      await snapshot.scrollIntoViewIfNeeded();
      if (pub.ok()) {
        const d = await pub.json();
        await expect(snapshot).toContainText(d.counts.detections.toLocaleString("en-US"));
        await expect(snapshot).toContainText(d.counts.facilities.toLocaleString("en-US"));
        await expect(snapshot).toContainText(`${d.sources_active} of ${d.sources_total} sources active`);
        await expect(page.getByRole("img", { name: /thermal event activity over the last 30 days/ })).toBeVisible();
      } else {
        await expect(snapshot).toContainText("Live statistics unavailable");
      }

      for (const id of ["how", "capabilities", "evidence", "data", "tech", "trust"]) {
        await page.locator(`#${id}`).scrollIntoViewIfNeeded();
        await expect(page.locator(`#${id} h2`)).toBeVisible();
      }
      await expect(page.getByText(/Built with/)).toContainText("by CodeCrafters");
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(over, "horizontal overflow").toBeLessThanOrEqual(1);
      // Nothing escapes its card: every glass panel lies within the viewport width.
      const escaping = await page.evaluate(() => [...document.querySelectorAll(".landing .glass")]
        .filter((e) => { const r = e.getBoundingClientRect(); return r.left < -1 || r.right > window.innerWidth + 1; }).length);
      expect(escaping, "panels outside the viewport").toBe(0);
      expect(errors, "console errors").toEqual([]);
      await page.screenshot({ path: `e2e/screenshots/landing-${name}.png` });
    });
  }

  test("normal sign-in form still reports a wrong password", async ({ page }) => {
    await fresh(page);
    await page.getByLabel("Email").fill("nobody@example.org");
    await page.getByLabel("Password").fill("wrong-password-123");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText(/Invalid email or password/);
  });

  test("reduced motion: content is shown without entrance animation", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await fresh(page);
    const opacity = await page.locator("#capabilities").evaluate((e) => getComputedStyle(e).opacity);
    expect(opacity).toBe("1");
  });

  test("Explore as Analyst, then Explore as Admin, start server-side demo sessions and their tours", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto("/");
    test.skip(!(await exploreEnabled(page)), "EXPLORE_MODE_ENABLED is off on this stack");
    await fresh(page);
    await page.getByRole("button", { name: "Explore as Analyst", exact: true }).click();
    await expect(page.getByRole("region", { name: "Demo mode" })).toContainText("Analyst");
    await expect(page.locator("#tour-step-title")).toHaveText("Welcome to ThermalTrace");
    const me = await page.evaluate(async () => (await fetch("/api/v1/auth/me", { headers: { Authorization: `Bearer ${localStorage.getItem("tt.token")}` } })).json());
    expect(me.is_demo).toBe(true);

    await page.getByRole("region", { name: "Demo mode" }).getByRole("button", { name: "Exit demo" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("From heat signals");
    await page.reload();
    await page.getByRole("button", { name: "Explore as Admin", exact: true }).click();
    await expect(page.getByRole("region", { name: "Demo mode" })).toContainText("Admin");
    await expect(page.locator("#tour-step-title")).toHaveText("Behind the investigation");
  });
});
