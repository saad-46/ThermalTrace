// @vitest-environment jsdom
/** Weather, Sentinel-2 search, NDVI/NBR and the facility card: every state is derived from what the backend recorded. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FacilityCard } from "../components/FacilityCard";
import { SatellitePanel, WeatherPanel } from "../components/investigation";
import { SpectralChangePanel } from "../components/landcover";
import { ToastProvider } from "../components/ui";
import type { EventJob, Scene, Weather } from "../lib/types";
import { event } from "./fixture";

const session = { can: (_r: string) => true, isDemo: false };
vi.mock("../lib/session", async (orig) => ({ ...(await orig<typeof import("../lib/session")>()), useSession: () => session }));
const apiCalls: { path: string; init?: { method?: string; query?: Record<string, unknown> } }[] = [];
vi.mock("../lib/api", async (orig) => ({
  ...(await orig<typeof import("../lib/api")>()),
  api: vi.fn(async (path: string, init?: { method?: string; query?: Record<string, unknown> }) => {
    apiCalls.push({ path, init });
    return { job_id: "j1", steps: init?.query?.steps ?? [] };
  }),
  post: vi.fn(async (path: string) => { apiCalls.push({ path, init: { method: "POST" } }); return { job_id: "j2" }; }),
}));

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter><ToastProvider>{ui}</ToastProvider></MemoryRouter></QueryClientProvider>);
}
const job = (over: Partial<EventJob>): EventJob => ({ kind: "enrich_event", steps: ["weather"], status: "queued", attempts: 0, max_attempts: 3,
  created_at: "2026-09-27T05:00:00Z", started_at: null, finished_at: null, error_type: null, ...over });
const WX: Weather = { kind: "at_last_detection", source_id: "open_meteo", dataset: "Open-Meteo Forecast (recent hourly model)",
  observed_at: "2026-09-24T21:00:00Z", retrieved_at: "2026-09-27T05:00:00Z", temperature_c: 25.5, humidity_pct: 91, wind_speed_ms: 5.56,
  wind_direction_deg: 42, precipitation_mm: null, pressure_hpa: 976.8, weather_code: 51, condition: "Light drizzle" } as Weather;
const scene = (id: string, at: string, cloud = 10): Scene => ({ id, provider: "earth-search", source_id: "earth_search", collection: "sentinel-2-l2a",
  item_id: `S2A_${id}`, platform: "sentinel-2a", acquired_at: at, cloud_cover: cloud, processing_level: "L2A", relation: "before",
  thumbnail_url: null, item_url: null, bbox: null, retrieved_at: at } as Scene);

beforeEach(() => { apiCalls.length = 0; session.can = () => true; session.isDemo = false; });
afterEach(cleanup);

describe("weather panel", () => {
  it("not requested: explains what retrieval adds and requests only the weather step", async () => {
    wrap(<WeatherPanel ev={event({ weather: [], enrichment_state: {} })} />);
    expect(screen.getByText("Weather context unavailable")).toBeTruthy();
    expect(screen.getByText(/has not been enriched with weather data yet/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retrieve weather" }));
    await waitFor(() => expect(apiCalls.some((c) => c.path === "/events/TT-2026-001323/enrich")).toBe(true));
    const call = apiCalls.find((c) => c.path === "/events/TT-2026-001323/enrich")!;
    expect(call.init?.method).toBe("POST");
    expect(call.init?.query?.steps).toEqual(["weather"]);
  });

  it("pending, provider failure and no data are three different states", () => {
    wrap(<WeatherPanel ev={event({ weather: [], jobs: [job({ status: "running", started_at: "2026-09-27T05:00:01Z" })] })} />);
    expect(screen.getByTestId("weather-state").getAttribute("role")).toBe("status");
    expect(screen.getByTestId("weather-state").textContent).toContain("Retrieving weather…");
    cleanup();
    wrap(<WeatherPanel ev={event({ weather: [], enrichment_state: { weather: { status: "failed", at: "2026-09-27T05:00:00Z", detail: "x", category: "timeout" } } })} />);
    expect(screen.getByText("Weather service temporarily unavailable")).toBeTruthy();
    expect(screen.getByText(/provider failure, not an absence of weather data/)).toBeTruthy();
    cleanup();
    wrap(<WeatherPanel ev={event({ weather: [], enrichment_state: { weather: { status: "no_data", at: "2026-09-27T05:00:00Z", detail: "no values" } } })} />);
    expect(screen.getByText("No weather observation available for this event")).toBeTruthy();
  });

  it("shows only the values the provider returned, as context not cause", () => {
    wrap(<WeatherPanel ev={event({ weather: [WX], enrichment_state: { weather: { status: "ok", at: "2026-09-27T05:00:00Z", detail: WX.dataset } } })} />);
    expect(screen.getByTestId("weather-result").textContent).toContain("25.5 °C");
    expect(screen.getByText("Light drizzle")).toBeTruthy();
    expect(screen.queryByText("Precipitation")).toBeNull(); // null: left out, never shown as 0 mm
    expect(screen.getByText(/supporting environmental context/)).toBeTruthy();
    expect(screen.getByText(/does not show what caused a fire/)).toBeTruthy();
  });

  it("a read-only demo session cannot request and is told why", () => {
    session.isDemo = true;
    wrap(<WeatherPanel ev={event({ weather: [], enrichment_state: {} })} />);
    expect(screen.queryByRole("button", { name: "Retrieve weather" })).toBeNull();
    expect(screen.getByText(/disabled in the read-only demo/)).toBeTruthy();
  });
});

describe("satellite panel", () => {
  it("distinguishes not searched, searching, failed and searched-without-scenes", () => {
    wrap(<SatellitePanel ev={event({ satellite: [], enrichment_state: {} })} />);
    expect(screen.getByText("Imagery has not been searched yet")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Search Sentinel-2 imagery" })).toBeTruthy();
    cleanup();
    wrap(<SatellitePanel ev={event({ satellite: [], jobs: [job({ steps: ["satellite"] })] })} />);
    expect(screen.getByTestId("satellite-state").getAttribute("role")).toBe("status");
    expect(screen.getByTestId("satellite-state").textContent).toContain("Searching Sentinel-2 imagery…");
    cleanup();
    wrap(<SatellitePanel ev={event({ satellite: [], enrichment_state: { satellite: { status: "failed", at: "2026-09-27T05:00:00Z", detail: "x", category: "service_unavailable" } } })} />);
    expect(screen.getByText("Sentinel-2 search failed")).toBeTruthy();
    cleanup();
    wrap(<SatellitePanel ev={event({ satellite: [], enrichment_state: { satellite: { status: "ok", at: "2026-09-27T05:00:00Z", detail: "0 scene(s)", scenes: 0, max_cloud: 60 } } })} />);
    expect(screen.getByText("No suitable Sentinel-2 scene was available for this event")).toBeTruthy();
  });

  it("a failed job after the last recorded search is reported, not hidden", () => {
    wrap(<SatellitePanel ev={event({ satellite: [], jobs: [job({ steps: ["satellite"], status: "failed", finished_at: "2026-09-27T06:00:00Z", error_type: "OperationalError" })] })} />);
    expect(screen.getByText("Imagery search did not complete")).toBeTruthy();
    expect(screen.getByText(/OperationalError/)).toBeTruthy();
  });
});

describe("NDVI / NBR panel", () => {
  const scenes = [scene("a", "2026-09-01T05:00:00Z"), scene("b", "2026-09-20T05:00:00Z")];
  it("offers no computation without a scene on both sides, and says why", () => {
    wrap(<SpectralChangePanel ev={event({ satellite: scenes, imagery_readiness: { ready: false, max_cloud: 40,
      reason: "Before/after analysis cannot be completed: no Sentinel-2 scene with cloud <= 40% after the last detection yet." } })} />);
    expect(screen.getByText("No suitable imagery available")).toBeTruthy();
    expect(screen.getByText(/after the last detection yet/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Compute/ })).toBeNull();
  });

  it("ready: computes on request; a queued job shows progress", async () => {
    wrap(<SpectralChangePanel ev={event({ satellite: scenes, imagery_readiness: { ready: true, reason: null, max_cloud: 40 } })} />);
    fireEvent.click(screen.getByRole("button", { name: "Compute NDVI / NBR change" }));
    await waitFor(() => expect(apiCalls.some((c) => c.path === "/events/TT-2026-001323/imagery-analysis")).toBe(true));
    cleanup();
    wrap(<SpectralChangePanel ev={event({ satellite: scenes, imagery_readiness: { ready: true, reason: null, max_cloud: 40 },
      jobs: [job({ kind: "imagery_analysis", steps: [], status: "running" })] })} />);
    expect(screen.getByTestId("spectral-state").textContent).toContain("Computing NDVI / NBR change…");
  });

  it("not searched: points to the imagery search instead of a dead button", () => {
    wrap(<SpectralChangePanel ev={event({ satellite: [], enrichment_state: {} })} />);
    expect(screen.getByText("Needs Sentinel-2 scenes")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Search Sentinel-2 imagery" })).toBeTruthy();
  });
});

describe("facility card", () => {
  const props = { id: "f1", name: "ArcelorMittal Nippon Steel India", type: "steel_plant", subtype: "null", status: "operating", operator: "AM/NS",
    capacity: "9.6", capacity_unit: "Mtpa", source: "osm", sources: 2, confidence: 0.8, registry: null, registry_station: "null", coordinate_source: "null" };

  it("shows the facts, the relation to the selected event and a clear way to the details", () => {
    wrap(<FacilityCard p={props} lngLat={[72.64, 21.11]} focus={event()} onClose={() => {}} variant="popup" />);
    const card = screen.getByTestId("facility-card");
    expect(card.textContent).toContain("ArcelorMittal Nippon Steel India");
    expect(card.textContent).toContain("AM/NS");
    expect(card.textContent).toContain("2 sources");
    expect(card.textContent).toContain("attribution candidate #1, score 0.31");
    expect(card.textContent).not.toContain("null");
    expect(screen.getByRole("link", { name: /View facility details/ }).getAttribute("href")).toBe("/facilities/f1?event=TT-2026-001323");
    expect(card.textContent).toContain("not proof");
  });

  it("without a selected event it links to the facility alone; the phone variant is a bottom sheet", () => {
    const onClose = vi.fn();
    wrap(<FacilityCard p={props} lngLat={[72.64, 21.11]} focus={null} onClose={onClose} variant="sheet" />);
    expect(screen.getByRole("link", { name: /View facility details/ }).getAttribute("href")).toBe("/facilities/f1");
    expect(screen.getByTestId("facility-card").className).toContain("fac-card--sheet");
    fireEvent.click(screen.getByRole("button", { name: "Close facility card" }));
    expect(onClose).toHaveBeenCalled();
  });
});
