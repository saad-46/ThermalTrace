/** Facility Intelligence Profile sections: observed activity (counts, weekly/monthly comparison), thermal profile
 *  distributions, source agreement and the event relationship's temporal context. Observed activity, never risk. */
import { useQuery } from "@tanstack/react-query";
import { Check, Minus } from "lucide-react";
import { api } from "../lib/api";
import { fmtDate, fmtNum, relTime } from "../lib/format";
import { CLASS_META } from "../lib/taxonomy";
import type { FacilityActivityProfile, FacilityRelationship } from "../lib/types";
import { HBars } from "./charts";
import { Skeleton } from "./ui";
import { KnowledgeBadge } from "./workspace";

export const useFacilityProfile = (id?: string) =>
  useQuery({ queryKey: ["facility-profile", id], enabled: !!id, queryFn: () => api<FacilityActivityProfile>(`/facilities/${id}/profile`) });

function Delta({ now, before }: { now: number; before: number }) {
  if (!now && !before) return null;
  const d = now - before;
  return <span className={`delta ${d > 0 ? "up" : d < 0 ? "down" : ""}`}>{d > 0 ? "+" : ""}{d} vs previous</span>;
}

export function FacilityActivitySummary({ p }: { p: FacilityActivityProfile }) {
  const a = p.activity, c = p.comparison;
  return (
    <div className="stack" style={{ gap: 10 }} data-testid="facility-activity">
      <div className="metrics tight">
        <div className="metric"><div className="label">Events within 2 km</div><div className="value">{p.counts.within_2km}</div><div className="hint">{p.counts.within_10km} within 10 km</div></div>
        <div className="metric"><div className="label">Attributed</div><div className="value">{p.counts.attributed}</div><div className="hint">events ranking this facility first</div></div>
        <div className="metric"><div className="label">This week</div><div className="value">{c.current_week}</div><div className="hint">previous week {c.previous_week} <Delta now={c.current_week} before={c.previous_week} /></div></div>
        <div className="metric"><div className="label">Last 30 days</div><div className="value">{c.current_30_days}</div><div className="hint">previous 30 days {c.previous_30_days}</div></div>
        <div className="metric"><div className="label">Historical average</div><div className="value">{fmtNum(c.weekly_average, 1)}</div><div className="hint">events / week over {fmtNum(a.history_weeks, 0)} weeks</div></div>
        <div className="metric"><div className="label">History</div><div className="value">{a.total}</div><div className="hint">{a.first_activity ? `${fmtDate(a.first_activity)} → ${relTime(a.last_activity)}` : "no activity recorded"}</div></div>
      </div>
      <div className="faint" style={{ fontSize: 11.5 }}>Counts within {p.within_m / 1000} km unless stated. {c.note}</div>
    </div>
  );
}

const range = (b: { from: number; to: number | null }, unit: string) => (b.to == null ? `≥ ${b.from} ${unit}` : `${b.from}–${b.to} ${unit}`);

export function FacilityThermalProfile({ p }: { p: FacilityActivityProfile }) {
  const d = p.distributions;
  const hours = Array.from({ length: 24 }, (_, h) => ({ h, n: d.hour_of_day.filter((x) => x.hour === h).reduce((s, x) => s + x.n, 0) }));
  const maxH = Math.max(...hours.map((x) => x.n), 1);
  const any = p.activity.total > 0;
  if (!any) return <div className="faint">No thermal activity attributed within {p.within_m / 1000} km in the loaded history.</div>;
  return (
    <div className="grid cols-2" data-testid="facility-thermal-profile">
      <div><h4 style={{ margin: "0 0 6px" }}>Peak FRP per event</h4><HBars rows={d.frp.filter((b) => b.n).map((b) => ({ label: range(b, "MW"), value: b.n }))} color="var(--thermal)" /></div>
      <div><h4 style={{ margin: "0 0 6px" }}>Peak brightness per event</h4>
        {d.brightness.some((b) => b.n) ? <HBars rows={d.brightness.filter((b) => b.n).map((b) => ({ label: range(b, "K"), value: b.n }))} color="var(--ember, #ffb454)" />
          : <div className="faint">No brightness values recorded.</div>}</div>
      <div><h4 style={{ margin: "0 0 6px" }}>Persistence</h4><HBars rows={d.persistence.map((k) => ({ label: k.key, value: k.n }))} /></div>
      <div><h4 style={{ margin: "0 0 6px" }}>Classifications</h4><HBars rows={d.classifications.map((k) => ({ label: CLASS_META[k.key as keyof typeof CLASS_META]?.label ?? k.key, value: k.n }))} /></div>
      <div style={{ gridColumn: "1 / -1" }}>
        <h4 style={{ margin: "0 0 6px" }}>Detections by hour of day (UTC)</h4>
        <div className="hourbars" role="img" aria-label="Detections by hour of day">
          {hours.map((x) => <span key={x.h} style={{ height: `${Math.max(2, (x.n / maxH) * 100)}%` }} title={`${String(x.h).padStart(2, "0")}:00 UTC: ${x.n} detection(s)`} />)}
        </div>
        <div className="row" style={{ justifyContent: "space-between", fontSize: 10.5 }} aria-hidden><span className="faint">00</span><span className="faint">06</span><span className="faint">12</span><span className="faint">18</span><span className="faint">23</span></div>
        <div className="faint" style={{ fontSize: 11.5 }}>Satellite overpass times shape this pattern; it is when heat was observed, not when it started.</div>
      </div>
    </div>
  );
}

