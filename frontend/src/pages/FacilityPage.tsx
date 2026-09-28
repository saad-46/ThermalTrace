import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Eye } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { HBars } from "../components/charts";
import { ExtLink } from "../components/evidence";
import { FacilityContextMap, type MapView } from "../components/FacilityContextMap";
import { FacilityProfileSections, RelationshipContext } from "../components/facilityIntel";
import { KnowledgeBadge } from "../components/workspace";
import { PriorityPill } from "../components/triage";
import { Async, ClassLabel, Empty, ErrorState, errText, PersistencePill, Skeleton, StatePill, useToast } from "../components/ui";
import { api } from "../lib/api";
import { fmtDate, fmtDateTime, fmtDistance, fmtNum, relTime } from "../lib/format";
import { actions, useWatchlists } from "../lib/hooks";
import { useSession, useTheme } from "../lib/session";
import { FACILITY_LABELS, SOURCE_NAMES, STATE_META } from "../lib/taxonomy";
import type { DisplayState, ReviewStatus, Facility, FacilityProfile, FacilityRelationship, PersistenceClass, SourceClass } from "../lib/types";

interface FacEvent {
  id: string; public_id: string; first_detected: string; last_detected: string; classification: SourceClass; persistence_class: PersistenceClass;
  persistence_score: number | null; confidence_state: DisplayState; confidence_score: number | null; priority_score: number | null;
  review_status: ReviewStatus; display_state: DisplayState; status: string; observation_count: number; frp_max: number | null; brightness_max: number | null;
  distance_m: number; attribution_score: number; rank: number; latitude: number | null; longitude: number | null;
}
interface FacEvents {
  profile: FacilityProfile;
  within_m: number;
  total: number;
  events: FacEvent[];
  weekly: { week: string; detections: number; frp_max: number }[];
}
const PAGE = 50;


