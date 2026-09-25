import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { compass, fmtDate, fmtDateTime, fmtDistance, fmtNum, fmtPct, relTime, titleCase } from "../lib/format";
import { CLASS_META, FACILITY_LABELS, KNOWLEDGE_LABELS, SOURCE_NAMES } from "../lib/taxonomy";
import type { EventDetail, EventSummary, Evidence } from "../lib/types";
import { ContributionChart, EvolutionChart } from "./charts";
import { PersistenceStrip } from "./triage";
import { ClassLabel, Empty, Meter, PersistencePill, StatePill } from "./ui";

const DIR_MARK: Record<Evidence["direction"], string> = { supports: "+", contradicts: "−", neutral: "·", missing: "?" };
const COMPONENT_LABELS: Record<string, string> = {
  model_probability: "Model probability", model_agreement: "Model agreement", context_support: "Context support",
  temporal_consistency: "Temporal consistency", sensor_agreement: "Sensor agreement", satellite: "Satellite imagery",
  weather: "Weather context", data_quality: "Data quality",
};

/** The product's core question set, answered in one block. */
export function AnswerGrid({ ev }: { ev: EventDetail }) {
  const top = ev.facilities[0];
  const pm = ev.persistence_metrics;
  const missing = ev.confidence_components?.missing ?? [];
  const lastReview = ev.reviews[0];
  return (
    <dl className="kv">
      <dt>Where</dt>
      <dd>{[ev.admin_district, ev.admin_state].filter(Boolean).join(", ") || <span className="faint">Not geocoded</span>}
        <span className="faint mono"> {ev.latitude.toFixed(4)}, {ev.longitude.toFixed(4)}</span></dd>
      <dt>When</dt>
      <dd>{fmtDateTime(ev.first_detected)} → {fmtDateTime(ev.last_detected)}</dd>
      <dt>How long</dt>
      <dd>{pm ? `${pm.active_days} active day(s) over ${pm.span_days}; ${pm.recurrence_pattern}` : `${ev.days_active} day(s)`}</dd>
      <dt>What type</dt>
      <dd><ClassLabel cls={ev.classification} /> · <PersistencePill p={ev.persistence_class} /></dd>
      <dt>Nearby facility</dt>
      <dd>{top ? <>{fmtDistance(top.distance_m)} {top.bearing_deg != null ? compass(top.bearing_deg) : ""} — {top.name ?? "unnamed"} ({FACILITY_LABELS[top.facility_type] ?? top.facility_type})</> : <span className="faint">None mapped within 10 km</span>}</dd>
      <dt>Satellite</dt>
      <dd>{ev.satellite.length ? `${ev.satellite.length} Sentinel-2 scene(s), clearest ${fmtNum(Math.min(...ev.satellite.map((s) => s.cloud_cover ?? 100)), 0)}% cloud` : <span className="faint">{ev.enrichment_state?.satellite ? "No suitable scene" : "Not yet searched"}</span>}</dd>
      <dt>Weather</dt>
      <dd>{ev.weather[0] ? `${ev.weather[0].condition ?? "—"}, wind ${fmtNum(ev.weather[0].wind_speed_ms)} m/s from ${compass(ev.weather[0].wind_direction_deg)}` : <span className="faint">Not available</span>}</dd>
      <dt>Confidence</dt>
      <dd><StatePill state={ev.display_state} /> <span className="num">{fmtNum(ev.confidence_score, 2)}</span></dd>
      <dt>Missing</dt>
      <dd>{missing.length ? missing.join(", ") : <span className="faint">Nothing flagged</span>}</dd>
      <dt>Analyst</dt>
      <dd>{lastReview ? `${titleCase(lastReview.decision)} by ${lastReview.reviewer ?? "analyst"}, ${relTime(lastReview.created_at)}` : <span className="faint">No decision yet</span>}</dd>
    </dl>
  );
}

const MISSING_TO_COMPONENT: Record<string, string> = {
  "satellite imagery": "satellite", weather: "weather", "land context": "context_support", "trained model": "model_agreement",
};

