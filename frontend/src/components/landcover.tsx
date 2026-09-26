/** Raster land cover (ESA WorldCover) and Sentinel-2 spectral change (NDVI / NBR) for an event.
 *  Both are context. Missing data is shown as missing — never as "no vegetation" or "no change". */
import { fmtDate, fmtNum } from "../lib/format";
import { actions, useAction } from "../lib/hooks";
import { useSession } from "../lib/session";
import type { EventDetail, ImageryAnalysis, LandCover } from "../lib/types";
import { Empty, errText, useToast } from "./ui";

// Official ESA WorldCover legend colours, so the bar matches the published product.
export const WORLDCOVER_META: Record<string, { label: string; color: string }> = {
  tree_cover: { label: "Tree cover", color: "#006400" },
  shrubland: { label: "Shrubland", color: "#ffbb22" },
  grassland: { label: "Grassland", color: "#ffff4c" },
  cropland: { label: "Cropland", color: "#f096ff" },
  built_up: { label: "Built-up", color: "#fa0000" },
  bare_sparse: { label: "Bare / sparse", color: "#b4b4b4" },
  snow_ice: { label: "Snow and ice", color: "#f0f0f0" },
  water: { label: "Water", color: "#0064c8" },
  herbaceous_wetland: { label: "Wetland", color: "#0096a0" },
  mangroves: { label: "Mangroves", color: "#00cf75" },
  moss_lichen: { label: "Moss and lichen", color: "#fae6a0" },
};

/** Share as a percentage; a non-zero share below 0.5 % shows as "<1%" rather than a misleading "0%". */
export const pct = (share: number) => (share > 0 && share < 0.005 ? "<1%" : `${Math.round(share * 100)}%`);

export function landcoverShares(lc: LandCover): { key: string; label: string; color: string; share: number }[] {
  return Object.entries(lc.fractions)
    .map(([key, share]) => ({ key, share, ...(WORLDCOVER_META[key] ?? { label: key, color: "#888" }) }))
    .sort((a, b) => b.share - a.share);
}

export function LandCoverPanel({ ev }: { ev: EventDetail }) {
  const lc = ev.landcover;
  const step = ev.enrichment_state?.landcover;
  if (!lc) {
    return (
      <Empty title="No raster land cover">
        {step?.status === "failed" ? `Provider error: ${step.detail}` : step?.status === "ok" ? "No WorldCover data at this location (offshore or outside coverage)." : "Land cover has not been retrieved yet."}
      </Empty>
    );
  }
  const shares = landcoverShares(lc);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="lc-bar" role="img" aria-label={`Land cover: ${shares.map((s) => `${s.label} ${pct(s.share)}`).join(", ")}`}>
        {shares.map((s) => <span key={s.key} style={{ width: `${s.share * 100}%`, background: s.color }} title={`${s.label} ${pct(s.share)}`} />)}
      </div>
      <ul className="lc-legend">
        {shares.map((s) => (
          <li key={s.key}><i className="swatch" style={{ background: s.color }} />{s.label}<span className="num">{pct(s.share)}</span></li>
        ))}
      </ul>
      <div className="faint" style={{ fontSize: 11.5 }}>
        {lc.product}, {fmtNum(lc.window_m / 1000, 1)} km square around the event, retrieved {fmtDate(lc.retrieved_at)}. The product maps 2021 conditions; land use may have changed since. It is context and does not decide the classification.
      </div>
    </div>
  );
}

const FINDING_TEXT: Record<string, string> = {
  vegetation_loss_consistent: "Vegetation loss consistent with burning",
  partial_change: "Partial change (inconclusive)",
  no_change_detected: "No change above threshold",
};

export function SpectralChangePanel({ ev }: { ev: EventDetail }) {
  const ia = ev.imagery_analysis;
  const { can } = useSession();
  const toast = useToast();
  const run = useAction(actions.imageryAnalysis(ev.public_id), [["jobs"]]);
  const request = async () => {
    try { await run.mutateAsync(undefined); toast("Spectral analysis queued; results appear when the worker finishes"); }
    catch (e) { toast(errText(e), "error"); }
  };
  const button = can("analyst") && (
    <button className="btn sm" onClick={request} disabled={run.isPending || !ev.satellite.length}>
      {run.isPending ? <span className="spinner" /> : null} {ia ? "Recompute" : "Compute"} NDVI / NBR change
    </button>
  );
  if (!ia || ia.status !== "ok") {
    return (
      <div className="stack" style={{ gap: 8 }}>
        <div className="faint" style={{ fontSize: 12 }}>
          {!ia ? (ev.satellite.length ? "Spectral change has not been computed for this event." : "No Sentinel-2 scenes stored yet; run enrichment first.")
            : `Unavailable: ${ia.reason}`}
        </div>
        <div>{button}</div>
      </div>
    );
  }
  return <SpectralTable ia={ia} action={button} />;
}

export function SpectralTable({ ia, action }: { ia: ImageryAnalysis; action: React.ReactNode }) {
  const b = ia.before_scene!, a = ia.after_scene!, d = ia.deltas!;
  const cell = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2));
  const delta = (v: number | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}`);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div><b>{FINDING_TEXT[ia.finding ?? ""] ?? ia.finding}</b></div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th scope="col">Index</th><th scope="col">Before · {b.acquired_at.slice(0, 10)}</th><th scope="col">After · {a.acquired_at.slice(0, 10)}</th><th scope="col">Change</th></tr></thead>
          <tbody>
            <tr><td>NDVI</td><td className="num">{cell(b.ndvi)}</td><td className="num">{cell(a.ndvi)}</td><td className="num">{delta(d.ndvi)}</td></tr>
            <tr><td>NBR</td><td className="num">{cell(b.nbr)}</td><td className="num">{cell(a.nbr)}</td><td className="num">{delta(d.nbr)}</td></tr>
          </tbody>
        </table>
      </div>
      <div className="faint" style={{ fontSize: 11.5 }}>
        Mean over usable pixels in a {fmtNum(ia.window_m / 1000, 1)} km window (clouds and shadows masked; {Math.round(b.valid_fraction * 100)}% and {Math.round(a.valid_fraction * 100)}% of pixels usable).
        Thresholds: NDVI change ≤ {ia.method.thresholds?.dndvi}, NBR change ≥ {ia.method.thresholds?.dnbr}. Vegetation change is supporting evidence only; it does not identify the cause, and no change does not rule out a fire.
      </div>
      <div>{action}</div>
    </div>
  );
}
