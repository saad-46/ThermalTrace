import { describe, expect, it } from "vitest";
import { qs } from "../lib/api";
import { compass, fmtCoord, fmtDistance, fmtDuration, relTime } from "../lib/format";
import { qualitative } from "../components/evidence";
import { buildEvidenceChain } from "../components/triage";
import { CLASS_META, STATE_META } from "../lib/taxonomy";
import { event } from "./fixture";

describe("format", () => {
  it("formats distances, durations and bearings", () => {
    expect(fmtDistance(566)).toBe("566 m");
    expect(fmtDistance(1600)).toBe("1.6 km");
    expect(fmtDistance(12500)).toBe("13 km");
    expect(fmtDistance(null)).toBe("—");
    expect(fmtDuration(0.5)).toBe("< 1 h");
    expect(fmtDuration(30)).toBe("30 h");
    expect(fmtDuration(150)).toBe("6 d");
    expect(compass(0)).toBe("N");
    expect(compass(225)).toBe("SW");
    expect(compass(359)).toBe("N");
    expect(fmtCoord(21.1055, -72.6)).toBe("21.1055°N, 72.6000°W");
  });

  it("relative time", () => {
    const now = Date.parse("2026-09-25T12:00:00Z");
    expect(relTime("2026-09-25T11:30:00Z", now)).toBe("30 min ago");
    expect(relTime("2026-09-25T02:00:00Z", now)).toBe("10 h ago");
    expect(relTime(null, now)).toBe("—");
  });
});

describe("api query strings", () => {
  it("drops empty values and repeats arrays", () => {
    expect(qs({ a: 1, b: "", c: null, d: undefined, cls: ["flare", "wildfire"] })).toBe("?a=1&cls=flare&cls=wildfire");
    expect(qs({})).toBe("");
  });
});

describe("taxonomy", () => {
  it("covers every class and state the API can return", () => {
    for (const c of ["flare", "process_heat", "coal_seam_fire", "agricultural_burn", "wildfire", "industrial_fire", "other", "unknown"])
      expect(CLASS_META[c as keyof typeof CLASS_META].label).toBeTruthy();
    expect(STATE_META.INSUFFICIENT_EVIDENCE.hint).toMatch(/manual review/i);
  });
});

describe("qualitative confidence decomposition", () => {
  it("marks missing evidence as unavailable, never as weak", () => {
    expect(qualitative("satellite", 0.3, ["satellite imagery"])).toBe("Unavailable");
    expect(qualitative("satellite", 1.0, [])).toBe("Strong");
    expect(qualitative("sensor_agreement", 0.6, [])).toBe("Moderate");
    expect(qualitative("context_support", 0.1, [])).toBe("Weak");
    expect(qualitative("model_agreement", 0.5, ["trained model"])).toBe("Unavailable");
  });
});

describe("evidence chain", () => {
  it("builds all stages from real bundle fields and flags missing ones", () => {
    const chain = buildEvidenceChain(event());
    expect(chain.map((s) => s.key)).toEqual(["detection", "location", "landcover", "facility", "persistence", "satellite", "weather", "classification", "confidence"]);
    expect(chain.find((s) => s.key === "facility")!.summary).toContain("ArcelorMittal");
    expect(chain.find((s) => s.key === "satellite")!.state).toBe("missing");
    expect(chain.find((s) => s.key === "satellite")!.summary).toBe("No scene available");
  });

  it("never claims a facility when OSM was not checked", () => {
    const ev = event({ facilities: [], enrichment_state: {} });
    const f = buildEvidenceChain(ev).find((s) => s.key === "facility")!;
    expect(f.state).toBe("missing");
    expect(f.summary).toBe("Not yet retrieved");
  });
});

describe("query-key stability", () => {
  it("sinceFromDays is stable within a minute (prevents refetch loops)", async () => {
    const { sinceFromDays } = await import("../lib/hooks");
    const t = Date.parse("2026-09-25T12:00:10Z");
    expect(sinceFromDays(7, t)).toBe(sinceFromDays(7, t + 40_000));
    expect(sinceFromDays(7, t)).toBe("2026-09-18T12:00:00.000Z");
    expect(sinceFromDays(null, t)).toBeUndefined();
  });
});

describe("CARTO basemap key", () => {
  it("adds the key only to CARTO requests, once", async () => {
    const { withCartoKey } = await import("../components/MapCanvas");
    expect(withCartoKey("https://tiles-a.basemaps.cartocdn.com/vectortiles/carto.streets/v1/3/5/3.mvt", "k1"))
      .toBe("https://tiles-a.basemaps.cartocdn.com/vectortiles/carto.streets/v1/3/5/3.mvt?key=k1");
    expect(withCartoKey("https://basemaps.cartocdn.com/gl/positron-gl-style/style.json?key=k0", "k1")).toContain("key=k0");
    expect(withCartoKey("https://tiles.maps.eox.at/wmts/1.0.0/x.jpg", "k1")).toBe("https://tiles.maps.eox.at/wmts/1.0.0/x.jpg");
    expect(withCartoKey("https://evil-basemaps.cartocdn.com.example.org/x", "k1")).not.toContain("key=");
    expect(withCartoKey("https://tiles.basemaps.cartocdn.com/x", "")).toBe("https://tiles.basemaps.cartocdn.com/x");
  });
});
