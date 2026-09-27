// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ContributionChart } from "../components/charts";
import { PersistenceStrip, PriorityPanel, PriorityPill } from "../components/triage";
import { Boundary, Meter, StatePill } from "../components/ui";
import { event } from "./fixture";

afterEach(cleanup);

describe("triage components", () => {
  it("PriorityPill derives tier from score and explains itself", () => {
    render(<PriorityPill score={72} />);
    const pill = screen.getByTitle(/not a risk assessment/i);
    expect(pill.textContent).toContain("72");
    expect(pill.textContent).toContain("high");
  });

  it("PriorityPanel lists components and the non-risk disclaimer", () => {
    render(<PriorityPanel p={event().priority_components} />);
    expect(screen.getByText("Thermal intensity")).toBeTruthy();
    expect(screen.getByText(/not a risk or threat assessment/i)).toBeTruthy();
  });

  it("PriorityPanel handles events without a computed priority", () => {
    render(<PriorityPanel p={null} />);
    expect(screen.getByText(/not computed/i)).toBeTruthy();
  });

  it("PersistenceStrip shows gap days explicitly", () => {
    render(<PersistenceStrip ev={event()} />);
    const days = screen.getAllByRole("listitem");
    expect(days).toHaveLength(3); // 18, 19 (gap), 20
    expect(days[1].getAttribute("title")).toMatch(/no detection/);
    expect(screen.getByText(/2 of 3 day/)).toBeTruthy();
  });
});

describe("shared ui", () => {
  it("StatePill shows the manual-review hint for insufficient evidence", () => {
    render(<StatePill state="INSUFFICIENT_EVIDENCE" />);
    expect(screen.getByText("Insufficient evidence").getAttribute("title")).toMatch(/manual review/i);
  });

  it("Meter clamps and exposes an ARIA value", () => {
    render(<Meter value={1.7} label="x" />);
    expect(screen.getByRole("meter").getAttribute("aria-valuenow")).toBe("100");
  });

  it("SHAP chart labels features and signs contributions", () => {
    render(<ContributionChart label="shap" items={[{ feature: "dist_oil_gas_km", value: 0.5, contribution: 0.42 }, { feature: "land_cropland", value: 0, contribution: -0.2 }]} />);
    expect(screen.getByText("Dist. to oil/gas")).toBeTruthy();
    expect(screen.getByText("+0.42")).toBeTruthy();
    expect(screen.getByText("-0.20")).toBeTruthy();
  });

  it("Boundary contains a crashing child and offers retry", () => {
    const Boom = () => { throw new Error("WebGL context lost"); };
    const orig = console.error;
    console.error = () => {};
    render(<Boundary label="Map"><Boom /></Boundary>);
    console.error = orig;
    expect(screen.getByRole("alert").textContent).toMatch(/WebGL is unavailable/);
    expect(() => fireEvent.click(screen.getByText("Retry"))).not.toThrow();
  });
});

describe("error states", () => {
  it("names the kind of failure and offers retry only when it can help", async () => {
    const { ApiError } = await import("../lib/api");
    const { ErrorState } = await import("../components/ui");
    const cases: [number, string, boolean][] = [
      [401, "Signed out", false], [403, "Not permitted", false], [404, "Not found", false],
      [400, "Request not accepted", false], [429, "Too many requests", true], [503, "Data source unavailable", true], [500, "Could not load data", true],
    ];
    for (const [status, title, retry] of cases) {
      render(<ErrorState error={new ApiError(status, "x", "message")} retry={() => undefined} />);
      expect(screen.getByText(title)).toBeTruthy();
      expect(!!screen.queryByRole("button", { name: /Retry/ })).toBe(retry);
      cleanup();
    }
  });
});
