/** Filtered analytics sections (server-side aggregates): activity over time, distributions, facility activity,
 *  geography and evidence coverage. Every chart is a database aggregate; empty ranges show an honest empty state. */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { fmtNum, sharePct } from "../lib/format";
import { CLASS_META, FACILITY_LABELS, PERSISTENCE_META } from "../lib/taxonomy";
import type { EvidenceCoverage } from "../lib/types";
import { apiQuery, type AnalyticsQuery } from "./analyticsFilters";
import { HBars, StackedBars } from "./charts";
import { Async, Empty } from "./ui";

interface Distributions {
  classification: { key: string; n: number }[]; persistence: { key: string; n: number }[]; confidence_state: { key: string; n: number }[];
  frp: { bin: number; n: number }[]; frp_bins: number[]; duration: { bin: number; n: number }[]; duration_bins_hours: number[];
}
interface Geography { states: { state: string | null; events: number; detections: number; persistent: number }[];
  districts: { district: string; state: string | null; events: number }[]; note: string }

const binLabel = (bins: number[], i: number, unit: string) => (i >= bins.length ? `≥ ${bins[bins.length - 1]} ${unit}` : `${bins[i - 1]}–${bins[i]} ${unit}`);
// the 13 evidence stages, in the event page's order and with its titles (backend services/evidence_rules.py)
const COVERAGE: [keyof EvidenceCoverage, string][] = [
  ["detection", "Thermal detection"], ["clustering", "Event clustering"], ["persistence", "Temporal persistence"],
  ["facility_proximity", "Facility proximity"], ["facility_attribution", "Facility attribution"], ["landcover", "Land cover"],
  ["weather", "Weather"], ["satellite", "Satellite scene availability"], ["spectral", "Spectral analysis (NDVI / NBR)"],
  ["classification", "Classification"], ["explainability", "Explainability"], ["review", "Analyst review"], ["final_status", "Final status"],
];

