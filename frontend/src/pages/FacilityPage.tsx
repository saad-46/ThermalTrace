import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Eye } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { HBars } from "../components/charts";
import { ExtLink } from "../components/evidence";
import { Async, ClassLabel, Empty, errText, PersistencePill, StatePill, useToast } from "../components/ui";
import { api } from "../lib/api";
import { fmtDate, fmtDistance, fmtNum, relTime } from "../lib/format";
import { actions, useWatchlists } from "../lib/hooks";
import { useSession } from "../lib/session";
import { FACILITY_LABELS, SOURCE_NAMES, STATE_META } from "../lib/taxonomy";
import type { DisplayState, Facility, FacilityProfile, PersistenceClass, SourceClass } from "../lib/types";

interface FacEvents {
  profile: FacilityProfile;
  within_m: number;
  events: { id: string; public_id: string; first_detected: string; last_detected: string; classification: SourceClass; persistence_class: PersistenceClass; confidence_state: DisplayState; review_status: string; observation_count: number; frp_max: number; distance_m: number }[];
  weekly: { week: string; detections: number; frp_max: number }[];
}

export default function FacilityPage() {
  const { id } = useParams();
  const { can } = useSession();
  const toast = useToast();
  const fac = useQuery({ queryKey: ["facility", id], queryFn: () => api<Facility>(`/facilities/${id}`) });
  const hist = useQuery({ queryKey: ["facility-events", id], queryFn: () => api<FacEvents>(`/facilities/${id}/events`) });
  const wls = useWatchlists();
  const watch = async (wlId: string, f: Facility) => {
    try { await actions.addWatchItem(wlId)({ kind: "facility", label: f.name ?? FACILITY_LABELS[f.facility_type], facility_id: f.id, radius_m: 3000 }); toast("Facility added to watchlist"); }
    catch (e) { toast(errText(e), "error"); }
  };
  return (
    <div className="page">
      <Link to="/facilities" className="btn ghost sm" style={{ marginBottom: 10 }}><ArrowLeft size={13} /> Facilities</Link>
      <Async q={fac} lines={6}>{(f) => (
        <>
          <div className="page-head">
            <div>
              <h1>{f.name ?? "Unnamed facility"}</h1>
              <div className="sub">{FACILITY_LABELS[f.facility_type] ?? f.facility_type} · {f.latitude.toFixed(4)}, {f.longitude.toFixed(4)}</div>
            </div>
            {can("analyst") && wls.data && wls.data.length > 0 && (
              <div className="actions">
                <select className="select" aria-label="Add to watchlist" defaultValue="" onChange={(e) => { if (e.target.value) watch(e.target.value, f); e.target.value = ""; }}>
                  <option value="" disabled>Add to watchlist…</option>{wls.data.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
                <Link className="btn" to={`/map?lat=${f.latitude}&lon=${f.longitude}&z=12`}><Eye size={14} /> Map</Link>
              </div>
            )}
          </div>
          <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.4fr)" }}>
            <section className="panel"><div className="panel-head"><h2>Attributes</h2></div><div className="panel-body">
              <dl className="kv">
                <dt>Operator</dt><dd>{f.operator ?? "—"}</dd>
                <dt>Status</dt><dd>{f.status ?? "—"}</dd>
                <dt>Capacity</dt><dd className="num">{f.capacity_value ? `${fmtNum(f.capacity_value, 0)} ${f.capacity_unit}` : "—"}</dd>
                <dt>Region</dt><dd>{[f.district, f.state].filter(Boolean).join(", ") || "—"}</dd>
                <dt>Confidence</dt><dd className="num">{f.confidence.toFixed(2)} ({f.source_count} independent source{f.source_count > 1 ? "s" : ""})</dd>
              </dl>
              <h4 style={{ margin: "14px 0 6px" }}>Source records</h4>
              <table className="table"><thead><tr><th scope="col">Source</th><th scope="col">Record</th><th scope="col">Dataset</th><th scope="col">Retrieved</th></tr></thead>
                <tbody>{(f.sources ?? []).map((s) => (
                  <tr key={s.source + s.external_id}><td>{SOURCE_NAMES[s.source] ?? s.source}</td>
                    <td>{s.url ? <ExtLink href={s.url}>{s.name ?? s.external_id}</ExtLink> : (s.name ?? s.external_id)}<div className="faint" style={{ fontSize: 11 }}>{s.source_type}</div></td>
                    <td className="faint" style={{ fontSize: 12 }}>{s.dataset_version ?? "—"}{s.published_at ? ` (${fmtDate(s.published_at)})` : ""}</td>
                    <td className="num" style={{ fontSize: 12 }}>{relTime(s.retrieved_at)}</td></tr>
                ))}</tbody></table>
            </div></section>
            <section className="panel"><div className="panel-head"><h2>Thermal history within 3 km</h2></div><div className="panel-body">
              <Async q={hist} empty={(h) => (h.events.length ? null : <Empty title="No thermal events linked">No FIRMS event has been attributed within 3 km in the loaded history.</Empty>)}>{(h) => (
                <div className="stack" style={{ gap: 12 }}>
                  <div className="metrics">
                    <div className="metric"><div className="label">Events ≤ {h.within_m / 1000} km</div><div className="value">{h.profile.events}</div><div className="hint">{h.profile.detections} detections</div></div>
                    <div className="metric"><div className="label">Persistent</div><div className="value">{h.profile.persistent}</div><div className="hint">{h.profile.active} active now</div></div>
                    <div className="metric"><div className="label">Peak FRP</div><div className="value">{fmtNum(h.profile.frp_max, 0)} <span style={{ fontSize: 12 }}>MW</span></div></div>
                    <div className="metric"><div className="label">Activity window</div><div className="value" style={{ fontSize: 14 }}>{fmtDate(h.profile.first_activity)} → {fmtDate(h.profile.last_activity)}</div><div className="hint">{h.profile.analyst_confirmed} analyst-confirmed</div></div>
                  </div>
                  <div className="chips">{h.profile.classifications.map((c) => <span key={c.classification} className="chip"><ClassLabel cls={c.classification === "unprocessed" ? null : c.classification as SourceClass} short /> {c.n}</span>)}</div>
                  <div className="faint" style={{ fontSize: 11.5 }}>{h.profile.note}</div>
                  <HBars rows={h.weekly.map((w) => ({ label: `week of ${fmtDate(w.week)}`, value: w.detections }))} color="var(--thermal)" />
                  <table className="table"><thead><tr><th scope="col">Event</th><th scope="col">Classification</th><th scope="col">Persistence</th><th scope="col">Status</th><th scope="col" className="right">Distance</th><th scope="col">Last seen</th></tr></thead>
                    <tbody>{h.events.map((e) => (
                      <tr key={e.id}><td><Link className="mono" to={`/events/${e.public_id}`}>{e.public_id}</Link></td><td><ClassLabel cls={e.classification} short /></td>
                        <td><PersistencePill p={e.persistence_class} /></td>
                        <td><StatePill state={(e.review_status === "analyst_confirmed" ? "ANALYST_CONFIRMED" : ["analyst_rejected", "false_positive"].includes(e.review_status) ? "ANALYST_REJECTED" : e.confidence_state) as DisplayState} title={STATE_META[e.confidence_state]?.hint} /></td>
                        <td className="right num">{fmtDistance(e.distance_m)}</td><td className="num">{relTime(e.last_detected)}</td></tr>
                    ))}</tbody></table>
                </div>
              )}</Async>
            </div></section>
          </div>
        </>
      )}</Async>
    </div>
  );
}
