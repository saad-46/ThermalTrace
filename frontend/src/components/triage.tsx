/** Triage priority, evidence chain and persistence strip.
 * Prioritisation breakdown, stepwise evidence chain and per-day persistence view, built on the
 * event bundle — real data only. */
import { compass, coordsLabel, fmtDate, fmtDistance, fmtNum, locationLabel } from "../lib/format";
import { CLASS_META, FACILITY_LABELS, SOURCE_NAMES, STATE_META } from "../lib/taxonomy";
import type { EventDetail, PriorityBreakdown } from "../lib/types";
import { Meter } from "./ui";

const TIER_TONE: Record<PriorityBreakdown["tier"], string> = { high: "thermal", elevated: "low", routine: "", low: "insufficient" };
const COMPONENT_LABELS: Record<string, string> = {
  thermal_intensity: "Thermal intensity",
  persistence: "Persistence",
  industrial_proximity: "Industrial proximity",
  classification_confidence: "Classification confidence",
  sensor_corroboration: "Sensor corroboration",
};

export function PriorityPill({ score, tier }: { score: number | null | undefined; tier?: PriorityBreakdown["tier"] }) {
  if (score == null) return <span className="faint">—</span>;
  const t = tier ?? (score >= 70 ? "high" : score >= 50 ? "elevated" : score >= 30 ? "routine" : "low");
  return (
    <span className={`pill ${TIER_TONE[t]}`} title="Triage priority: orders the review queue; not a risk assessment">
      <span className="num">{Math.round(score)}</span> {t}
    </span>
  );
}

/** "Why is this event prioritised?" */
export function PriorityPanel({ p }: { p: PriorityBreakdown | null }) {
  if (!p) return <div className="faint">Priority not computed yet.</div>;
  return (
    <div className="stack" style={{ gap: 7 }}>
      {p.components.map((c) => (
        <div key={c.name} title={c.detail}>
          <div className="row" style={{ justifyContent: "space-between", fontSize: 12 }}>
            <span>{COMPONENT_LABELS[c.name] ?? c.name}</span>
            <span className="num mono">+{fmtNum(c.points, 1)} / {c.max}</span>
          </div>
          <Meter value={c.points / c.max} tone="thermal" label={COMPONENT_LABELS[c.name]} />
          <div className="faint" style={{ fontSize: 11.5 }}>{c.detail}</div>
        </div>
      ))}
      <div className="divider" />
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="muted">Triage priority</span>
        <PriorityPill score={p.score} tier={p.tier} />
      </div>
      <div className="faint" style={{ fontSize: 11.5 }}>{p.note} Tiers: high ≥ 70 · elevated ≥ 50 · routine ≥ 30.</div>
    </div>
  );
}

/** State of one stage: evidence present, checked and nothing found, or not available (not retrieved / failed). */
export type StageState = "ok" | "neutral" | "missing";
export type Stage = {
  key: string;
  title: string;
  summary: string;
  detail: string;
  state: StageState;
  /** Where the stage's evidence comes from (dataset, provider or process). */
  source: string;
  /** What this stage adds to the assessment, stated with its limits. */
  contribution: string;
  /** When the evidence was observed or retrieved, if known. */
  at: string | null;
};

export const STAGE_STATE_LABEL: Record<StageState, string> = { ok: "Available", neutral: "Checked · none found", missing: "Unavailable" };

const signed = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;

/** "How ThermalTrace thinks": the evidence progression for one event, from the thermal detection to its current
 *  status. Every stage is derived from fields of the real event bundle; missing evidence is reported as missing. */
