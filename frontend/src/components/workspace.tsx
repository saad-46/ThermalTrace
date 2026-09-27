/** Investigation workspace: evidence stages ("How ThermalTrace thinks"), evidence availability, the event timeline with
 *  playback, activity charts, the explainable classification and recurring activity. Everything renders what the
 *  backend computed from stored data (event bundle `evidence_stages`, `timeline`, detections, observations); missing
 *  evidence is shown with its reason, never hidden and never treated as negative. */
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Pause, Play, SkipBack } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { fmtDate, fmtDateTime, fmtNum, relTime, titleCase } from "../lib/format";
import { CLASS_META } from "../lib/taxonomy";
import type { EventDetail, EvidenceStage, Knowledge, Recurrence, StageStatus, TimelineItem } from "../lib/types";
import { Skeleton, StatePill } from "./ui";

export const KNOWLEDGE_LABEL: Record<Knowledge, string> = { observed: "Observed", derived: "Derived", inferred: "Inferred", analyst: "Analyst", registry: "Registry" };
const KNOWLEDGE_HINT: Record<Knowledge, string> = {
  observed: "Retrieved directly from a provider or the database",
  derived: "Calculated from observed data",
  inferred: "An interpretation by rules or a model",
  analyst: "An explicit human decision",
  registry: "Reference data from facility registries and maps; says nothing about current activity",
};
export function KnowledgeBadge({ k }: { k?: Knowledge }) {
  if (!k) return null;
  return <span className={`kbadge ${k}`} title={KNOWLEDGE_HINT[k]}>{KNOWLEDGE_LABEL[k]}</span>;
}

const STATE_SYMBOL: Record<StageStatus, string> = { available: "✓", pending: "…", no_data: "∅", not_requested: "—", failed: "!", review: "?" };
export function StageState({ s }: { s: StageStatus }) {
  const label = { available: "Available", pending: "Pending", no_data: "No data", not_requested: "Not requested", failed: "Failed", review: "Requires analyst review" }[s];
  return <span className={`stage-state ${s}`}><span aria-hidden>{STATE_SYMBOL[s]}</span> {label}</span>;
}

/** "Updated 4 min ago" / "Not requested" / "Unavailable": always from a stored timestamp, never invented. */
export function freshness(st: EvidenceStage): string {
  if (st.state === "not_requested") return "Not requested";
  if (st.state === "pending") return "Retrieving now";
  if (!st.at) return st.state === "available" ? "Time not recorded" : "Unavailable";
  return `${st.state === "available" ? "Updated" : "Last checked"} ${relTime(st.at)}`;
}

// ------------------------------------------------------------------ evidence availability
export function EvidenceCompleteness({ ev, compact }: { ev: EventDetail; compact?: boolean }) {
  const es = ev.evidence_stages;
  if (!es) return null;
  const { stages, completeness } = es;
  const bar = (
    <div className="ecomp-bar" role="img" aria-label={`Evidence availability: ${completeness.available} of ${completeness.total} stages`}>
      {stages.map((s) => <span key={s.key} className={`ecomp-seg ${s.state}`} title={`${s.title}: ${s.state_label}`} />)}
    </div>
  );
  if (compact)
    return (
      <div className="ecomp compact" title={completeness.note}>
        <span className="ecomp-label">Evidence availability</span>{bar}
        <span className="num">{completeness.available} / {completeness.total}</span>
      </div>
    );
  return (
    <div className="ecomp" data-testid="evidence-completeness">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <b>Evidence collected</b><span className="num">{completeness.available} / {completeness.total} stages available</span>
      </div>
      {bar}
      <ul className="ecomp-list">
        {stages.map((s) => (
          <li key={s.key}><span>{s.title}</span><StageState s={s.state} /></li>
        ))}
      </ul>
      <div className="faint" style={{ fontSize: 11.5 }}>{completeness.note}</div>
    </div>
  );
}

