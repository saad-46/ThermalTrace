/** Raster land cover (ESA WorldCover) and Sentinel-2 spectral change (NDVI / NBR) for an event.
 *  Both are context. Missing data is shown as missing — never as "no vegetation" or "no change". */
import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { fmtDate, fmtDateTime, fmtNum, sharePct } from "../lib/format";
import { actions, useAction } from "../lib/hooks";
import type { EventDetail, ImageryAnalysis, LandCover } from "../lib/types";
import { ActionButton, EvidenceState, errorText, jobFor, pendingLabel, stepPhase, useRequestSteps } from "./enrichment";
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
export const pct = sharePct;

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
        {step?.status === "failed"
          ? `Provider failure: ${errorText(step.category)}. This is not an absence of land cover; the lookup is retried automatically.`
          : step?.status === "ok" || step?.status === "no_data" ? "No WorldCover data at this location (offshore or outside coverage)." : "Land cover has not been retrieved yet."}
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
  vegetation_loss_consistent: "Spectral change is consistent with burning",
  partial_change: "Partial spectral change (inconclusive)",
  no_change_detected: "No burn-consistent spectral change above threshold",
};

const SPECTRAL_MEANING = "NDVI and NBR compare a clear scene before the first detection with one after the last. A drop in both is consistent with burning; it does not prove that a fire occurred or identify its cause, and no change does not rule a fire out.";

export function SpectralChangePanel({ ev }: { ev: EventDetail }) {
  const ia = ev.imagery_analysis;
  const qc = useQueryClient();
  const toast = useToast();
  const run = useAction(actions.imageryAnalysis(ev.public_id), [["jobs"]]);
  const job = jobFor(ev, "imagery_analysis");
  const computing = run.isPending || job?.status === "queued" || job?.status === "running";
  const search = stepPhase(ev, "satellite");
  const req = useRequestSteps(ev, ["satellite"]);
  const ready = ev.imagery_readiness?.ready ?? false;
  const request = async () => {
    try { await run.mutateAsync(undefined); await qc.invalidateQueries({ queryKey: ["event"] }); }
    catch (e) { toast(errText(e), "error"); }
  };
  const compute = (label: string) => (
    <ActionButton onClick={request} busy={computing} busyLabel="Computing…" testId="spectral-compute">{label}</ActionButton>
  );
  if (computing)
    return <EvidenceState tone="busy" title="Computing NDVI / NBR change…" testId="spectral-state">Reading the red, NIR and SWIR bands of the before and after scenes in a 1 km window around the event; {pendingLabel(job)}.</EvidenceState>;
  if (ia?.status === "ok") return <SpectralTable ia={ia} action={ready ? compute("Recompute") : null} />;
  if (!ev.satellite.length) {
    if (search.phase === "pending")
      return <EvidenceState tone="busy" title="Searching Sentinel-2 imagery…" testId="spectral-state">NDVI / NBR can be computed once scenes are found.</EvidenceState>;
    if (search.phase === "failed")
      return (
        <EvidenceState tone="warn" title="Sentinel-2 search failed" testId="spectral-state" meaning={SPECTRAL_MEANING}
          action={<ActionButton onClick={req.run} busy={req.sending} busyLabel="Searching…" testId="spectral-search">Search again</ActionButton>}>
          The imagery search did not complete ({errorText(search.state?.category)}). This is a provider failure, not an absence of imagery.
        </EvidenceState>
      );
    const searched = search.phase === "ok" || search.phase === "no_data";
    return (
      <EvidenceState title={searched ? "No suitable imagery available" : "Needs Sentinel-2 scenes"} testId="spectral-state" meaning={SPECTRAL_MEANING}
        action={<ActionButton onClick={req.run} busy={req.sending} busyLabel="Searching…" testId="spectral-search">{searched ? "Search again" : "Search Sentinel-2 imagery"}</ActionButton>}>
        {searched ? "The imagery search found no scene for this event under the cloud threshold, so there is nothing to compare." : "Imagery has not been searched yet. A before and an after scene are needed."}
      </EvidenceState>
    );
  }
  if (!ready)
    return (
      <EvidenceState title="No suitable imagery available" testId="spectral-state" meaning={SPECTRAL_MEANING}>
        {ev.imagery_readiness?.reason ?? "Before/after analysis cannot be completed with the stored scenes."}
        {(ia?.status === "unavailable" || ia?.status === "failed") && ia.reason ? <> Last attempt ({fmtDate(ia.retrieved_at)}): {ia.reason}</> : null}
      </EvidenceState>
    );
  if (ia?.status === "failed")
    return (
      <EvidenceState tone="warn" title="Sentinel-2 bands could not be read" testId="spectral-state" action={compute("Try again")} meaning={SPECTRAL_MEANING}>
        {ia.reason} (attempted {fmtDate(ia.retrieved_at)}). This is a provider failure, not a finding about the surface.
      </EvidenceState>
    );
  if (ia?.status === "unavailable")
    return (
      <EvidenceState tone="warn" title="Spectral change could not be calculated" testId="spectral-state" action={compute("Recompute")} meaning={SPECTRAL_MEANING}>
        {ia.reason} (attempted {fmtDate(ia.retrieved_at)})
      </EvidenceState>
    );
  if (job?.status === "failed")
    return (
      <EvidenceState tone="warn" title="The last computation did not complete" testId="spectral-state" action={compute("Compute NDVI / NBR change")}>
        The background job stopped with an error{job.error_type ? ` (${job.error_type})` : ""}. No result was stored.
      </EvidenceState>
    );
  return (
    <EvidenceState title="Spectral change has not been computed" testId="spectral-state" action={compute("Compute NDVI / NBR change")} meaning={SPECTRAL_MEANING}>
      Clear scenes exist before and after the event (cloud ≤ {ev.imagery_readiness?.max_cloud ?? 40}%). Computing reads their bands on demand (about 30 s).
    </EvidenceState>
  );
}

