// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PublicLanding } from "../lib/types";

const startDemo = vi.fn(() => Promise.resolve());
const login = vi.fn(() => Promise.resolve());
let landingResponse: () => Promise<PublicLanding> = () => new Promise(() => {});
// Test fixture geometry (a square "mainland" and two small islands); the real boundary comes from the backend.
const BOUNDARY = {
  india: { type: "Feature", properties: {}, geometry: { type: "MultiPolygon", coordinates: [
    [[[70, 10], [90, 10], [90, 30], [70, 30], [70, 10]]],
    [[[72.6, 10.5], [72.7, 10.5], [72.7, 10.6], [72.6, 10.5]]],
    [[[92.7, 11.6], [92.8, 11.6], [92.8, 11.7], [92.7, 11.6]]]] } },
  states: { type: "FeatureCollection", features: [] }, bbox: [70, 10, 92.8, 30], source: "fixture",
};
let boundaryResponse: () => Promise<unknown> = () => Promise.resolve(BOUNDARY);

vi.mock("../lib/session", () => ({
  useSession: () => ({ login, startDemo }),
  useMedia: () => false,
}));
vi.mock("../lib/api", () => ({
  api: (path: string) => (path === "/public/landing" ? landingResponse() : path === "/public/boundary" ? boundaryResponse()
    : Promise.resolve({ enabled: true, roles: ["analyst", "admin"] })),
}));

const { default: Landing, CountUp, flameCells } = await import("../pages/Landing");

const LIVE: PublicLanding = {
  counts: { detections: 123457, events: 45679, events_recent: 812, facilities: 3021, events_outside_india: 5021 },
  sources: [
    { id: "firms", name: "NASA FIRMS", kind: "detections", state: "active", reason: "Connected", requirement: null, last_success_at: "2026-09-27T00:00:00Z" },
    { id: "cdse", name: "Copernicus Data Space Ecosystem", kind: "imagery", state: "credentials_required", reason: "Credentials required",
      requirement: "Copernicus Data Space OAuth client", last_success_at: null },
    { id: "osm", name: "OpenStreetMap (Overpass)", kind: "facilities", state: "unavailable", reason: "Not responding", requirement: null, last_success_at: null },
  ],
  sources_active: 1,
  sources_total: 3,
  latest_detection: new Date(Date.now() - 2 * 3600_000).toISOString(),
  firms_last_sync: new Date(Date.now() - 20 * 60_000).toISOString(),
  workers_online: false,
  classifier: "rule-cascade-v1.1",
  activity: { window_days: 30, cell_deg: 1, cells: [[22.5, 69.5, 40], [23.5, 86.5, 9]] },
  generated_at: new Date().toISOString(),
  cache_seconds: 300,
};

function renderLanding() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Landing /></QueryClientProvider>);
}

const SOURCE = Object.values(
  import.meta.glob("../pages/Landing.tsx", { query: "?raw", import: "default", eager: true }) as Record<string, string>,
).join("\n");

