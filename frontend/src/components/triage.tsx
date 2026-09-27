/** Triage priority, evidence chain and persistence strip.
 * Prioritisation breakdown, stepwise evidence chain and per-day persistence view, built on the
 * event bundle — real data only. */
import { fmtNum } from "../lib/format";
import type { EventDetail, PriorityBreakdown } from "../lib/types";
import { Meter } from "./ui";
import { InvestigationStages } from "./workspace";

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

/** "How ThermalTrace thinks": the 13 evidence stages computed by the server from the shared availability rules, so the
 *  event page, mobile, alerts, analytics and reports agree. */
export function EvidenceChain({ ev }: { ev: EventDetail }) {
  return <InvestigationStages ev={ev} />;
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