/** Qualitative reading of a component, so analysts see "Strong / Weak / Unavailable" rather than only a number. */
export function qualitative(name: string, value: number, missing: string[]): "Strong" | "Moderate" | "Weak" | "Unavailable" {
  if (missing.some((m) => MISSING_TO_COMPONENT[m] === name)) return "Unavailable";
  return value >= 0.7 ? "Strong" : value >= 0.4 ? "Moderate" : "Weak";
}

export function ConfidenceBreakdown({ ev }: { ev: EventDetail }) {
  const c = ev.confidence_components;
  if (!c) return <Empty title="Not yet scored" />;
  return (
    <div className="stack" style={{ gap: 7 }}>
      {c.components.map((k) => (
        <div key={k.name} title={k.explanation}>
          <div className="row" style={{ fontSize: 12, justifyContent: "space-between" }}>
            <span>{COMPONENT_LABELS[k.name] ?? k.name} <span className="faint">×{k.weight.toFixed(2)}</span></span>
            <span className="row" style={{ gap: 8 }}>
              <span className={`qual ${qualitative(k.name, k.value, c.missing).toLowerCase()}`}>{qualitative(k.name, k.value, c.missing)}</span>
              <span className="num mono">{k.value.toFixed(2)}</span>
            </span>
          </div>
          <Meter value={k.value} tone={k.value >= 0.7 ? "info" : k.value >= 0.4 ? "" : "warn"} label={COMPONENT_LABELS[k.name]} />
          <div className="faint" style={{ fontSize: 11.5 }}>{k.explanation}</div>
        </div>
      ))}
      <div className="divider" />
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="muted">Weighted score</span>
        <span className="num" style={{ fontWeight: 600 }}>{c.score.toFixed(2)}</span>
      </div>
      <div className="faint" style={{ fontSize: 11.5 }}>
        Thresholds: &lt;0.40 insufficient · &lt;0.55 low · &lt;0.72 moderate · ≥0.72 high. "Confirmed" additionally requires multi-sensor, context and an imagery check.
      </div>
    </div>
  );
}