beforeEach(() => {
  startDemo.mockClear();
  login.mockClear();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("landing page", () => {
  it("renders the hero, sign-in form, both explore modes and the footer credit", async () => {
    renderLanding();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("From heat signals to actionable intelligence.");
    expect(screen.getByLabelText("Email")).toBeTruthy();
    expect(screen.getByLabelText("Password")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Explore as Analyst" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Explore as Admin" })).toBeTruthy();
    expect(screen.getByText(/Built with/).textContent).toContain("by CodeCrafters");
    expect(document.body.textContent).not.toMatch(/SIH|Smart India Hackathon|hackathon/i);
  });

  it("explore buttons start the server-side demo session (no client-side fake login)", async () => {
    renderLanding();
    fireEvent.click(await screen.findByRole("button", { name: "Explore as Analyst" }));
    expect(startDemo).toHaveBeenCalledWith("analyst");
    expect(login).not.toHaveBeenCalled();
  });

  it("normal sign-in uses the existing login flow", async () => {
    renderLanding();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: " a@b.org " } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret-pass-1" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Sign in" })); });
    expect(login).toHaveBeenCalledWith("a@b.org", "secret-pass-1");
  });

  it("shows a loading state, not numbers, while live statistics load", () => {
    landingResponse = () => new Promise(() => {});
    renderLanding();
    const snapshot = document.getElementById("snapshot")!;
    expect(within(snapshot).getByText("Thermal detections in India")).toBeTruthy();
    expect(snapshot.querySelector(".lp-stats")!.getAttribute("aria-busy")).toBe("true");
    for (const v of snapshot.querySelectorAll(".lp-stat-value")) expect(v.textContent).not.toMatch(/\d/);
    expect(screen.getByText(/Connecting to live data/)).toBeTruthy();
  });

  it("renders live figures and source states from the API", async () => {
    landingResponse = () => Promise.resolve(LIVE);
    renderLanding();
    expect(await screen.findAllByText("123,457")).toBeTruthy();
    expect(screen.getAllByText("45,679").length).toBeGreaterThan(0);
    expect(screen.getAllByText("3,021").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /1 \/ 3 sources active/ })).toBeTruthy();
    expect(screen.getByText(/Processing paused or offline/)).toBeTruthy(); // not claimed operational
    expect(screen.getAllByText("Credentials required").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(screen.getByText("Needs Copernicus Data Space OAuth client")).toBeTruthy();
    expect(await screen.findByRole("img", { name: /including Lakshadweep and the Andaman and Nicobar Islands, showing 49 thermal events inside India/ })).toBeTruthy();
    expect(screen.getByText("rule-cascade-v1.1")).toBeTruthy();
  });

  it("source health opens a list of every backend state and what inactive sources need", async () => {
    landingResponse = () => Promise.resolve(LIVE);
    renderLanding();
    const btn = await screen.findByRole("button", { name: /1 \/ 3 sources active/ });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    const region = screen.getByRole("region", { name: "Data source health" });
    expect(within(region).getAllByRole("listitem")).toHaveLength(3);
    expect(within(region).getByText("NASA FIRMS").closest("li")!.textContent).toContain("Active");
    expect(within(region).getByText("Needs Copernicus Data Space OAuth client")).toBeTruthy();
    expect(within(region).getByText("Not responding")).toBeTruthy(); // the reason, not a generic error
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Data source health" })).toBeNull();
  });

  it("marks the busiest live cells with a flame and shows India on the Copernicus card", async () => {
    landingResponse = () => Promise.resolve(LIVE);
    const { container } = renderLanding();
    await screen.findByRole("img", { name: /marked with a flame/ });
    expect(container.querySelectorAll(".lp-flames .tt-flame")).toHaveLength(2); // only 2 live cells: never invented
    expect(container.querySelector(".lp-source.st-credentials_required .tt-india")).toBeTruthy();
  });

  it("says statistics are unavailable instead of inventing them", async () => {
    landingResponse = () => Promise.reject(new Error("down"));
    renderLanding();
    expect(await screen.findByText(/Live statistics unavailable/, {}, { timeout: 5000 })).toBeTruthy(); // after one retry
    expect(screen.getByText("Live activity unavailable")).toBeTruthy();
    expect(document.querySelector(".lp-india")).toBeTruthy(); // India is drawn without any fire data
    expect(screen.getByText(/Live status unavailable/)).toBeTruthy();
    expect(screen.getByText(/Source status is unavailable/)).toBeTruthy();
    expect(document.querySelectorAll(".lp-stat-value").length).toBe(0);
  });

  it("contains no hard-coded metrics or claims the system does not support", () => {
    expect(SOURCE).not.toMatch(/\b\d{1,3},\d{3}\b/); // no literal figures like 4,907
    expect(SOURCE).not.toMatch(/\d+(\.\d+)?%\s*(confidence|accura)/i);
    for (const claim of [/xgboost/i, /calibrated probab/i, /real-time imagery/i, /drift monitoring/i, /100% accurate/i, /proves? a fire/i])
      expect(SOURCE).not.toMatch(claim);
  });

  it("flames mark the busiest distinct areas and never more cells than exist", () => {
    // busiest first; the second cell is adjacent to the first, so it does not get its own flame
    const cells: [number, number, number][] = [[8.5, 77.5, 90], [8.5, 78.5, 80], [31.5, 74.5, 60], [23.5, 86.5, 50], [26.5, 94.5, 40]];
    expect(flameCells(cells).map((c) => c[2])).toEqual([90, 60, 50]);
    expect(flameCells([[20.5, 80.5, 5]])).toHaveLength(1);
    expect(flameCells([])).toEqual([]);
  });

  it("draws India, with its island territories, even when there are no fires", async () => {
    landingResponse = () => Promise.resolve({ ...LIVE, activity: { ...LIVE.activity, cells: [] } });
    const { container } = renderLanding();
    expect(await screen.findByText(/No thermal anomalies inside India in the last 30 days/)).toBeTruthy();
    expect(container.querySelector(".lp-india")).toBeTruthy();
    const labels = [...container.querySelectorAll(".lp-island-labels text")].map((t) => t.textContent);
    expect(labels).toEqual(expect.arrayContaining(["Lakshadweep", "Andaman & Nicobar"]));
    expect(container.querySelectorAll(".lp-flames .tt-flame")).toHaveLength(0);
  });

  it("CEA and Copernicus cards stay compact: name, what the source is for, and its status", async () => {
    landingResponse = () => Promise.resolve({ ...LIVE, sources: [
      ...LIVE.sources.filter((x) => x.id !== "cdse"),
      { id: "cea", name: "Central Electricity Authority (India)", kind: "facilities", state: "active", reason: "Connected", requirement: null,
        last_success_at: "2026-09-27T00:00:00Z" },
      { id: "cdse", name: "Copernicus Data Space Ecosystem", kind: "imagery", state: "active", reason: "Authentication healthy",
        requirement: null, last_success_at: "2026-09-27T00:00:00Z" },
    ] });
    renderLanding();
    const cea = (await screen.findByText("Central Electricity Authority (India)")).closest("li")!;
    expect(cea.textContent).toContain("Official power-station registry");
    expect(cea.querySelector(".lp-state.active")).toBeTruthy();
    const cdse = screen.getByText("Copernicus Data Space Ecosystem", { selector: ".lp-source-name" }).closest("li")!;
    expect(cdse.textContent).toContain("Sentinel-2 SWIR composites for visual review of an event");
    expect(cdse.querySelector(".lp-state.active")).toBeTruthy();
    for (const card of [cea, cdse]) {
      for (const detail of ["stations", "located", "for review", "Authentication", "Satellite preview", "Last checked", "verified"]) {
        expect(card.textContent).not.toContain(detail);
      }
      expect(card.textContent).not.toMatch(/\d(\.\d)? s|\d+ ms/);  // no response times
    }
  });

  it("respects reduced motion: figures appear immediately without a count-up", () => {
    class IO { observe() {} disconnect() {} }
    vi.stubGlobal("IntersectionObserver", IO);
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
    const { container } = render(<CountUp value={98765} />);
    expect(container.querySelector("[aria-hidden]")!.textContent).toBe("98,765");
    cleanup();
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
    const animated = render(<CountUp value={98765} />);
    expect(animated.container.querySelector("[aria-hidden]")!.textContent).toBe("0"); // animates once visible
    expect(animated.container.querySelector(".sr-only")!.textContent).toBe("98,765"); // exact value always announced
  });
});