// ------------------------------------------------------------------ how ThermalTrace thinks
export function InvestigationStages({ ev }: { ev: EventDetail }) {
  const stages = ev.evidence_stages?.stages ?? [];
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const all = stages.length > 0 && stages.every((s) => open[s.key]);
  if (!stages.length) return <div className="faint">Evidence stages are not available for this event.</div>;
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <p className="faint" style={{ fontSize: 12, margin: 0 }}>
          How ThermalTrace reached its assessment, stage by stage. Supporting evidence, not proof; missing evidence is shown with its reason.
        </p>
        <button className="btn ghost sm" onClick={() => setOpen(all ? {} : Object.fromEntries(stages.map((s) => [s.key, true])))}>{all ? "Collapse all" : "Expand all"}</button>
      </div>
      <ol className="stages" aria-label="Evidence stages">
        {stages.map((s, i) => {
          const o = !!open[s.key];
          return (
            <li key={s.key} className={`stage ${s.state} ${o ? "open" : ""}`}>
              <button className="stage-head" aria-expanded={o} onClick={() => setOpen((m) => ({ ...m, [s.key]: !m[s.key] }))}>
                <span className="stage-num">{i + 1}</span>
                <span className="stage-title">{s.title}</span>
                <StageState s={s.state} />
                <span className="stage-value">{s.value}</span>
                <span className="stage-fresh">{freshness(s)}</span>
                {o ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
              </button>
              {o && (
                <div className="stage-body">
                  {s.reason && <div><b>Why:</b> {s.reason}</div>}
                  {s.detail && <div className="faint">{s.detail}</div>}
                  <dl className="kv">
                    <dt>Contributes</dt><dd>{s.contributes}</dd>
                    <dt>Limitation</dt><dd>{s.limitation}</dd>
                    <dt>Source</dt><dd>{s.source}</dd>
                    <dt>Knowledge</dt><dd><KnowledgeBadge k={s.knowledge} /></dd>
                    <dt>Time</dt><dd>{s.at ? `${fmtDateTime(s.at)} (${relTime(s.at)})` : "—"}</dd>
                  </dl>
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// ------------------------------------------------------------------ timeline / playback
const KIND_TONE: Partial<Record<TimelineItem["kind"], string>> = {
  first_seen: "thermal", observation: "thermal", latest: "thermal", gap: "gap", review: "analyst", note: "analyst", alert: "alert",
  classification: "inferred", facility: "derived", clustered: "derived", spectral: "derived",
};

export function EventTimeline({ ev }: { ev: EventDetail }) {
  const items = ev.timeline;
  const [cursor, setCursor] = useState(items.length - 1);
  const [playing, setPlaying] = useState(false);
  const listRef = useRef<HTMLOListElement>(null);
  useEffect(() => { setCursor(items.length - 1); setPlaying(false); }, [ev.id, items.length]);
  useEffect(() => {
    if (!playing) return;
    if (cursor >= items.length - 1) { setPlaying(false); return; }
    const t = window.setTimeout(() => setCursor((c) => c + 1), 700);
    return () => window.clearTimeout(t);
  }, [playing, cursor, items.length]);
  useEffect(() => {
    if (!playing) return;
    listRef.current?.querySelector<HTMLElement>(`[data-i="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor, playing]);
  if (!items.length) return <div className="faint">No timeline yet.</div>;
  let lastDay = "";
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row wrap" style={{ gap: 6 }}>
        <button className="btn sm" onClick={() => { setCursor(0); setPlaying(false); }} aria-label="Back to the first entry"><SkipBack size={13} /></button>
        <button className="btn sm" onClick={() => { if (cursor >= items.length - 1) setCursor(0); setPlaying((p) => !p); }}>
          {playing ? <><Pause size={13} /> Pause</> : <><Play size={13} /> Play</>}
        </button>
        <input type="range" min={0} max={items.length - 1} value={cursor} onChange={(e) => { setPlaying(false); setCursor(+e.target.value); }}
          aria-label="Timeline position" style={{ flex: 1, minWidth: 120 }} />
        <span className="faint num" style={{ fontSize: 11.5 }}>{fmtDateTime(items[cursor].at)}</span>
      </div>
      <ol className="tl" ref={listRef} aria-label="Event timeline">
        {items.map((t, i) => {
          const day = t.at.slice(0, 10);
          const header = day !== lastDay ? (lastDay = day, <li key={`d${day}`} className="tl-day">{fmtDate(t.at)}</li>) : null;
          return [
            header,
            <li key={i} data-i={i} className={`tl-item ${KIND_TONE[t.kind] ?? ""} ${i > cursor ? "future" : ""} ${i === cursor ? "current" : ""}`}>
              <span className="tl-time num">{t.at.slice(11, 16)}</span>
              <span className="tl-dot" aria-hidden />
              <span className="tl-text"><b>{t.label}</b>{t.detail ? <span className="faint"> · {t.detail}</span> : null}</span>
              <KnowledgeBadge k={t.knowledge} />
            </li>,
          ];
        })}
      </ol>
      <div className="faint" style={{ fontSize: 11.5 }}>Stored timestamps only (UTC). Gaps between detection days are shown; nothing is interpolated.</div>
    </div>
  );
}

// ------------------------------------------------------------------ activity chart
type Metric = "frp" | "brightness" | "detections" | "persistence";
const METRICS: { key: Metric; label: string }[] = [
  { key: "frp", label: "FRP" }, { key: "brightness", label: "Brightness" }, { key: "detections", label: "Detections" }, { key: "persistence", label: "Persistence" },
];

interface Pt { t: number; v: number; label: string; sub: string }

export function ActivityChart({ ev }: { ev: EventDetail }) {
  const [metric, setMetric] = useState<Metric>("frp");
  const [hover, setHover] = useState<number | null>(null);
  const pts: Pt[] = useMemo(() => {
    if (metric === "frp" || metric === "brightness")
      return ev.detections.filter((d) => (metric === "frp" ? d.frp : d.brightness) != null).map((d) => ({
        t: Date.parse(d.acq_datetime), v: (metric === "frp" ? d.frp : d.brightness)!,
        label: `${fmtNum(metric === "frp" ? d.frp : d.brightness, 1)} ${metric === "frp" ? "MW" : "K"}`,
        sub: `${fmtDateTime(d.acq_datetime)} · ${d.satellite} (${d.dataset.replace(/_NRT$/, "")})${d.daynight === "N" ? " · night" : ""}`,
      }));
    if (metric === "detections")
      return ev.observations.map((o) => ({ t: Date.parse(`${o.obs_date}T12:00:00Z`), v: o.detection_count, label: `${o.detection_count} detection(s)`,
        sub: `${o.obs_date} · ${o.sensors.join(", ")} · peak ${fmtNum(o.frp_max, 1)} MW` }));
    let n = 0;
    return ev.observations.map((o) => ({ t: Date.parse(`${o.obs_date}T12:00:00Z`), v: ++n, label: `${n} active day(s)`, sub: `${o.obs_date} · ${o.detection_count} detection(s)` }));
  }, [ev, metric]);
  const W = 640, H = 170, P = { l: 40, r: 10, t: 10, b: 22 };
  const t0 = Math.min(...pts.map((p) => p.t)), t1 = Math.max(...pts.map((p) => p.t));
  const vmax = Math.max(...pts.map((p) => p.v), 1), vmin = metric === "brightness" ? Math.min(...pts.map((p) => p.v)) - 5 : 0;
  const x = (t: number) => P.l + (t1 > t0 ? ((t - t0) / (t1 - t0)) * (W - P.l - P.r) : (W - P.l - P.r) / 2);
  const y = (v: number) => H - P.b - ((v - vmin) / Math.max(vmax - vmin, 1e-9)) * (H - P.t - P.b);
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const mx = ((e.clientX - r.left) / r.width) * W;
    let best = 0, bd = Infinity;
    pts.forEach((p, i) => { const d = Math.abs(x(p.t) - mx); if (d < bd) { bd = d; best = i; } });
    setHover(pts.length ? best : null);
  };
  const h = hover != null ? pts[hover] : null;
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="seg" role="tablist" aria-label="Activity metric">
        {METRICS.map((m) => <button key={m.key} role="tab" aria-selected={metric === m.key} className={metric === m.key ? "on" : ""} onClick={() => { setMetric(m.key); setHover(null); }}>{m.label}</button>)}
      </div>
      {pts.length ? (
        <div className="achart">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${metric} over time`} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
            {[0, 0.5, 1].map((f) => { const v = vmin + f * (vmax - vmin); return (
              <g key={f}><line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} className="achart-grid" />
                <text x={P.l - 4} y={y(v) + 3} textAnchor="end" className="achart-axis">{fmtNum(v, metric === "frp" ? 1 : 0)}</text></g>); })}
            <text x={P.l} y={H - 6} className="achart-axis">{fmtDate(new Date(t0).toISOString())}</text>
            <text x={W - P.r} y={H - 6} textAnchor="end" className="achart-axis">{fmtDate(new Date(t1).toISOString())}</text>
            {metric === "detections"
              ? pts.map((p, i) => <rect key={i} x={x(p.t) - 3} y={y(p.v)} width={6} height={H - P.b - y(p.v)} className={`achart-bar ${hover === i ? "on" : ""}`} />)
              : metric === "persistence"
                ? <polyline points={pts.map((p) => `${x(p.t)},${y(p.v)}`).join(" ")} className="achart-line" />
                : pts.map((p, i) => <circle key={i} cx={x(p.t)} cy={y(p.v)} r={hover === i ? 4.5 : 2.6} className={`achart-dot ${hover === i ? "on" : ""}`} />)}
            {h && <line x1={x(h.t)} x2={x(h.t)} y1={P.t} y2={H - P.b} className="achart-cursor" />}
          </svg>
          {h && <div className="achart-tip" role="status"><b>{h.label}</b><div className="faint">{h.sub}</div></div>}
        </div>
      ) : <div className="faint">No {metric} values recorded for this event.</div>}
      <div className="faint" style={{ fontSize: 11.5 }}>
        {metric === "frp" || metric === "brightness" ? `${pts.length} detection(s)${ev.detections.length >= 1000 ? " (first 1,000)" : ""}. ` : ""}
        Higher thermal intensity does not by itself determine the cause of an event.
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ explainable classification
export function ClassificationExplained({ ev }: { ev: EventDetail }) {
  const stages = ev.evidence_stages?.stages ?? [];
  const by = Object.fromEntries(stages.map((s) => [s.key, s]));
  const supports = ev.evidence.filter((e) => e.direction === "supports").sort((a, b) => b.strength - a.strength).slice(0, 4);
  const contradicts = ev.evidence.filter((e) => e.direction === "contradicts").slice(0, 3);
  const dets = ev.detections.filter((d) => d.brightness != null);
  const bmax = dets.length ? Math.max(...dets.map((d) => d.brightness!)) : null;
  const rows: [string, string][] = [
    ["Land cover", by.landcover?.value ?? "—"],
    ["Persistence", by.persistence?.value ?? "—"],
    ["Facility proximity", by.facility_proximity?.value ?? "—"],
    ["FRP", `peak ${fmtNum(ev.frp_max, 1)} MW, mean ${fmtNum(ev.frp_mean, 1)} MW`],
    ["Brightness", bmax != null ? `max ${fmtNum(bmax, 0)} K` : "not reported"],
    ["Spectral evidence", by.spectral ? `${by.spectral.state_label}${by.spectral.state === "available" ? `: ${by.spectral.value}` : ""}` : "—"],
    ["Weather", by.weather?.value ?? "—"],
  ];
  const missing = stages.filter((s) => s.state !== "available");
  return (
    <div className="stack" style={{ gap: 10 }} data-testid="classification-explained">
      <div>
        <div className="faint" style={{ fontSize: 11.5, textTransform: "uppercase", letterSpacing: ".04em" }}>Current interpretation</div>
        <div style={{ fontSize: 16, fontWeight: 600 }}>{ev.classification ? CLASS_META[ev.classification].label : "Not classified yet"}</div>
        <div className="row wrap" style={{ marginTop: 4 }}><StatePill state={ev.display_state} /><span className="faint">confidence {fmtNum(ev.confidence_score, 2)} · reflects supporting evidence, not a probability</span></div>
      </div>
      <div>
        <h4 style={{ margin: "0 0 4px" }}>Why</h4>
        {supports.length ? <ul className="plain">{supports.map((e, i) => <li key={i}><span className="kbadge derived">{titleCase(e.category)}</span> {e.statement}</li>)}</ul>
          : <div className="faint">No supporting evidence item recorded.</div>}
        {contradicts.length > 0 && <><h4 style={{ margin: "8px 0 4px" }}>Against</h4><ul className="plain">{contradicts.map((e, i) => <li key={i}>{e.statement}</li>)}</ul></>}
      </div>
      <dl className="kv">{rows.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl>
      <div>
        <h4 style={{ margin: "0 0 4px" }}>Limitations</h4>
        {missing.length ? <ul className="plain">{missing.map((s) => <li key={s.key}><b>{s.title}</b>: {s.state_label.toLowerCase()}{s.reason ? ` (${s.reason})` : ""}</li>)}</ul>
          : <div className="faint">Every evidence stage has data; each still has the limitations listed in the evidence stages.</div>}
      </div>
      <div className="faint" style={{ fontSize: 11.5 }}>SHAP shows how features contributed to the model output. It does not establish causation. The interpretation is supporting evidence until an analyst reviews it.</div>
    </div>
  );
}

// ------------------------------------------------------------------ recurring activity around the event
export function RecurrencePanel({ ev, radiusKm = 2 }: { ev: EventDetail; radiusKm?: number }) {
  const q = useQuery({ queryKey: ["recurrence", ev.public_id, radiusKm], queryFn: () => api<Recurrence>(`/events/${ev.public_id}/recurrence`, { query: { radius_km: radiusKm } }) });
  if (q.isLoading) return <Skeleton lines={3} />;
  if (q.error || !q.data) return <div className="faint">Recurring activity is unavailable right now.</div>;
  const a = q.data.activity;
  const max = Math.max(...q.data.monthly.map((m) => m.events), 1);
  return (
    <div className="stack" style={{ gap: 10 }} data-testid="recurrence-panel">
      <div className="metrics tight">
        <div className="metric"><div className="label">This week</div><div className="value">{a.this_week}</div><div className="hint">previous week {a.previous_week}</div></div>
        <div className="metric"><div className="label">Last 30 days</div><div className="value">{a.last_30_days}</div><div className="hint">previous 30 days {a.previous_30_days}</div></div>
        <div className="metric"><div className="label">Average</div><div className="value">{fmtNum(a.weekly_average, 1)}</div><div className="hint">events / week over {fmtNum(a.history_weeks, 0)} weeks</div></div>
        <div className="metric"><div className="label">Historical</div><div className="value">{a.total}</div><div className="hint">{a.detections} detections · mean peak FRP {fmtNum(a.frp_max_mean, 1)} MW</div></div>
      </div>
      {q.data.monthly.length > 1 && (
        <div className="minibars" role="img" aria-label="Events per month within the radius">
          {q.data.monthly.map((m) => <span key={m.month} style={{ height: `${Math.max(4, (m.events / max) * 100)}%` }} title={`${m.month.slice(0, 7)}: ${m.events} event(s)`} />)}
        </div>
      )}
      <div className="chips">
        {q.data.persistence.map((p) => <span key={p.key} className="chip">{p.key} {p.n}</span>)}
        {q.data.classifications.slice(0, 5).map((c) => <span key={c.key} className="chip">{CLASS_META[c.key as keyof typeof CLASS_META]?.short ?? c.key} {c.n}</span>)}
      </div>
      <div className="faint" style={{ fontSize: 11.5 }}>Events within {radiusKm} km of this location. {q.data.note}</div>
    </div>
  );
}
