// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LandCoverPanel, landcoverShares, SpectralTable } from "../components/landcover";
import type { ImageryAnalysis, LandCover } from "../lib/types";
import { event } from "./fixture";

afterEach(cleanup);

const WC: LandCover = {
  product: "ESA WorldCover 10 m 2021 v200", window_m: 1500, fractions: { cropland: 0.93, tree_cover: 0.04, built_up: 0.03 },
  dominant: "cropland", valid_fraction: 1, source_ref: "https://example/tile.tif", retrieved_at: "2026-09-26T04:14:45Z",
};

const IA: ImageryAnalysis = {
  status: "ok", reason: null, finding: "vegetation_loss_consistent", window_m: 1000,
  before_scene: { item_id: "S2B_43RDQ_20260918_0_L2A", acquired_at: "2026-09-18T05:00:00Z", cloud_cover: 3, ndvi: 0.86, nbr: 0.68, valid_fraction: 0.95 },
  after_scene: { item_id: "S2C_43RDQ_20261003_0_L2A", acquired_at: "2026-10-03T05:00:00Z", cloud_cover: 5, ndvi: 0.41, nbr: 0.2, valid_fraction: 0.9 },
  deltas: { ndvi: -0.45, nbr: -0.48 }, method: { thresholds: { dndvi: -0.1, dnbr: 0.1 } }, retrieved_at: "2026-10-04T00:00:00Z",
};

describe("land cover", () => {
  it("orders shares and uses the WorldCover legend", () => {
    const s = landcoverShares(WC);
    expect(s.map((x) => x.key)).toEqual(["cropland", "tree_cover", "built_up"]);
    expect(s[0].label).toBe("Cropland");
  });

  it("renders shares, product, date and the context-only caveat", () => {
    render(<LandCoverPanel ev={event({ landcover: WC, enrichment_state: { landcover: { status: "ok", at: "", detail: null } } })} />);
    expect(screen.getByRole("img", { name: /Cropland 93%/ })).toBeTruthy();
    expect(screen.getByText(/does not decide the classification/)).toBeTruthy();
  });

  it("distinguishes not retrieved, provider failure and no data", () => {
    render(<LandCoverPanel ev={event({ landcover: null, enrichment_state: {} })} />);
    expect(screen.getByText(/not been retrieved yet/)).toBeTruthy();
    cleanup();
    render(<LandCoverPanel ev={event({ landcover: null, enrichment_state: { landcover: { status: "failed", at: "", detail: "timeout", category: "timeout" } } })} />);
    expect(screen.getByText(/Provider failure: the provider timed out\. This is not an absence of land cover/)).toBeTruthy();
    cleanup();
    render(<LandCoverPanel ev={event({ landcover: null, enrichment_state: { landcover: { status: "no_data", at: "", detail: null } } })} />);
    expect(screen.getByText(/offshore or outside coverage/)).toBeTruthy();
    cleanup();
    render(<LandCoverPanel ev={event({ landcover: null, enrichment_state: { landcover: { status: "ok", at: "", detail: null } } })} />);
    expect(screen.getByText(/offshore or outside coverage/)).toBeTruthy();
  });
});

describe("spectral change", () => {
  it("shows both indices, dates, masking and the not-proof caveat", () => {
    render(<SpectralTable ia={IA} action={null} />);
    expect(screen.getByText("Spectral change is consistent with burning")).toBeTruthy();
    expect(screen.getByText("-0.45")).toBeTruthy();
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toContain("Before · 2026-09-18");
    expect(screen.getByText(/does not identify the cause, and no change does not rule out a fire/)).toBeTruthy();
  });

});

describe("share formatting", () => {
  it("never shows a present class as 0%", async () => {
    const { pct } = await import("../components/landcover");
    expect(pct(0.0044)).toBe("<1%");
    expect(pct(0)).toBe("0%");
    expect(pct(0.93)).toBe("93%");
  });
});