const AGREEMENT: [string, string][] = [["gem", "GEM"], ["wri_gppd", "WRI"], ["cea", "CEA"], ["osm", "OSM"]];

export function SourceAgreement({ p }: { p: FacilityActivityProfile }) {
  const sa = p.source_agreement;
  return (
    <div className="stack" style={{ gap: 8 }} data-testid="source-agreement">
      <div className="agree">
        {AGREEMENT.map(([k, label]) => {
          const s = sa.sources[k];
          return (
            <div key={k} className={`agree-item ${s?.present ? "yes" : "no"}`} title={s?.records.map((r) => `${r.external_id}${r.name ? ` (${r.name})` : ""}`).join("\n") || "not listed"}>
              {s?.present ? <Check size={14} aria-hidden /> : <Minus size={14} aria-hidden />}
              <b>{label}</b><span className="faint">{s?.present ? `${s.records.length} record${s.records.length > 1 ? "s" : ""}` : "not listed"}</span>
            </div>
          );
        })}
      </div>
      <div className="faint" style={{ fontSize: 11.5 }}>{sa.count} of 4 registries identify this facility. {sa.note}</div>
    </div>
  );
}

export function RelationshipContext({ rel }: { rel: FacilityRelationship }) {
  return (
    <div className="stack" style={{ gap: 6 }}>
      {rel.temporal && (
        <div className="faint" style={{ fontSize: 12 }}>
          Temporal relationship: {rel.temporal.around_event} event(s) within 2 km of this facility were active within 30 days of this event
          ({rel.temporal.total} in the loaded history{rel.temporal.first_activity ? `, ${fmtDate(rel.temporal.first_activity)} → ${fmtDate(rel.temporal.last_activity)}` : ""}).
        </div>
      )}
      {rel.evidence?.length ? (
        <div><h4 style={{ margin: "4px 0" }}>Supporting evidence recorded for the event</h4>
          <ul className="plain">{rel.evidence.map((e, i) => <li key={i}><span className={`kbadge ${e.direction === "supports" ? "derived" : ""}`}>{e.direction}</span> {e.statement}</li>)}</ul></div>
      ) : null}
    </div>
  );
}

export function FacilityProfileSections({ id }: { id?: string }) {
  const q = useFacilityProfile(id);
  if (q.isLoading) return <Skeleton lines={6} />;
  if (q.error || !q.data) return <div className="faint">The activity profile is unavailable right now.</div>;
  const p = q.data;
  return (
    <div className="stack" style={{ gap: 12 }}>
      <section className="panel"><div className="panel-head"><h2>Activity summary</h2><span className="right faint row" style={{ gap: 6 }}>observed activity, not risk <KnowledgeBadge k="observed" /></span></div>
        <div className="panel-body"><FacilityActivitySummary p={p} /></div></section>
      <div className="grid cols-2">
        <section className="panel"><div className="panel-head"><h2>Thermal profile</h2><span className="right"><KnowledgeBadge k="derived" /></span></div><div className="panel-body"><FacilityThermalProfile p={p} /></div></section>
        <section className="panel"><div className="panel-head"><h2>Source agreement</h2><span className="right"><KnowledgeBadge k="registry" /></span></div><div className="panel-body"><SourceAgreement p={p} /></div></section>
      </div>
    </div>
  );
}