export function SpectralTable({ ia, action }: { ia: ImageryAnalysis; action: ReactNode }) {
  const b = ia.before_scene!, a = ia.after_scene!, d = ia.deltas!;
  const cell = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2));
  const delta = (v: number | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}`);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div data-testid="spectral-result"><b>{FINDING_TEXT[ia.finding ?? ""] ?? ia.finding}</b></div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th scope="col">Index</th><th scope="col">Before · {b.acquired_at.slice(0, 10)}</th><th scope="col">After · {a.acquired_at.slice(0, 10)}</th><th scope="col">Change</th></tr></thead>
          <tbody>
            <tr><td>NDVI</td><td className="num">{cell(b.ndvi)}</td><td className="num">{cell(a.ndvi)}</td><td className="num">{delta(d.ndvi)}</td></tr>
            <tr><td>NBR</td><td className="num">{cell(b.nbr)}</td><td className="num">{cell(a.nbr)}</td><td className="num">{delta(d.nbr)}</td></tr>
          </tbody>
        </table>
      </div>
      <dl className="kv" style={{ fontSize: 12 }}>
        <dt>Before scene</dt><dd className="mono" style={{ fontSize: 11 }}>{b.item_id} · {fmtDateTime(b.acquired_at)} · {b.cloud_cover == null ? "cloud n/a" : `${fmtNum(b.cloud_cover, 0)}% tile cloud`}</dd>
        <dt>After scene</dt><dd className="mono" style={{ fontSize: 11 }}>{a.item_id} · {fmtDateTime(a.acquired_at)} · {a.cloud_cover == null ? "cloud n/a" : `${fmtNum(a.cloud_cover, 0)}% tile cloud`}</dd>
        <dt>Computed</dt><dd>{fmtDateTime(ia.retrieved_at)} · Sentinel-2 L2A via Element84 Earth Search</dd>
      </dl>
      <div className="faint" style={{ fontSize: 11.5 }}>
        Mean over usable pixels in a {fmtNum(ia.window_m / 1000, 1)} km window (clouds and shadows masked; {Math.round(b.valid_fraction * 100)}% and {Math.round(a.valid_fraction * 100)}% of pixels usable).
        Thresholds: NDVI change ≤ {ia.method.thresholds?.dndvi}, NBR change ≤ −{ia.method.thresholds?.dnbr} (burning lowers both indices). Vegetation change is supporting evidence only; it does not identify the cause, and no change does not rule out a fire.
      </div>
      <div>{action}</div>
    </div>
  );
}
