// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PublicLanding } from "../lib/types";

const startDemo = vi.fn(() => Promise.resolve());
const login = vi.fn(() => Promise.resolve());
let landingResponse: () => Promise<PublicLanding> = () => new Promise(() => {});

vi.mock("../lib/session", () => ({
  useSession: () => ({ login, startDemo }),
  useMedia: () => false,
}));
vi.mock("../lib/api", () => ({
  api: (path: string) => (path === "/public/landing" ? landingResponse() : Promise.resolve({ enabled: true, roles: ["analyst", "admin"] })),
}));

const { default: Landing, CountUp } = await import("../pages/Landing");

const LIVE: PublicLanding = {
  counts: { detections: 123457, events: 45679, events_recent: 812, facilities: 3021 },
  sources: [
    { id: "firms", name: "NASA FIRMS", kind: "thermal", state: "active", last_success_at: "2026-09-27T00:00:00Z" },
    { id: "cdse", name: "Copernicus Data Space Ecosystem", kind: "imagery", state: "not_configured", last_success_at: null },
    { id: "osm", name: "OpenStreetMap (Overpass)", kind: "context", state: "unavailable", last_success_at: null },
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
    expect(within(snapshot).getByText("Thermal detections")).toBeTruthy();
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
    expect(screen.getByText("1 of 3 sources active")).toBeTruthy();
    expect(screen.getByText(/Processing paused or offline/)).toBeTruthy(); // not claimed operational
    expect(screen.getByText("Available when configured")).toBeTruthy();
    expect(screen.getByText("Temporarily unavailable")).toBeTruthy();
    expect(screen.getByRole("img", { name: /49 events in 2 one-degree grid cells/ })).toBeTruthy();
    expect(screen.getByText("rule-cascade-v1.1")).toBeTruthy();
  });

  it("says statistics are unavailable instead of inventing them", async () => {
    landingResponse = () => Promise.reject(new Error("down"));
    renderLanding();
    expect(await screen.findByText(/Live statistics unavailable/, {}, { timeout: 5000 })).toBeTruthy(); // after one retry
    expect(screen.getByText(/Live activity is unavailable right now/)).toBeTruthy();
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