export function EvidenceMatrix({ ev }: { ev: EventDetail }) {
  return (
    <table className="table matrix">
      <thead><tr><th scope="col">Evidence</th><th scope="col">Availability</th><th scope="col" style={{ width: 90 }}>Strength</th><th scope="col">Detail</th></tr></thead>
      <tbody>
        {ev.evidence_matrix.map((r) => (
          <tr key={r.type}>
            <td>{r.type}</td>
            <td><span className={`pill ${r.availability === "available" ? "live" : r.availability === "failed" ? "rejected" : ""}`}>{r.availability}</span></td>
            <td><Meter value={r.strength} tone={r.strength >= 0.7 ? "info" : r.strength > 0.3 ? "" : "warn"} label={`${r.type} strength`} /></td>
            <td className="muted" style={{ fontSize: 12 }}>{r.detail}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function EvidenceList({ items, compact }: { items: Evidence[]; compact?: boolean }) {
  if (!items.length) return <Empty title="No evidence recorded" />;
  return (
    <div>
      {items.map((e, i) => (
        <div className="ev" key={i}>
          <span className={`mark ${e.direction}`} title={e.direction} aria-label={e.direction}>{DIR_MARK[e.direction]}</span>
          <div>
            <div style={{ fontSize: compact ? 12.5 : 13 }}>{e.statement}</div>
            <div className="meta">
              <span className="tag">{KNOWLEDGE_LABELS[e.knowledge_type]}</span>
              <span>{e.category}</span>
              {e.provenance && typeof e.provenance.source === "string" && <span>· {SOURCE_NAMES[e.provenance.source as string] ?? (e.provenance.source as string)}</span>}
              {e.provenance && typeof e.provenance.dataset === "string" && <span>· {e.provenance.dataset as string}</span>}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function Fingerprint({ ev }: { ev: EventDetail }) {
  const f = ev.fingerprint;
  if (!f) return null;
  const dims: [string, number | null, string][] = [
    ["Intensity", f.intensity as number, "log-scaled peak FRP"],
    ["Persistence", f.persistence as number, "persistence score"],
    ["Sensor agreement", f.sensor_agreement as number, "platforms / 5"],
    ["Facility proximity", f.facility_proximity as number, "exp(−distance / 1.5 km)"],
    ["Recurrence", f.recurrence as number, "earlier events at this site"],
    ["Night share", f.night_share as number, "share of night detections"],
  ];
  return (
    <div>
      <div className="stack" style={{ gap: 5 }}>
        {dims.map(([k, v, hint]) => (
          <div key={k} style={{ display: "grid", gridTemplateColumns: "118px 1fr 34px", gap: 8, alignItems: "center", fontSize: 12 }} title={hint}>
            <span className="muted">{k}</span>
            <Meter value={v ?? 0} tone="thermal" label={k} />
            <span className="num mono" style={{ textAlign: "right" }}>{v == null ? "—" : v.toFixed(2)}</span>
          </div>
        ))}
      </div>
      <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>
        {f.facility_type ? `Nearest context: ${FACILITY_LABELS[f.facility_type as string] ?? f.facility_type}. ` : "No facility context. "}
        {Array.isArray(f.land) && f.land.length ? `Land use: ${(f.land as string[]).join(", ")}.` : ""}
      </div>
    </div>
  );
}

export function FacilityList({ ev }: { ev: EventDetail }) {
  if (!ev.facilities.length)
    return <Empty title="No mapped facility within 10 km">{ev.enrichment_state?.osm?.status === "ok" ? "OpenStreetMap and loaded registries were checked. Absence may reflect incomplete mapping." : "Infrastructure context has not been retrieved yet."}</Empty>;
  return (
    <table className="table">
      <thead><tr><th scope="col">Facility</th><th scope="col" className="right">Distance</th><th scope="col" className="right">Attribution</th><th scope="col">Sources</th></tr></thead>
      <tbody>
        {ev.facilities.map((f) => (
          <tr key={f.id}>
            <td>
              <div style={{ fontWeight: 500 }}><Link to={`/facilities/${f.id}`}>{f.name ?? "Unnamed"}</Link></div>
              <div className="faint" style={{ fontSize: 11.5 }}>
                {FACILITY_LABELS[f.facility_type] ?? f.facility_type}{f.capacity_value ? ` · ${fmtNum(f.capacity_value, 0)} ${f.capacity_unit}` : ""}{f.operator ? ` · ${f.operator}` : ""}{f.status ? ` · ${f.status}` : ""}
              </div>
            </td>
            <td className="right num">{fmtDistance(f.distance_m)} {f.bearing_deg != null ? compass(f.bearing_deg) : ""}</td>
            <td className="right"><span className="num">{f.attribution_score.toFixed(2)}</span></td>
            <td style={{ fontSize: 11.5 }}>{[...new Set((f.sources ?? []).map((s) => SOURCE_NAMES[s.source] ?? s.source))].join(", ")}<div className="faint">conf. {f.confidence.toFixed(2)}</div></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function PersistencePanel({ ev }: { ev: EventDetail }) {
  const pm = ev.persistence_metrics;
  const days = ev.observations.map((o) => ({ date: o.obs_date, count: o.detection_count, frp: o.frp_max, sensors: o.sensors.length }));
  return (
    <div className="stack" style={{ gap: 12 }}>
      {pm && (
        <>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <PersistencePill p={pm.persistence_class} />
            <span className="muted">Persistence score <b className="num">{pm.score.toFixed(2)}</b></span>
          </div>
          <div className="muted" style={{ fontSize: 12.5 }}>{pm.rationale}.</div>
          <dl className="kv">
            <dt>First seen</dt><dd>{fmtDateTime(ev.first_detected)}</dd>
            <dt>Last seen</dt><dd>{fmtDateTime(ev.last_detected)}</dd>
            <dt>Observations</dt><dd className="num">{ev.observation_count}</dd>
            <dt>Active days</dt><dd className="num">{pm.active_days} of {pm.span_days} (frequency {fmtPct(pm.observation_frequency)})</dd>
            <dt>Longest gap</dt><dd className="num">{pm.longest_gap_days} day(s)</dd>
            <dt>FRP variability</dt><dd className="num">{pm.frp_cv == null ? "n/a (< 3 days)" : `CV ${pm.frp_cv}`}</dd>
            <dt>Repeat site</dt><dd className="num">{pm.recurrence_count} earlier event(s) within 1.5 km (365 d)</dd>
            <dt>Pattern</dt><dd>{pm.recurrence_pattern}</dd>
            <dt>History depth</dt><dd className="num">{pm.history_window_days} day(s) of FIRMS data loaded</dd>
          </dl>
        </>
      )}
      <div><h4 style={{ marginBottom: 6 }}>Detections by day</h4><PersistenceStrip ev={ev} /></div>
      <div><h4 style={{ marginBottom: 6 }}>Event evolution</h4><EvolutionChart days={days} /></div>
    </div>
  );
}

export function Provenance({ ev }: { ev: EventDetail }) {
  const rows: { what: string; source: string; dataset: string; observed: string; retrieved: string }[] = [];
  const bySet = new Map<string, { n: number; first: string; last: string; retrieved: string }>();
  for (const d of ev.detections) {
    const cur = bySet.get(d.dataset);
    if (!cur) bySet.set(d.dataset, { n: 1, first: d.acq_datetime, last: d.acq_datetime, retrieved: d.retrieved_at });
    else { cur.n++; cur.last = d.acq_datetime > cur.last ? d.acq_datetime : cur.last; cur.retrieved = d.retrieved_at > cur.retrieved ? d.retrieved_at : cur.retrieved; }
  }
  for (const [ds, v] of bySet) rows.push({ what: `${v.n} thermal detection(s)`, source: "NASA FIRMS", dataset: ds.replace(/_/g, " "), observed: `${fmtDateTime(v.first)} – ${fmtDateTime(v.last)}`, retrieved: fmtDateTime(v.retrieved) });
  for (const f of ev.facilities.slice(0, 5))
    for (const s of f.sources ?? [])
      rows.push({ what: `Facility: ${f.name ?? "unnamed"}`, source: SOURCE_NAMES[s.source] ?? s.source, dataset: s.dataset_version ?? "—", observed: s.published_at ? `published ${fmtDate(s.published_at)}` : "—", retrieved: fmtDateTime(s.retrieved_at) });
  for (const w of ev.weather) rows.push({ what: "Weather at last detection", source: "Open-Meteo", dataset: w.dataset, observed: fmtDateTime(w.observed_at), retrieved: fmtDateTime(w.retrieved_at) });
  for (const s of ev.satellite) rows.push({ what: `Sentinel-2 scene (${s.relation})`, source: s.provider === "earth-search" ? "Copernicus Sentinel-2 via Earth Search" : "Copernicus Data Space", dataset: `${s.collection} ${s.item_id}`, observed: fmtDateTime(s.acquired_at), retrieved: fmtDateTime(s.retrieved_at) });
  if (ev.land.length) rows.push({ what: `${ev.land.length} land-use feature(s)`, source: "OpenStreetMap (Overpass)", dataset: "live OSM", observed: "—", retrieved: fmtDateTime(ev.land[0].retrieved_at) });
  const cls = ev.classification_current;
  if (cls) rows.push({ what: "Classification", source: "ThermalTrace", dataset: `${cls.primary_model_id} · ${cls.pipeline_version}`, observed: "—", retrieved: fmtDateTime(cls.created_at) });
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr><th scope="col">Information</th><th scope="col">Source</th><th scope="col">Dataset / version</th><th scope="col">Observed</th><th scope="col">Retrieved</th></tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}><td>{r.what}</td><td>{r.source}</td><td className="mono" style={{ fontSize: 11.5 }}>{r.dataset}</td><td className="num" style={{ fontSize: 12 }}>{r.observed}</td><td className="num" style={{ fontSize: 12 }}>{r.retrieved}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

export function ModelPanel({ ev }: { ev: EventDetail }) {
  const rule = ev.predictions.find((p) => p.explanation?.kind === "rule_trace");
  const gbm = ev.predictions.find((p) => p.explanation?.kind === "shap");
  const primary = ev.classification_current?.primary_model_id;
  return (
    <div className="stack" style={{ gap: 14 }}>
      {rule && (
        <div>
          <h4 style={{ marginBottom: 6 }}>Rule cascade · {rule.model_version_id}{primary === rule.model_version_id ? " · primary" : ""}</h4>
          <div className="row" style={{ marginBottom: 6 }}><ClassLabel cls={rule.prediction} /><span className="num muted">p = {rule.probability.toFixed(2)}</span></div>
          <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12.5 }}>{rule.explanation?.trace.map((t, i) => <li key={i}>{t}</li>)}</ol>
          {rule.explanation?.notes.map((n) => <div key={n} className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>{n}</div>)}
        </div>
      )}
      {gbm ? (
        <div>
          <h4 style={{ marginBottom: 6 }}>Gradient boosting · {gbm.model_version_id}{primary === gbm.model_version_id ? " · primary" : ""}</h4>
          <div className="row" style={{ marginBottom: 8 }}><ClassLabel cls={gbm.prediction} /><span className="num muted">p = {gbm.probability.toFixed(2)}</span></div>
          <div className="label-sm" style={{ marginBottom: 6 }}>Model evidence (SHAP) — why the model leaned this way. Not causal proof.</div>
          <ContributionChart items={gbm.explanation?.contributions ?? []} label="SHAP contributions" />
          <ProbBars probs={gbm.probabilities} />
        </div>
      ) : (
        <div className="faint" style={{ fontSize: 12.5 }}>No trained model is active yet, so no SHAP explanation is available. The rule cascade above is the classifier of record.</div>
      )}
    </div>
  );
}

function ProbBars({ probs }: { probs: Record<string, number> }) {
  const rows = Object.entries(probs).sort((a, b) => b[1] - a[1]).slice(0, 5);
  return (
    <div className="stack" style={{ gap: 4, marginTop: 10 }}>
      <div className="label-sm">Class probabilities</div>
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "grid", gridTemplateColumns: "140px 1fr 40px", gap: 8, alignItems: "center", fontSize: 12 }}>
          <span>{CLASS_META[k as keyof typeof CLASS_META]?.short ?? k}</span>
          <div className="meter"><i style={{ width: `${v * 100}%`, background: CLASS_META[k as keyof typeof CLASS_META]?.color }} /></div>
          <span className="num mono" style={{ textAlign: "right" }}>{v.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}

export function Timeline({ ev }: { ev: EventDetail }) {
  return (
    <div className="tl">
      {ev.timeline.map((t, i) => (
        <div key={i} className={`tl-item ${t.kind}`}>
          <div className="when">{fmtDateTime(t.at)}</div>
          <div style={{ fontWeight: 500 }}>{t.label}</div>
          {t.detail && <div className="muted" style={{ fontSize: 12 }}>{t.detail}</div>}
        </div>
      ))}
    </div>
  );
}

export function EventRowMini({ e, to }: { e: EventSummary; to?: string }) {
  return (
    <Link to={to ?? `/events/${e.public_id}`} className="row" style={{ justifyContent: "space-between", padding: "7px 0", borderTop: "1px solid var(--border)", color: "var(--text)" }}>
      <span className="stack" style={{ gap: 1 }}>
        <span className="mono">{e.public_id}</span>
        <span className="faint" style={{ fontSize: 11.5 }}>{[e.admin_district, e.admin_state].filter(Boolean).join(", ") || `${e.latitude.toFixed(2)}, ${e.longitude.toFixed(2)}`} · {relTime(e.last_detected)}</span>
      </span>
      <span className="stack" style={{ gap: 3, alignItems: "flex-end" }}><ClassLabel cls={e.classification} short /><StatePill state={e.display_state} /></span>
    </Link>
  );
}

export function ExtLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <a href={href} target="_blank" rel="noopener noreferrer" className="row" style={{ gap: 4, display: "inline-flex" }}>{children}<ExternalLink size={11} /></a>;
}