export function buildEvidenceChain(ev: EventDetail): Stage[] {
  const es = ev.enrichment_state ?? {};
  const top = ev.facilities[0];
  const pm = ev.persistence_metrics;
  const best = ev.satellite.length
    ? ev.satellite.reduce((a, b) => ((a.cloud_cover ?? 101) <= (b.cloud_cover ?? 101) ? a : b))
    : null;
  const land = [...new Set(ev.land.map((l) => l.category))];
  const osmChecked = es.osm?.status === "ok";
  const w = ev.weather[0];
  const lc = ev.landcover;
  const lcTop = lc ? Object.entries(lc.fractions).sort((a, b) => b[1] - a[1]).slice(0, 2) : [];
  const ia = ev.imagery_analysis;
  const pred = ev.predictions.find((p) => p.model_version_id === ev.classification_current?.primary_model_id) ?? ev.predictions[0];
  const explanation = pred?.explanation;
  const supports = ev.evidence.filter((e) => e.direction === "supports").length;
  const contradicts = ev.evidence.filter((e) => e.direction === "contradicts").length;
  const lastReview = ev.reviews[0];
  const insufficient = ev.display_state === "INSUFFICIENT_EVIDENCE";

  return [
    { key: "detection", title: "Thermal detection", state: "ok",
      summary: `${ev.observation_count} FIRMS detection(s) · ${ev.sensor_count} platform(s)`,
      detail: `Peak FRP ${fmtNum(ev.frp_max)} MW; ${ev.sensors.join(", ")}.`,
      source: "NASA FIRMS (MODIS / VIIRS active fire)", at: ev.last_detected,
      contribution: "Heat was observed at this place. A detection alone does not say what caused it." },
    { key: "clustering", title: "Event clustering", state: "ok",
      summary: `${ev.observation_count} detection(s) over ${ev.days_active} active day(s)`,
      detail: `Nearby detections in space and time are grouped into one event (${fmtDate(ev.first_detected)} to ${fmtDate(ev.last_detected)}).`,
      source: `ThermalTrace processing${ev.processing_version ? ` ${ev.processing_version}` : ""}`, at: ev.processed_at,
      contribution: "Turns individual pixels into one event that can be analysed and reviewed." },
    { key: "location", title: "Spatial context", state: osmChecked || land.length ? "ok" : es.osm?.status === "failed" ? "missing" : locationLabel(ev) ? "neutral" : "missing",
      summary: [locationLabel(ev), coordsLabel(ev)].filter(Boolean).join(" · "),
      detail: land.length ? `Mapped land use nearby: ${land.join(", ")}.` : osmChecked ? "No farmland, forest or residential land use mapped within 1.5 km." : es.osm?.status === "failed" ? "Land-use lookup failed; it will be retried." : "Land use not yet retrieved.",
      source: "GeoNames places · OpenStreetMap land use", at: es.osm?.at ?? null,
      contribution: "Places the heat among what is mapped around it. Mapping can be incomplete." },
    { key: "facility", title: "Facility attribution", state: top ? "ok" : osmChecked ? "neutral" : "missing",
      summary: top ? `${top.name ?? "Unnamed"} — ${fmtDistance(top.distance_m)}` : osmChecked ? "No mapped facility within 10 km" : "Not yet retrieved",
      detail: top ? `${FACILITY_LABELS[top.facility_type] ?? top.facility_type}, ${top.bearing_deg != null ? compass(top.bearing_deg) + " of event, " : ""}attribution ${top.attribution_score.toFixed(2)}.` : "Absence may reflect incomplete mapping.",
      source: top ? `${SOURCE_NAMES[top.primary_source] ?? top.primary_source}${top.source_count > 1 ? ` + ${top.source_count - 1} other source(s)` : ""}` : "OpenStreetMap, WRI, Global Energy Monitor",
      at: es.osm?.at ?? null,
      contribution: "Proximity is supporting evidence for attribution, not proof that the facility caused the heat." },
    { key: "landcover", title: "Land cover", state: lc ? "ok" : es.landcover?.status === "ok" ? "neutral" : "missing",
      summary: lc ? lcTop.map(([k, v]) => `${k.replace(/_/g, " ")} ${Math.round(v * 100)}%`).join(" · ") : es.landcover?.status === "ok" ? "No data at this location" : "Not yet retrieved",
      detail: lc ? `ESA WorldCover 2021, ${fmtNum(lc.window_m / 1000, 1)} km window.` : "",
      source: "ESA WorldCover 10 m (2021)", at: lc?.retrieved_at ?? es.landcover?.at ?? null,
      contribution: "Context only: cropland supports agricultural burning, built-up or bare ground supports industry. It does not decide the class." },
    { key: "persistence", title: "Temporal persistence", state: pm ? "ok" : "missing",
      summary: pm ? `${pm.persistence_class} · ${pm.active_days} of ${pm.span_days} day(s)` : "Not computed",
      detail: pm ? `${pm.rationale}.` : "",
      source: "Derived from the event's daily FIRMS observations", at: ev.last_detected,
      contribution: "Repeated detections over days suggest sustained activity; a single one is an isolated observation." },
    { key: "satellite", title: "Imagery and spectral change",
      state: ia?.status === "ok" ? "ok" : best ? "neutral" : "missing",
      summary: ia?.status === "ok" && ia.deltas
        ? `NDVI ${signed(ia.deltas.ndvi)} · NBR ${signed(ia.deltas.nbr)} (${(ia.finding ?? "").replace(/_/g, " ")})`
        : best ? `Sentinel-2 ${fmtDate(best.acquired_at)} · ${fmtNum(best.cloud_cover, 0)}% cloud` : "No scene available",
      detail: ia?.status === "ok"
        ? "Consistent with burning, not proof of burning."
        : ia ? `Spectral change unavailable: ${ia.reason ?? "no usable clear scene"}.`
        : best ? "A scene is available for visual comparison; no before/after analysis has been run." : es.satellite ? "No L2A scene under the cloud threshold." : "Imagery not yet searched.",
      source: "Copernicus Sentinel-2 L2A", at: ia?.retrieved_at ?? best?.acquired_at ?? null,
      contribution: "A drop in NDVI and NBR is consistent with burned vegetation. No change does not rule out a fire." },
    { key: "weather", title: "Weather context", state: w ? "ok" : "missing",
      summary: w ? `${w.condition ?? "—"}, wind ${fmtNum(w.wind_speed_ms)} m/s from ${compass(w.wind_direction_deg)}` : "Not available",
      detail: w ? `${w.dataset}.` : "",
      source: "Open-Meteo", at: w?.observed_at ?? null,
      contribution: "Context only; weather is never evidence of the source." },
    { key: "classification", title: "Classification", state: ev.classification && ev.classification !== "unknown" ? "ok" : "missing",
      summary: ev.classification ? CLASS_META[ev.classification].label : "Unprocessed",
      detail: `Probability ${fmtNum(ev.classification_probability, 2)} from ${ev.classification_current?.primary_model_id ?? "—"}.`,
      source: ev.classification_current?.primary_model_id ?? "Not classified yet", at: ev.classification_current?.created_at ?? null,
      contribution: "The most consistent explanation for the evidence above. It is an assessment, not a verified fact." },
    { key: "confidence", title: "Confidence", state: insufficient ? "missing" : "ok",
      summary: `${STATE_META[ev.display_state].label} · ${fmtNum(ev.confidence_score, 2)}`,
      detail: insufficient
        ? "Insufficient evidence — manual review required."
        : ev.confidence_components?.missing.length ? `Missing: ${ev.confidence_components.missing.join(", ")}.` : "No evidence flagged as missing.",
      source: "Confidence components (model, context, persistence, sensors, imagery, data quality)", at: ev.classification_current?.created_at ?? null,
      contribution: "Reflects how much available evidence supports the classification. It is not the probability of a fire." },
    { key: "explainability", title: "Explainability", state: explanation || ev.evidence.length ? "ok" : "missing",
      summary: explanation
        ? explanation.kind === "shap" ? `SHAP contributions for ${explanation.contributions.length} feature(s)` : `Rule trace · ${explanation.trace.length} step(s)`
        : ev.evidence.length ? `${ev.evidence.length} evidence item(s)` : "No explanation recorded",
      detail: ev.evidence.length ? `${supports} supporting, ${contradicts} contradicting evidence item(s).` : "",
      source: explanation?.kind === "shap" ? "SHAP (trained model)" : "Rule cascade trace", at: pred?.created_at ?? null,
      contribution: explanation?.kind === "shap"
        ? "SHAP explains each feature's contribution to the model output; it does not prove causation."
        : "Shows which rules fired and why; it explains the decision, not the real-world cause." },
    { key: "review", title: "Human review", state: lastReview ? "ok" : "missing",
      summary: lastReview ? `${lastReview.decision.replace(/_/g, " ")}${lastReview.reviewer ? ` by ${lastReview.reviewer}` : ""}` : "Not reviewed yet",
      detail: lastReview?.notes ?? (lastReview ? "" : "An analyst decision is required before this event can be confirmed."),
      source: "Analyst review (audited)", at: lastReview?.created_at ?? null,
      contribution: "The only step that can confirm or reject the assessment, together with imagery confirmation." },
    { key: "status", title: "Current status", state: ["CONFIRMED", "ANALYST_CONFIRMED", "ANALYST_REJECTED"].includes(ev.display_state) ? "ok" : "neutral",
      summary: STATE_META[ev.display_state].label,
      detail: STATE_META[ev.display_state].hint + ".",
      source: "Classification state and review status", at: lastReview?.created_at ?? ev.classification_current?.created_at ?? null,
      contribution: "Confirmed only after imagery confirmation or analyst review." },
  ];
}

