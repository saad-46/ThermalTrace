/** Activity cluster around one event: nearby events in space and time, their aggregate activity and the facilities
 *  around them. A cluster groups activity for review; it does not mean the events share a source or cause. */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { HBars } from "../components/charts";
import { ContextMap } from "../components/ContextMap";
import { PriorityPill } from "../components/triage";
import { Async, ClassLabel, Empty, PersistencePill, StatePill } from "../components/ui";
import { api } from "../lib/api";
import { fmtDate, fmtDateTime, fmtDistance, fmtDuration, fmtNum, relTime } from "../lib/format";
import { useTheme } from "../lib/session";
import { CLASS_META, FACILITY_LABELS } from "../lib/taxonomy";
import type { Cluster, DisplayState } from "../lib/types";

const RADII = [2, 5, 10, 25];
const WINDOWS = [7, 30, 90];

export default function ClusterPage() {
  const { ref } = useParams();
  const [theme] = useTheme();
  const [radius, setRadius] = useState(5);
  const [days, setDays] = useState(30);
  const q = useQuery({ queryKey: ["cluster", ref, radius, days], placeholderData: keepPreviousData,
    queryFn: () => api<Cluster>(`/events/${ref}/cluster`, { query: { radius_km: radius, days } }) });
  return (
    <div className="page">
      <Link to={`/events/${ref}`} className="btn ghost sm" style={{ marginBottom: 10 }}><ArrowLeft size={13} /> Back to {ref}</Link>
      <div className="page-head">
        <div><h1>Activity cluster around {ref}</h1>
          <div className="sub">Observed spatial / temporal grouping: events within {radius} km, active within {days} days of {ref}. Grouped for review; not a shared source or cause.</div></div>
        <div className="actions">
          <div className="seg" aria-label="Radius">{RADII.map((r) => <button key={r} className={radius === r ? "on" : ""} onClick={() => setRadius(r)}>{r} km</button>)}</div>
          <div className="seg" aria-label="Time window">{WINDOWS.map((d) => <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>±{d} d</button>)}</div>
        </div>
      </div>
      <Async q={q} lines={8}>{(c) => (
        <div className="stack" style={{ gap: 12 }} data-testid="cluster-page">
          <div className="metrics">
            <div className="metric"><div className="label">Cluster</div><div className="value mono" style={{ fontSize: 14 }}>{c.cluster_id}</div><div className="hint">anchor {c.anchor.public_id}</div></div>
            <div className="metric"><div className="label">Events</div><div className="value">{c.summary.events}</div><div className="hint">{c.summary.detections.toLocaleString()} detections</div></div>
            <div className="metric"><div className="label">Duration</div><div className="value" style={{ fontSize: 15 }}>{fmtDuration(c.summary.duration_hours)}</div>
              <div className="hint">{fmtDate(c.summary.first_detected)} → {fmtDate(c.summary.last_detected)}</div></div>
            <div className="metric"><div className="label">Spatial extent</div><div className="value" style={{ fontSize: 15 }}>{fmtDistance(c.summary.max_distance_m)}</div><div className="hint">farthest event from the anchor</div></div>
            <div className="metric"><div className="label">FRP</div><div className="value" style={{ fontSize: 15 }}>{fmtNum(c.summary.frp_max, 1)} MW</div><div className="hint">peak · mean {fmtNum(c.summary.frp_mean, 1)} MW</div></div>
          </div>
          <div className="grid cols-2">
            <section className="panel"><div className="panel-head"><h2>Map</h2></div><div className="panel-body" style={{ padding: 0 }}>
              <ContextMap theme={theme} extent={c.summary.extent} rings={{ latitude: c.anchor.latitude, longitude: c.anchor.longitude }}
                events={c.events.map((e) => ({ ...e, focus: e.public_id === c.anchor.public_id }))} facilities={c.facilities} label="Cluster map" />
            </div></section>
            <section className="panel"><div className="panel-head"><h2>Composition</h2></div><div className="panel-body stack" style={{ gap: 12 }}>
              <div><h4 style={{ margin: "0 0 6px" }}>Classification distribution</h4>
                <HBars rows={c.classifications.map((k) => ({ label: CLASS_META[k.key as keyof typeof CLASS_META]?.label ?? k.key, value: k.n }))} color="var(--thermal)" /></div>
              <div><h4 style={{ margin: "0 0 6px" }}>Persistence</h4><HBars rows={c.persistence.map((k) => ({ label: k.key, value: k.n }))} /></div>
              <div><h4 style={{ margin: "0 0 6px" }}>Dominant land cover</h4>
                {c.landcover.length ? <HBars rows={c.landcover.map((k) => ({ label: k.key.replace(/_/g, " "), value: k.n }))} color="var(--info)" />
                  : <div className="faint">Land cover has not been retrieved for these events.</div>}</div>
            </div></section>
          </div>
          <section className="panel"><div className="panel-head"><h2>Nearest facilities and their activity</h2><span className="right faint">events within 3 km</span></div>
            {c.facilities.length ? (
              <div className="table-wrap"><table className="table"><thead><tr><th scope="col">Facility</th><th scope="col">Type</th><th scope="col" className="right">Events</th><th scope="col" className="right">Attributed</th><th scope="col" className="right">Closest</th></tr></thead>
                <tbody>{c.facilities.map((f) => (
                  <tr key={f.id}><td><Link to={`/facilities/${f.id}?event=${c.anchor.public_id}`}>{f.name ?? "Unnamed"}</Link></td><td>{FACILITY_LABELS[f.facility_type] ?? f.facility_type}</td>
                    <td className="right num">{f.events}</td><td className="right num">{f.attributed}</td><td className="right num">{fmtDistance(f.min_distance_m)}</td></tr>
                ))}</tbody></table></div>
            ) : <div className="panel-body"><Empty title="No mapped facility within 3 km of these events" /></div>}
          </section>
          <section className="panel"><div className="panel-head"><h2>Events in the cluster</h2><span className="right faint">{c.events.length}{c.truncated ? ` of ${c.summary.events}` : ""}</span></div>
            <div className="table-wrap"><table className="table cards-on-mobile"><thead><tr><th scope="col">Event</th><th scope="col">First → last</th><th scope="col" className="right">From anchor</th><th scope="col" className="right">Detections</th><th scope="col" className="right">Peak FRP</th><th scope="col">Classification</th><th scope="col">Persistence</th><th scope="col">Status</th><th scope="col">Priority</th></tr></thead>
              <tbody>{c.events.map((e) => (
                <tr key={e.id} className={e.public_id === c.anchor.public_id ? "row-selected" : undefined}>
                  <td data-label="Event"><Link className="mono" to={`/events/${e.public_id}`}>{e.public_id}</Link></td>
                  <td data-label="Active" className="num" title={fmtDateTime(e.first_detected)}>{fmtDate(e.first_detected)} → {relTime(e.last_detected)}</td>
                  <td data-label="From anchor" className="right num">{fmtDistance(e.distance_m)}</td>
                  <td data-label="Detections" className="right num">{e.observation_count}</td>
                  <td data-label="Peak FRP" className="right num">{fmtNum(e.frp_max, 1)} MW</td>
                  <td data-label="Classification"><ClassLabel cls={e.classification} short /></td>
                  <td data-label="Persistence"><PersistencePill p={e.persistence_class} /></td>
                  <td data-label="Status"><StatePill state={(e.confidence_state ?? "INSUFFICIENT_EVIDENCE") as DisplayState} /></td>
                  <td data-label="Priority"><PriorityPill score={e.priority_score} /></td>
                </tr>
              ))}</tbody></table></div>
          </section>
          <div className="faint" style={{ fontSize: 11.5 }}>{c.note}</div>
        </div>
      )}</Async>
    </div>
  );
}
