/** Triage priority, evidence chain and persistence strip.
 * Prioritisation breakdown, stepwise evidence chain and per-day persistence view, built on the
 * event bundle — real data only. */
import { compass, fmtDate, fmtDistance, fmtNum } from "../lib/format";
import { CLASS_META, FACILITY_LABELS, STATE_META } from "../lib/taxonomy";
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

type Stage = { key: string; title: string; summary: string; detail: string; state: "ok" | "missing" | "neutral" };

export function buildEvidenceChain(ev: EventDetail): Stage[] {
  const top = ev.facilities[0];
  const pm = ev.persistence_metrics;
  const best = ev.satellite.length
    ? ev.satellite.reduce((a, b) => ((a.cloud_cover ?? 101) <= (b.cloud_cover ?? 101) ? a : b))
    : null;
  const land = [...new Set(ev.land.map((l) => l.category))];
  const osmChecked = ev.enrichment_state?.osm?.status === "ok";
  const w = ev.weather[0];
  return [
    { key: "detection", title: "Thermal detection", state: "ok",
      summary: `${ev.observation_count} FIRMS detection(s) · ${ev.sensor_count} platform(s)`,
      detail: `Peak FRP ${fmtNum(ev.frp_max)} MW; ${ev.sensors.join(", ")}.` },
    { key: "location", title: "Location context", state: ev.admin_district || land.length ? "ok" : "neutral",
      summary: [ev.admin_district, ev.admin_state].filter(Boolean).join(", ") || `${ev.latitude.toFixed(3)}, ${ev.longitude.toFixed(3)}`,
      detail: land.length ? `Mapped land use nearby: ${land.join(", ")}.` : osmChecked ? "No farmland/forest/residential mapped within 1.5 km." : "Land use not yet retrieved." },
    { key: "facility", title: "Facility attribution", state: top ? "ok" : osmChecked ? "neutral" : "missing",
      summary: top ? `${top.name ?? "Unnamed"} — ${fmtDistance(top.distance_m)}` : osmChecked ? "No mapped facility within 10 km" : "Not yet retrieved",
      detail: top ? `${FACILITY_LABELS[top.facility_type] ?? top.facility_type}, ${top.bearing_deg != null ? compass(top.bearing_deg) + " of event, " : ""}attribution ${top.attribution_score.toFixed(2)}.` : "Absence may reflect incomplete mapping." },
    { key: "persistence", title: "Temporal persistence", state: "ok",
      summary: pm ? `${pm.persistence_class} · ${pm.active_days} of ${pm.span_days} day(s)` : "—",
      detail: pm ? `${pm.rationale}.` : "" },
    { key: "satellite", title: "Satellite imagery", state: best ? "ok" : "missing",
      summary: best ? `Sentinel-2 ${fmtDate(best.acquired_at)} · ${fmtNum(best.cloud_cover, 0)}% cloud` : "No scene available",
      detail: best ? "Available for analyst comparison; not analysed automatically." : ev.enrichment_state?.satellite ? "No L2A scene under the cloud threshold." : "Imagery not yet searched." },
    { key: "weather", title: "Weather context", state: w ? "ok" : "missing",
      summary: w ? `${w.condition ?? "—"}, wind ${fmtNum(w.wind_speed_ms)} m/s from ${compass(w.wind_direction_deg)}` : "Not available",
      detail: w ? `${w.dataset}. Context only — not proof of source.` : "" },
    { key: "classification", title: "Classification", state: ev.classification && ev.classification !== "unknown" ? "ok" : "missing",
      summary: ev.classification ? CLASS_META[ev.classification].label : "Unprocessed",
      detail: `Model ${ev.classification_current?.primary_model_id ?? "—"}, probability ${fmtNum(ev.classification_probability, 2)}.` },
    { key: "confidence", title: "Confidence", state: ev.display_state === "INSUFFICIENT_EVIDENCE" ? "missing" : "ok",
      summary: `${STATE_META[ev.display_state].label} · ${fmtNum(ev.confidence_score, 2)}`,
      detail: ev.confidence_components?.missing.length ? `Missing: ${ev.confidence_components.missing.join(", ")}.` : "No evidence flagged as missing." },
  ];
}

export function EvidenceChain({ ev }: { ev: EventDetail }) {
  const stages = buildEvidenceChain(ev);
  return (
    <ol className="chain" aria-label="Evidence chain">
      {stages.map((s) => (
        <li key={s.key} className={`chain-step ${s.state}`}>
          <div className="chain-title">{s.title}</div>
          <div className="chain-summary">{s.summary}</div>
          {s.detail && <div className="chain-detail">{s.detail}</div>}
        </li>
      ))}
    </ol>
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