export function EvidenceChain({ ev }: { ev: EventDetail }) {
  const stages = buildEvidenceChain(ev);
  return (
    <div>
      <p className="faint" style={{ fontSize: 12, margin: "0 0 8px" }}>
        How ThermalTrace reached its assessment, stage by stage. Supporting evidence, not proof; unavailable evidence is shown as unavailable, never as negative.
      </p>
      <ol className="chain" aria-label="Evidence chain">
        {stages.map((s) => (
          <li key={s.key} className={`chain-step ${s.state}`}>
            <div className="chain-title">{s.title} <span className={`chain-state ${s.state}`}>{STAGE_STATE_LABEL[s.state]}</span></div>
            <div className="chain-summary">{s.summary}</div>
            {s.detail && <div className="chain-detail">{s.detail}</div>}
            <div className="chain-contribution">{s.contribution}</div>
            <div className="chain-meta">{s.source}{s.at ? ` · ${fmtDate(s.at)}` : ""}</div>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** One cell per day of the event span: detected (with count) or not — makes gaps visible. */
export function PersistenceStrip({ ev }: { ev: EventDetail }) {
  if (!ev.observations.length) return null;
  const byDay = new Map(ev.observations.map((o) => [o.obs_date, o]));
  const start = new Date(`${ev.observations[0].obs_date}T00:00:00Z`);
  const end = new Date(`${ev.observations[ev.observations.length - 1].obs_date}T00:00:00Z`);
  const days: string[] = [];
  for (let d = new Date(start); d <= end && days.length < 120; d.setUTCDate(d.getUTCDate() + 1)) days.push(d.toISOString().slice(0, 10));
  return (
    <div>
      <div className="strip" role="list" aria-label="Detections per day">
        {days.map((d) => {
          const o = byDay.get(d);
          return (
            <div key={d} role="listitem" className={`strip-day ${o ? "on" : ""}`}
              title={o ? `${d}: ${o.detection_count} detection(s), peak ${fmtNum(o.frp_max)} MW, ${o.sensors.join(", ")}` : `${d}: no detection`}>
              <span className="strip-cell">{o ? o.detection_count : ""}</span>
              <span className="strip-label">{d.slice(8)}</span>
            </div>
          );
        })}
      </div>
      <div className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>
        {byDay.size} of {days.length} day(s) with detections · cells show detections per UTC day
      </div>
    </div>
  );
}
