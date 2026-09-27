// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { EvidenceChain } from "../components/triage";
import { EvidenceCompleteness, freshness } from "../components/workspace";
import { InvestigationStatus } from "../pages/EventPage";
import type { EvidenceStage, StageStatus } from "../lib/types";
import { event } from "./fixture";

afterEach(cleanup);

const stage = (key: string, title: string, state: StageStatus, over: Partial<EvidenceStage> = {}): EvidenceStage => ({
  key, title, state, state_label: { available: "Available", pending: "Pending", no_data: "No data", not_requested: "Not requested",
    failed: "Failed", review: "Requires analyst review" }[state],
  value: `${title} value`, detail: null, reason: state === "available" ? null : `${title} reason`, source: `${title} source`,
  at: state === "available" ? "2026-09-25T06:00:00Z" : null, contributes: "c", limitation: "l", knowledge: "observed", ...over,
});

const STAGES = [
  stage("detection", "Thermal detection", "available"), stage("clustering", "Event clustering", "available"),
  stage("persistence", "Temporal persistence", "available"), stage("facility_proximity", "Facility proximity", "available"),
  stage("facility_attribution", "Facility attribution", "available"), stage("landcover", "Land cover", "pending"),
  stage("weather", "Weather", "failed"), stage("satellite", "Satellite scene availability", "no_data"),
  stage("spectral", "Spectral analysis (NDVI / NBR)", "not_requested"), stage("classification", "Classification", "available"),
  stage("explainability", "Explainability", "available"), stage("review", "Analyst review", "review"),
  stage("final_status", "Final status", "review"),
];
const withStages = (over = {}) => event({
  evidence_stages: {
    stages: STAGES,
    completeness: { available: 7, total: 13, note: "Evidence availability: not a confidence score.",
      by_state: { available: 7, pending: 1, no_data: 1, not_requested: 1, failed: 1, review: 2 } },
    freshness: { latest_observation_at: "2026-09-24T21:50:00Z", latest_evidence_refresh_at: "2026-09-25T06:00:00Z",
      processed_at: "2026-09-25T06:00:00Z", record_updated_at: "2026-09-26T08:00:00Z" },
  },
  ...over,
});

describe("evidence stages (one server definition)", () => {
  it("renders exactly the server's 13 stages with every state distinct", () => {
    render(<EvidenceChain ev={withStages()} />);
    const list = screen.getByRole("list", { name: "Evidence stages" });
    expect(list.querySelectorAll(":scope > li")).toHaveLength(13);
    for (const label of ["Pending", "Failed", "No data", "Not requested"]) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Requires analyst review")).toHaveLength(2);
  });

  it("never invents stages when the bundle has none", () => {
    render(<EvidenceChain ev={event({ evidence_stages: null })} />);
    expect(screen.getByText("Evidence stages are not available for this event.")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Evidence stages" })).toBeNull();
  });

  it("expands a stage to its reason, source and limitation", () => {
    render(<EvidenceChain ev={withStages()} />);
    fireEvent.click(screen.getByRole("button", { name: /Weather/ }));
    expect(screen.getByText("Weather reason")).toBeTruthy();
    expect(screen.getByText("Weather source")).toBeTruthy();
  });

  it("availability counts come from the server and are labelled as not confidence", () => {
    render(<EvidenceCompleteness ev={withStages()} />);
    expect(screen.getByText("7 / 13 stages available")).toBeTruthy();
    expect(screen.getByText(/not a confidence score/)).toBeTruthy();
  });

  it("freshness wording follows the stage state", () => {
    expect(freshness(STAGES[8])).toBe("Not requested");
    expect(freshness(STAGES[5])).toBe("Retrieving now");
    expect(freshness(STAGES[6])).toBe("Unavailable");
    expect(freshness(STAGES[0])).toMatch(/^Updated /);
  });
});

describe("status strip freshness", () => {
  it("separates heat observed, evidence refreshed and record updated", () => {
    render(<MemoryRouter><InvestigationStatus ev={withStages()} /></MemoryRouter>);
    for (const k of ["Heat last observed", "Evidence refreshed", "Record updated"]) expect(screen.getByText(k)).toBeTruthy();
    expect(screen.queryByText("Last updated")).toBeNull();
    const refreshed = screen.getByText("Evidence refreshed").nextElementSibling!;
    expect(refreshed.querySelector("span")?.getAttribute("title")).toContain("25 Sept 06:00");
  });

  it("shows a dash rather than a record update when no evidence was refreshed", () => {
    const ev = withStages();
    ev.evidence_stages!.freshness.latest_evidence_refresh_at = null;
    render(<MemoryRouter><InvestigationStatus ev={ev} /></MemoryRouter>);
    expect(screen.getByText("Evidence refreshed").nextElementSibling!.textContent).toBe("—");
  });
});