export default function FacilityPage() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const eventRef = params.get("event");
  const initialView = params.get("view") === "satellite" ? "satellite" : "map";
  const { can } = useSession();
  const [theme] = useTheme();
  const toast = useToast();
  const [limit, setLimit] = useState(PAGE);
  const fac = useQuery({ queryKey: ["facility", id], queryFn: () => api<Facility>(`/facilities/${id}`) });
  const hist = useQuery({ queryKey: ["facility-events", id, limit], queryFn: () => api<FacEvents>(`/facilities/${id}/events`, { query: { limit } }),
    placeholderData: keepPreviousData });
  const rel = useQuery({ queryKey: ["facility-rel", id, eventRef], enabled: !!eventRef,
    queryFn: () => api<FacilityRelationship>(`/facilities/${id}/relationship`, { query: { event: eventRef } }) });
  const wls = useWatchlists();
  const watch = async (wlId: string, f: Facility) => {
    try { await actions.addWatchItem(wlId)({ kind: "facility", label: f.name ?? FACILITY_LABELS[f.facility_type], facility_id: f.id, radius_m: 3000 }); toast("Facility added to watchlist"); }
    catch (e) { toast(errText(e), "error"); }
  };
  const mapFacility = useMemo(() => fac.data && { latitude: fac.data.latitude, longitude: fac.data.longitude, facility_type: fac.data.facility_type, name: fac.data.name,
    operator: fac.data.operator, status: fac.data.status }, [fac.data]);
  // keep ?view=satellite in the URL so the view survives reloads and can be linked to (replace: no extra history entries)
  const onViewChange = (v: MapView) => setParams((p) => { const n = new URLSearchParams(p); if (v === "satellite") n.set("view", "satellite"); else n.delete("view"); return n; }, { replace: true });
  const mapEvent = useMemo(() => rel.data && { latitude: rel.data.event.latitude, longitude: rel.data.event.longitude, public_id: rel.data.event.public_id }, [rel.data]);

  return (
    <div className="page">
      {eventRef
        ? <Link to={`/events/${eventRef}`} className="btn ghost sm" style={{ marginBottom: 10 }}><ArrowLeft size={13} /> Back to {eventRef}</Link>
        : <Link to="/facilities" className="btn ghost sm" style={{ marginBottom: 10 }}><ArrowLeft size={13} /> Facilities</Link>}
      <Async q={fac} lines={6}>{(f) => (
        <>
          <div className="page-head">
            <div style={{ minWidth: 0 }}>
              <div className="faint" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".06em" }}>Facility intelligence profile</div>
              <h1 data-testid="facility-name" style={{ overflowWrap: "anywhere" }}>{f.name ?? "Unnamed facility"}</h1>
              <div className="sub">{[FACILITY_LABELS[f.facility_type] ?? f.facility_type, f.subtype, f.status].filter(Boolean).join(" · ")}</div>
            </div>
            <div className="actions">
              {can("analyst") && wls.data && wls.data.length > 0 && (
                <select className="select" aria-label="Add to watchlist" defaultValue="" onChange={(e) => { if (e.target.value) watch(e.target.value, f); e.target.value = ""; }}>
                  <option value="" disabled>Add to watchlist…</option>{wls.data.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              )}
              <Link className="btn" to={`/map?lat=${f.latitude}&lon=${f.longitude}&z=12`}><Eye size={14} /> Map</Link>
            </div>
          </div>

          {eventRef && (
            <section className="panel" style={{ marginBottom: 12 }} data-testid="facility-relationship">
              <div className="panel-head"><h2>Investigation relationship</h2><span className="right"><KnowledgeBadge k="inferred" /></span></div>
              <div className="panel-body">
                {rel.isLoading ? <Skeleton lines={2} /> : rel.error ? <ErrorState error={rel.error} retry={() => rel.refetch()} /> : rel.data && (
                  <div className="stack" style={{ gap: 8 }}>
                    <dl className="kv">
                      <dt>Event</dt><dd><Link className="mono" to={`/events/${rel.data.event.public_id}`}>{rel.data.event.public_id}</Link> · <ClassLabel cls={rel.data.event.classification} short /> · <StatePill state={rel.data.event.confidence_state} /></dd>
                      <dt>Distance</dt><dd className="num">{fmtDistance(rel.data.distance_m)}{rel.data.bearing_deg != null ? ` (bearing ${fmtNum(rel.data.bearing_deg, 0)}°)` : ""} · {rel.data.distance_m <= rel.data.rule_radius_m ? `within the ${rel.data.rule_radius_m / 1000} km rule radius` : rel.data.distance_m <= rel.data.search_radius_m ? `within the ${rel.data.search_radius_m / 1000} km search radius` : "outside the search radius"}</dd>
                      <dt>Attribution</dt><dd>{rel.data.linked ? `Candidate #${rel.data.rank} for this event, score ${rel.data.attribution_score?.toFixed(2)}` : "Not an attribution candidate for this event"}</dd>
                    </dl>
                    <RelationshipContext rel={rel.data} />
                    <div className="faint" style={{ fontSize: 12 }}>{rel.data.note}</div>
                  </div>
                )}
              </div>
            </section>
          )}

          <div className="grid fac-grid">
            <section className="panel"><div className="panel-head"><h2>Overview</h2><span className="right"><KnowledgeBadge k="registry" /></span></div><div className="panel-body">
              <dl className="kv">
                <dt>Type</dt><dd>{FACILITY_LABELS[f.facility_type] ?? f.facility_type}{f.subtype ? ` · ${f.subtype}` : ""}</dd>
                <dt>Operator</dt><dd>{f.operator ?? "—"}</dd>
                <dt>Status</dt><dd>{f.status ?? "—"}</dd>
                <dt>Capacity</dt><dd className="num">{f.capacity_value ? `${fmtNum(f.capacity_value, 0)} ${f.capacity_unit ?? ""}` : "—"}</dd>
                <dt>Region</dt><dd>{[f.district, f.state].filter(Boolean).join(", ") || "—"}</dd>
                <dt>Coordinates</dt><dd className="mono">{f.latitude.toFixed(5)}, {f.longitude.toFixed(5)}</dd>
                <dt>Location confidence</dt><dd className="num">{f.confidence.toFixed(2)}</dd>
                {(f.registries ?? []).map((r, i) => (
                  <Fragment key={i}><dt>Registry</dt><dd>{String(r.source).toUpperCase()}{r.station ? `: ${r.station}` : ""}{r.coordinate_source ? ` (coordinates from ${SOURCE_NAMES[r.coordinate_source] ?? r.coordinate_source})` : ""}</dd></Fragment>
                ))}
              </dl>
            </div></section>
            <section className="panel" data-tour-id="facility-satellite"><div className="panel-head"><h2>Map context</h2><span className="right"><KnowledgeBadge k="registry" /></span></div><div className="panel-body" style={{ padding: 0 }}>
              {mapFacility && <FacilityContextMap key={f.id} facility={mapFacility} event={mapEvent} distanceM={rel.data?.distance_m} theme={theme}
                nearby={hist.data?.events} initialView={initialView} onViewChange={onViewChange} />}
              <div className="faint" style={{ fontSize: 11.5, padding: "8px 12px" }}>
                Rings: {eventRef ? "around the selected event" : "around the facility"}: 2 km (rule "near" threshold) and 10 km (facility search radius).
              </div>
            </div></section>
          </div>

          <div style={{ marginTop: 12 }}><FacilityProfileSections id={f.id} /></div>

          <section className="panel" style={{ marginTop: 12 }}><div className="panel-head"><h2>Provenance</h2><span className="right"><KnowledgeBadge k="registry" /></span></div><div className="panel-body">
            <div className="faint" style={{ fontSize: 12, marginBottom: 8 }}>
              {f.source_count} independent source{f.source_count > 1 ? "s" : ""} list this facility. Agreement between sources raises confidence in its identity and location; it is not certainty that the facility is operating or emitting.
            </div>
            <div className="table-wrap">
              <table className="table"><thead><tr><th scope="col">Source</th><th scope="col">Record</th><th scope="col">Dataset</th><th scope="col">Retrieved</th></tr></thead>
                <tbody>{(f.sources ?? []).map((s) => (
                  <tr key={s.source + s.external_id}><td>{SOURCE_NAMES[s.source] ?? s.source}</td>
                    <td>{s.url ? <ExtLink href={s.url}>{s.name ?? s.external_id}</ExtLink> : (s.name ?? s.external_id)}<div className="faint" style={{ fontSize: 11 }}>{s.source_type}</div></td>
                    <td className="faint" style={{ fontSize: 12 }}>{s.dataset_version ?? "—"}{s.published_at ? ` (${fmtDate(s.published_at)})` : ""}</td>
                    <td className="num" style={{ fontSize: 12 }}>{relTime(s.retrieved_at)}</td></tr>
                ))}</tbody></table>
            </div>
          </div></section>

          <section className="panel" style={{ marginTop: 12 }}><div className="panel-head"><h2>Thermal activity within 3 km</h2><span className="right"><KnowledgeBadge k="observed" /></span></div><div className="panel-body">
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
                <h4 style={{ margin: 0 }}>Activity timeline (detections per week)</h4>
                <HBars rows={h.weekly.map((w) => ({ label: `week of ${fmtDate(w.week)}`, value: w.detections }))} color="var(--thermal)" />
                <div className="table-wrap">
                  <table className="table" data-testid="facility-events"><thead><tr>
                    <th scope="col">Event</th><th scope="col">Last seen</th><th scope="col" className="right">Distance</th><th scope="col">Persistence</th>
                    <th scope="col" className="right">Peak FRP</th><th scope="col" className="right">Brightness</th><th scope="col">Classification</th>
                    <th scope="col">Confidence</th><th scope="col">Priority</th></tr></thead>
                    <tbody>{h.events.map((e) => (
                      <tr key={e.id} className={e.public_id === eventRef ? "row-selected" : undefined}>
                        <td><Link className="mono" to={`/events/${e.public_id}`}>{e.public_id}</Link><div className="faint" style={{ fontSize: 11 }}>{e.observation_count} obs.</div></td>
                        <td className="num" title={fmtDateTime(e.last_detected)}>{relTime(e.last_detected)}</td>
                        <td className="right num">{fmtDistance(e.distance_m)}</td>
                        <td><PersistencePill p={e.persistence_class} /></td>
                        <td className="right num">{e.frp_max == null ? "—" : `${fmtNum(e.frp_max, 1)} MW`}</td>
                        <td className="right num">{e.brightness_max == null ? "—" : `${fmtNum(e.brightness_max, 0)} K`}</td>
                        <td><ClassLabel cls={e.classification} short /></td>
                        <td><StatePill state={e.display_state} title={STATE_META[e.confidence_state]?.hint} />{e.confidence_score != null && <span className="faint num" style={{ fontSize: 11 }}> {e.confidence_score.toFixed(2)}</span>}</td>
                        <td><PriorityPill score={e.priority_score} /></td>
                      </tr>
                    ))}</tbody></table>
                </div>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="faint" style={{ fontSize: 12 }}>Showing {h.events.length} of {h.total}</span>
                  {h.events.length < h.total && <button className="btn sm" onClick={() => setLimit((n) => Math.min(n + PAGE, 200))} disabled={hist.isFetching || limit >= 200}>
                    {limit >= 200 ? "Showing the 200 most recent" : hist.isFetching ? "Loading…" : "Load more"}</button>}
                </div>
              </div>
            )}</Async>
          </div></section>
        </>
      )}</Async>
    </div>
  );
}
