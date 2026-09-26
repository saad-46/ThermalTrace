// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { GLOSSARY } from "../tour/glossary";
import { placePopover, waitForTarget } from "../tour/target";
import { resolveRoute, resolveTarget } from "../tour/TourProvider";
import { ADMIN_TOUR, ANALYST_TOUR } from "../tour/tours";
import type { TourContext } from "../tour/types";
import type { FeaturedEvent } from "../lib/types";

const featured = { public_id: "TT-2026-001235", selection_reasons: ["a mapped facility within 2 km"], unavailable_evidence: [] } as unknown as FeaturedEvent;
const desktop: TourContext = { featured, isMobile: false };
const phone: TourContext = { featured, isMobile: true };
const empty: TourContext = { featured: null, isMobile: false };

// Every source file as text (Vite resolves this at build time; no Node APIs needed).
const SOURCE = Object.values(
  import.meta.glob(["../**/*.tsx", "../**/*.ts", "!../__tests__/**"], { query: "?raw", import: "default", eager: true }) as Record<string, string>,
).join("\n");

describe("tour content", () => {
  for (const tour of [ANALYST_TOUR, ADMIN_TOUR]) {
    it(`${tour.id}: step ids are unique and every target exists in the app`, () => {
      const ids = tour.steps.map((s) => s.id);
      expect(new Set(ids).size).toBe(ids.length);
      const targets = tour.steps.flatMap((s) => [s.target, s.mobile?.target]).filter((t): t is string => !!t);
      for (const t of targets) expect(SOURCE.includes(`"${t}"`), `data-tour-id "${t}" is rendered somewhere`).toBe(true);
    });
    it(`${tour.id}: glossary keys resolve`, () => {
      for (const s of tour.steps) for (const k of s.terms ?? []) expect(GLOSSARY[k], `${s.id}: ${k}`).toBeTruthy();
    });
  }

  it("uses defensible wording: no overclaiming, priority is not risk, imagery is not proof", () => {
    const text = [...ANALYST_TOUR.steps, ...ADMIN_TOUR.steps].map((s) => [typeof s.body === "string" ? s.body : s.body(desktop), s.why, s.how, s.limits, s.learnMore].join(" ")).join(" ").toLowerCase();
    for (const banned of ["revolutionary", "game-changing", "world's first", "100% accurate", "magic", "unprecedented", "mathematical proof"])
      expect(text).not.toContain(banned);
    expect(text).toContain("not a fire-risk");
    expect(text).toContain("consistent with burning, not proof of burning");
    expect(text).toContain("does not prove that a facility caused");
    expect(text).toContain("shap explains contribution; it does not prove causation");
    expect(text).toContain("not the probability of a fire");
    // Admin tour is technically honest about what does not exist.
    expect(text).toContain("no imagery-based classifier");
    expect(text).toContain("not calibrated probabilities");
    expect(text).toContain("not real-time");
    expect(text).toContain("stored inactive");
  });

  it("the featured-event step explains the real selection, and every limitation is shown", () => {
    const step = ANALYST_TOUR.steps.find((s) => s.id === "featured")!;
    const body = typeof step.body === "string" ? step.body : step.body(desktop);
    expect(body).toContain("TT-2026-001235");
    expect(body).toContain("a mapped facility within 2 km");
    expect(ANALYST_TOUR.steps[ANALYST_TOUR.steps.length - 1].id).toBe("summary");
  });

  it("the analyst tour covers the investigation story in order", () => {
    const ids = ANALYST_TOUR.steps.map((s) => s.id);
    const order = ["welcome", "data", "queue", "search", "featured", "map", "facility", "rings", "persistence", "chain", "landcover", "spectral", "classification", "shap", "review", "alerts", "reports", "summary"];
    expect(order.map((id) => ids.indexOf(id))).toEqual([...order.map((id) => ids.indexOf(id))].sort((a, b) => a - b));
  });
});

describe("route and target resolution", () => {
  const map = ANALYST_TOUR.steps.find((s) => s.id === "map")!;
  const persistence = ANALYST_TOUR.steps.find((s) => s.id === "persistence")!;
  it("routes follow the real featured event", () => {
    expect(resolveRoute(map, desktop)).toBe("/map?event=TT-2026-001235");
    expect(resolveRoute(persistence, desktop)).toBe("/events/TT-2026-001235");
  });
  it("uses phone targets on phones", () => {
    expect(resolveTarget(persistence, desktop)).toBe("persistence-panel");
    expect(resolveTarget(persistence, phone)).toBe("card-persistence");
  });
  it("with no events, event steps have no route or target (explained, not spotlighted)", () => {
    expect(resolveRoute(persistence, empty)).toBeNull();
    expect(resolveTarget(persistence, empty)).toBeNull();
    expect(persistence.fallback).toMatch(/No thermal events/);
  });
});

describe("popover placement", () => {
  it("prefers below, then above, and never leaves the viewport", () => {
    const below = placePopover({ top: 100, left: 100, width: 200, height: 50 }, 360, 200, 1440, 900);
    expect(below.placement).toBe("bottom");
    const above = placePopover({ top: 700, left: 100, width: 200, height: 150 }, 360, 200, 1440, 900);
    expect(above.placement).toBe("top");
    const edge = placePopover({ top: 100, left: 1400, width: 30, height: 30 }, 360, 200, 1440, 900);
    expect(edge.left + 360).toBeLessThanOrEqual(1440 - 12);
  });
  it("sits inside large targets such as the map", () => {
    const p = placePopover({ top: 50, left: 200, width: 1240, height: 850 }, 360, 240, 1440, 900);
    expect(p.placement).toBe("inside");
    expect(p.top).toBeGreaterThanOrEqual(12);
    expect(p.top + 240).toBeLessThanOrEqual(900 - 12);
  });
  it("clamps a target that has scrolled off-screen", () => {
    const p = placePopover({ top: 1400, left: 200, width: 600, height: 300 }, 360, 240, 1440, 900);
    expect(p.top).toBeGreaterThanOrEqual(12);
    expect(p.top + 240).toBeLessThanOrEqual(900 - 12);
  });
});

describe("waiting for targets", () => {
  it("resolves when the target is mounted later and null when it never appears", async () => {
    const pending = waitForTarget("late-panel", 2000);
    const el = document.createElement("div");
    el.setAttribute("data-tour-id", "late-panel");
    el.getBoundingClientRect = () => ({ width: 100, height: 40, top: 0, left: 0, right: 100, bottom: 40, x: 0, y: 0, toJSON: () => ({}) });
    document.body.appendChild(el);
    await expect(pending).resolves.toBe(el);
    await expect(waitForTarget("never-rendered", 50)).resolves.toBeNull();
  });
});