export function AdvancedAnalytics({ q, queryKey }: { q: AnalyticsQuery; queryKey: string }) {
  const query = apiQuery(q);
  const series = useQuery({ queryKey: ["analytics-series", queryKey], queryFn: () => api<{ bucket: string; rows: { bucket: string; classification: string; events: number; detections: number }[] }>("/analytics/series", { query }) });
  const dist = useQuery({ queryKey: ["analytics-dist", queryKey], queryFn: () => api<Distributions>("/analytics/distributions", { query }) });
  const geo = useQuery({ queryKey: ["analytics-geo", queryKey], queryFn: () => api<Geography>("/analytics/geography", { query }) });
  const cov = useQuery({ queryKey: ["analytics-cov", queryKey], queryFn: () => api<EvidenceCoverage>("/analytics/evidence-coverage", { query }) });
  const fac = useQuery({ queryKey: ["analytics-fac", queryKey], queryFn: () => api<{ id: string; name: string | null; facility_type: string; events: number; attributed: number; frp_max: number | null }[]>("/analytics/facility-activity", { query }) });

  const buckets = (() => {
    const m = new Map<string, Record<string, number>>();
    for (const r of series.data?.rows ?? []) { const k = r.bucket.slice(0, 10); m.set(k, { ...(m.get(k) ?? {}), [r.classification]: (m.get(k)?.[r.classification] ?? 0) + r.events }); }
    return [...m.entries()].map(([key, values]) => ({ key: key.slice(5), values }));
  })();
  const colors = { ...Object.fromEntries(Object.entries(CLASS_META).map(([k, v]) => [k, v.color])), unclassified: "#ced4da" };
  return (
    <div className="stack" style={{ gap: 12 }}>
      <section className="panel" data-tour-id="analytics-activity"><div className="panel-head"><h2>Activity over time</h2><span className="right faint">events per {series.data?.bucket ?? "day"}</span></div>
        <div className="panel-body"><Async q={series} empty={() => (buckets.length ? null : <Empty title="No activity is available for this period" />)}>{() => (
          <StackedBars buckets={buckets} series={[...Object.keys(CLASS_META), "unclassified"]} colors={colors} />
        )}</Async></div></section>
      <div className="grid cols-2">
        <section className="panel"><div className="panel-head"><h2>Classification distribution</h2><span className="right faint">automated interpretations</span></div><div className="panel-body">
          <Async q={dist} empty={(d) => (d.classification.length ? null : <Empty title="No events" />)}>{(d) => (
            <HBars rows={d.classification.map((r) => ({ label: CLASS_META[r.key as keyof typeof CLASS_META]?.label ?? r.key, value: r.n }))} color="var(--thermal)" />
          )}</Async></div></section>
        <section className="panel"><div className="panel-head"><h2>Persistence distribution</h2></div><div className="panel-body">
          <Async q={dist} empty={(d) => (d.persistence.length ? null : <Empty title="No events" />)}>{(d) => (
            <div className="stack" style={{ gap: 12 }}>
              <HBars rows={d.persistence.map((r) => ({ label: PERSISTENCE_META[r.key as keyof typeof PERSISTENCE_META]?.label ?? r.key, value: r.n }))} />
              <div><h4 style={{ margin: "0 0 6px" }}>Event duration</h4>
                <HBars rows={d.duration.map((r) => ({ label: binLabel(d.duration_bins_hours, r.bin, "h"), value: r.n }))} color="var(--info)" /></div>
            </div>
          )}</Async></div></section>
        <section className="panel"><div className="panel-head"><h2>FRP distribution</h2><span className="right faint">peak FRP per event</span></div><div className="panel-body">
          <Async q={dist} empty={(d) => (d.frp.length ? null : <Empty title="No FRP values" />)}>{(d) => (
            <><HBars rows={d.frp.map((r) => ({ label: binLabel(d.frp_bins, r.bin, "MW"), value: r.n }))} color="var(--thermal)" />
              <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>Higher thermal intensity does not by itself determine the cause of an event.</div></>
          )}</Async></div></section>
        <section className="panel" data-tour-id="analytics-coverage"><div className="panel-head"><h2>Evidence coverage</h2><span className="right faint">availability, not confidence</span></div><div className="panel-body">
          <Async q={cov} empty={(c) => (c.events ? null : <Empty title="No events in this range" />)}>{(c) => (
            <div className="stack" style={{ gap: 8 }}>
              <div className="faint" style={{ fontSize: 12 }}>{c.events.toLocaleString()} events · mean {fmtNum(c.mean_stages, 1)} of {c.stages_total} evidence stages available</div>
              <HBars rows={COVERAGE.map(([k, label]) => ({ label, value: (c[k] as number) / c.events, sub: `${(c[k] as number).toLocaleString()} events` }))}
                color="var(--ok)" format={sharePct} />
              <div className="faint" style={{ fontSize: 11.5 }}>{c.note}</div>
            </div>
          )}</Async></div></section>
        <section className="panel"><div className="panel-head"><h2>Facility activity</h2><span className="right faint">events within 2 km</span></div>
          <Async q={fac} empty={(d) => (d.length ? null : <div className="panel-body"><Empty title="No facility-associated events in this range" /></div>)}>{(d) => (
            <div className="table-wrap"><table className="table cards-on-mobile"><thead><tr><th scope="col">Facility</th><th scope="col">Type</th><th scope="col" className="right">Events</th><th scope="col" className="right">Attributed</th><th scope="col" className="right">Peak FRP</th></tr></thead>
              <tbody>{d.map((r) => (
                <tr key={r.id}><td data-label="Facility"><Link to={`/facilities/${r.id}`}>{r.name ?? "Unnamed"}</Link></td><td data-label="Type">{FACILITY_LABELS[r.facility_type] ?? r.facility_type}</td>
                  <td data-label="Events" className="right num">{r.events}</td><td data-label="Attributed" className="right num">{r.attributed}</td><td data-label="Peak FRP" className="right num">{fmtNum(r.frp_max, 1)} MW</td></tr>
              ))}</tbody></table></div>
          )}</Async></section>
        <section className="panel"><div className="panel-head"><h2>Geographic distribution</h2></div><div className="panel-body">
          <Async q={geo} empty={(g) => (g.states.length ? null : <Empty title="No events in this range" />)}>{(g) => (
            <div className="stack" style={{ gap: 12 }}>
              <HBars rows={g.states.slice(0, 15).map((r) => ({ label: r.state ?? "Unknown state", value: r.events, sub: `${r.persistent} persistent` }))} color="var(--thermal)" />
              {g.districts.length > 0 && <div><h4 style={{ margin: "0 0 6px" }}>Districts</h4><HBars rows={g.districts.slice(0, 12).map((r) => ({ label: `${r.district}${r.state ? `, ${r.state}` : ""}`, value: r.events }))} /></div>}
              <div className="faint" style={{ fontSize: 11.5 }}>{g.note}</div>
            </div>
          )}</Async></div></section>
      </div>
    </div>
  );
}
