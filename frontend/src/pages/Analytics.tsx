import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { HBars, StackedBars } from "../components/charts";
import { Async, ClassLabel, Empty, errText, PersistencePill, StatePill, useToast } from "../components/ui";
import { api, downloadFile } from "../lib/api";
import { useSession } from "../lib/session";
import { fmtDistance, relTime, titleCase } from "../lib/format";
import { CLASS_META, FACILITY_LABELS, FP_REASONS } from "../lib/taxonomy";
import type { EventSummary } from "../lib/types";

export default function Analytics() {
  const { can } = useSession();
  const toast = useToast();
  const [days, setDays] = useState(30);
  const trends = useQuery({ queryKey: ["trends", days], queryFn: () => api<{ rows: { bucket: string; classification: string; detections: number }[] }>("/analytics/trends", { query: { days } }) });
  const hotspots = useQuery({ queryKey: ["hotspots", days], queryFn: () => api<{ districts: { admin_state: string; admin_district: string; events: number; detections: number; persistent: number; industrial: number }[]; facility_types: { facility_type: string; events: number; facilities: number }[]; note: string }>("/analytics/hotspots", { query: { days } }) });
  const sensors = useQuery({ queryKey: ["sensors", days], queryFn: () => api<{ per_sensor: { dataset: string; satellite: string; n: number; frp_mean: number; conf_mean: number }[]; multi_sensor_agreement: { sensor_count: number; n: number }[] }>("/analytics/sensors", { query: { days } }) });
  const diurnal = useQuery({ queryKey: ["diurnal", days], queryFn: () => api<{ satellite: string; daynight: string; hour: number; n: number }[]>("/analytics/diurnal", { query: { days } }) });
  const persistent = useQuery({ queryKey: ["persistent-sources", 25], queryFn: () => api<(EventSummary & { recurrence_count: number })[]>("/analytics/persistent-sources", { query: { limit: 25 } }) });
  const feedback = useQuery({ queryKey: ["feedback"], queryFn: () => api<{ decisions: { decision: string; n: number }[]; false_positives: { false_positive_reason: string; system_source_class: string; n: number }[]; system_vs_analyst: { system_source_class: string; confirmed: number; reclassified: number; rejected: number }[]; adjudicated_labels: number }>("/analytics/feedback") });

  const buckets = (() => {
    const m = new Map<string, Record<string, number>>();
    for (const r of trends.data?.rows ?? []) { const k = r.bucket.slice(0, 10); m.set(k, { ...(m.get(k) ?? {}), [r.classification]: r.detections }); }
    return [...m.entries()].map(([key, values]) => ({ key: key.slice(5), values }));
  })();
  const nightShare = (() => {
    const rows = diurnal.data ?? [];
    const by = new Map<string, { d: number; n: number }>();
    for (const r of rows) { const c = by.get(r.satellite) ?? { d: 0, n: 0 }; if (r.daynight === "N") c.n += r.n; else c.d += r.n; by.set(r.satellite, c); }
    return [...by.entries()].map(([s, c]) => ({ label: s, value: c.n / Math.max(c.d + c.n, 1), sub: `${c.n} night / ${c.d} day` }));
  })();

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Analytics</h1><div className="sub">Operational patterns in the loaded FIRMS history. Everything reflects satellite detections, not verified incidents.</div></div>
        <div className="actions"><div className="seg">{[7, 30, 90, 365].map((d) => <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>{d} d</button>)}</div></div>
      </div>
      <div className="stack" style={{ gap: 12 }}>
        <section className="panel"><div className="panel-head"><h2>Thermal activity by classification</h2><span className="right faint">daily detections</span></div>
          <div className="panel-body"><Async q={trends} empty={() => (buckets.length ? null : <Empty title="No data in range" />)}>{() => (
            <StackedBars buckets={buckets} series={[...Object.keys(CLASS_META), "unclassified"]} colors={{ ...Object.fromEntries(Object.entries(CLASS_META).map(([k, v]) => [k, v.color])), unclassified: "#ced4da" }} />
          )}</Async></div></section>

        <section className="panel"><div className="panel-head"><h2>Persistent thermal sources</h2><span className="right faint">ranked by persistence evidence — not a threat ranking</span></div>
          <Async q={persistent} empty={(d) => (d.length ? null : <Empty title="None identified yet" />)}>{(d) => (
            <div className="table-wrap"><table className="table"><thead><tr><th scope="col">Event</th><th scope="col">Location</th><th scope="col">Classification</th><th scope="col">Persistence</th><th scope="col" className="right">Active days</th><th scope="col" className="right">Platforms</th><th scope="col">Nearest facility</th><th scope="col">Status</th><th scope="col">Last seen</th></tr></thead>
              <tbody>{d.map((e) => (
                <tr key={e.id}><td><Link className="mono" to={`/events/${e.public_id}`}>{e.public_id}</Link></td><td>{[e.admin_district, e.admin_state].filter(Boolean).join(", ") || "—"}</td>
                  <td><ClassLabel cls={e.classification} short /></td><td><PersistencePill p={e.persistence_class} /> <span className="num faint">{e.persistence_score?.toFixed(2)}</span></td>
                  <td className="right num">{e.days_active}</td><td className="right num">{e.sensor_count}</td>
                  <td>{e.nearest_facility_name ? `${e.nearest_facility_name} (${fmtDistance(e.nearest_facility_distance_m)})` : "—"}</td>
                  <td><StatePill state={e.display_state} /></td><td className="num">{relTime(e.last_detected)}</td></tr>
              ))}</tbody></table></div>
          )}</Async></section>

        <div className="grid cols-2">
          <section className="panel"><div className="panel-head"><h2>District hotspots</h2></div><div className="panel-body">
            <Async q={hotspots} empty={(d) => (d.districts.length ? null : <Empty title="No geocoded events yet">{d.note}</Empty>)}>{(d) => (
              <><HBars rows={d.districts.map((r) => ({ label: `${r.admin_district}, ${r.admin_state}`, value: r.events, sub: `${r.persistent} persistent · ${r.industrial} industrial` }))} color="var(--thermal)" />
                <div className="faint" style={{ fontSize: 11.5, marginTop: 8 }}>{d.note}</div></>
            )}</Async></div></section>
          <section className="panel"><div className="panel-head"><h2>Industrial hotspots by facility type</h2><span className="right faint">events with nearest facility ≤ 2 km</span></div><div className="panel-body">
            <Async q={hotspots} empty={(d) => (d.facility_types.length ? null : <Empty title="No attributed events" />)}>{(d) => (
              <HBars rows={d.facility_types.map((r) => ({ label: FACILITY_LABELS[r.facility_type] ?? r.facility_type, value: r.events, sub: `${r.facilities} facilities` }))} />
            )}</Async></div></section>
          <section className="panel"><div className="panel-head"><h2>Sensor distribution</h2></div><div className="panel-body">
            <Async q={sensors}>{(d) => (
              <div className="stack" style={{ gap: 12 }}>
                <HBars rows={d.per_sensor.map((r) => ({ label: `${r.satellite} (${r.dataset.replace(/_NRT$/, "")})`, value: r.n, sub: `mean FRP ${r.frp_mean} MW` }))} />
                <div><h4 style={{ marginBottom: 6 }}>Multi-sensor agreement (events by number of platforms)</h4>
                  <HBars rows={d.multi_sensor_agreement.map((r) => ({ label: `${r.sensor_count} platform${r.sensor_count > 1 ? "s" : ""}`, value: r.n }))} color="var(--info)" /></div>
              </div>
            )}</Async></div></section>
          <section className="panel"><div className="panel-head"><h2>Night-time share by platform</h2><span className="right faint">persistent industrial sources are visible at night</span></div><div className="panel-body">
            <Async q={diurnal} empty={() => (nightShare.length ? null : <Empty title="No data" />)}>{() => <HBars rows={nightShare} color="#862e9c" format={(v) => `${Math.round(v * 100)}%`} />}</Async>
          </div></section>
        </div>

        <section className="panel"><div className="panel-head"><h2>Analyst feedback loop</h2><span className="right faint">training feedback dataset & false-positive intelligence</span>
          {can("supervisor") && <button className="btn sm" onClick={() => downloadFile("/ml/training-dataset?format=csv", "thermaltrace_training_dataset.csv").catch((e) => toast(errText(e), "error"))}>Export training dataset (CSV)</button>}
        </div><div className="panel-body">
          <Async q={feedback}>{(d) => (
            <div className="grid cols-3">
              <div><div className="metric" style={{ padding: 0 }}><div className="label">Adjudicated training labels</div><div className="value">{d.adjudicated_labels}</div>
                <div className="hint">Confirmed/reclassified events available to retrain the model (weight 3×).</div></div>
                <div style={{ marginTop: 10 }}><HBars rows={d.decisions.map((r) => ({ label: titleCase(r.decision), value: r.n }))} /></div></div>
              <div><h4 style={{ marginBottom: 6 }}>False positives by reason</h4>{d.false_positives.length
                ? <HBars rows={d.false_positives.map((r) => ({ label: FP_REASONS[r.false_positive_reason] ?? r.false_positive_reason, value: r.n, sub: `system said ${r.system_source_class}` }))} color="var(--bad)" />
                : <div className="faint">No false positives recorded.</div>}</div>
              <div><h4 style={{ marginBottom: 6 }}>System vs analyst</h4>{d.system_vs_analyst.length ? (
                <table className="table"><thead><tr><th scope="col">System label</th><th scope="col" className="right">Conf.</th><th scope="col" className="right">Reclass.</th><th scope="col" className="right">Rej.</th></tr></thead>
                  <tbody>{d.system_vs_analyst.map((r) => <tr key={r.system_source_class}><td>{CLASS_META[r.system_source_class as keyof typeof CLASS_META]?.short ?? r.system_source_class}</td><td className="right num">{r.confirmed}</td><td className="right num">{r.reclassified}</td><td className="right num">{r.rejected}</td></tr>)}</tbody></table>
              ) : <div className="faint">No reviews yet.</div>}</div>
            </div>
          )}</Async></div></section>
      </div>
    </div>
  );
}
