import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { DEFAULT_FILTERS, FilterButton, TimeRange, toQuery, type FilterState } from "../components/filters";
import { PriorityPill } from "../components/triage";
import { Async, ClassLabel, Empty, ModePill, PersistencePill, StatePill } from "../components/ui";
import { coordsLabel, fmtDistance, fmtDuration, fmtNum, locationLabel, relTime } from "../lib/format";
import { useEvents } from "../lib/hooks";

const SORTS: [string, string][] = [["priority", "Triage priority"], ["last_detected", "Most recent"], ["confidence", "Confidence"], ["frp", "Peak FRP"], ["persistence", "Persistence"], ["observations", "Detections"]];
const QUEUES: [string, string, Partial<FilterState>][] = [
  ["all", "All events", {}],
  ["review", "Needs review", { confidence_state: ["INSUFFICIENT_EVIDENCE", "LOW_CONFIDENCE"] }],
  ["persistent", "Persistent", { persistence: ["persistent"] }],
  ["industrial", "Industrial", { classification: ["flare", "process_heat", "coal_seam_fire", "industrial_fire"] }],
];

export default function Events() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  // Deep links from global search, e.g. /events?classification=flare
  const [filters, setFilters] = useState<FilterState>({
    ...DEFAULT_FILTERS, min_observations: null, days: params.get("classification") ? null : DEFAULT_FILTERS.days,
    classification: params.getAll("classification"),
  });
  const [queue, setQueue] = useState("all");
  const [sort, setSort] = useState("priority");
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const limit = 50;
  const merged = useMemo(() => ({ ...filters, ...QUEUES.find((x) => x[0] === queue)![2], q }), [filters, queue, q]);
  const query = useMemo(() => toQuery(merged as FilterState), [merged]);
  const res = useEvents(query, sort, limit, offset);
  const setF = (f: FilterState) => { setFilters(f); setOffset(0); };

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Thermal events</h1><div className="sub">Spatio-temporal clusters of FIRMS detections, each with classification, confidence and evidence. Confidence reflects the supporting evidence, not the probability of a fire.</div></div>
      </div>
      <div className="panel" data-tour-id="events-table">
        <div className="panel-head" style={{ flexWrap: "wrap", gap: 8 }}>
          <div className="seg" role="tablist" aria-label="Queue">
            {QUEUES.map(([k, l]) => <button key={k} role="tab" aria-selected={queue === k} className={queue === k ? "on" : ""} onClick={() => { setQueue(k); setOffset(0); }}>{l}</button>)}
          </div>
          <TimeRange value={filters.days} onChange={(days) => setF({ ...filters, days })} />
          <FilterButton f={filters} set={setF} />
          <div className="row right" style={{ marginLeft: "auto" }}>
            <div className="row" style={{ position: "relative" }}>
              <Search size={13} style={{ position: "absolute", left: 8 }} className="faint" aria-hidden />
              <input className="input" style={{ paddingLeft: 26, width: 220 }} placeholder="ID, district, state, facility" aria-label="Search events" value={q}
                onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
            </div>
            <label className="sr-only" htmlFor="sort">Sort</label>
            <select id="sort" className="select" value={sort} onChange={(e) => setSort(e.target.value)}>
              {SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </div>
        </div>
        <Async q={res} lines={10} empty={(d) => (d.items.length ? null : <Empty title="No events match">Widen the time range or clear filters.</Empty>)}>
          {(d) => (
            <>
              <div className="table-wrap">
                <table className="table">
                  <thead><tr>
                    <th scope="col">Event</th><th scope="col">Priority</th><th scope="col">Location</th><th scope="col">Classification</th><th scope="col">Persistence</th><th scope="col">Status</th>
                    <th scope="col" className="right">Detections</th><th scope="col" className="right">Peak FRP</th><th scope="col">Nearest facility</th><th scope="col">Last seen</th>
                  </tr></thead>
                  <tbody>
                    {d.items.map((e) => (
                      <tr key={e.id} className="click" tabIndex={0} onClick={() => nav(`/events/${e.public_id}`)} onKeyDown={(k) => k.key === "Enter" && nav(`/events/${e.public_id}`)}>
                        <td><span className="mono">{e.public_id}</span>{e.data_mode !== "live" && <> <ModePill mode={e.data_mode} /></>}</td>
                        <td><PriorityPill score={e.priority_score} /></td>
                        <td>{locationLabel(e) || <span className="faint">Unnamed</span>} <span className="faint mono" style={{ fontSize: 11 }}>{coordsLabel(e)}</span></td>
                        <td><ClassLabel cls={e.classification} short /></td>
                        <td className="nowrap"><PersistencePill p={e.persistence_class} /> <span className="faint">{fmtDuration(e.duration_hours)}</span></td>
                        <td><StatePill state={e.display_state} /></td>
                        <td className="right num">{e.observation_count} <span className="faint">/{e.sensor_count}</span></td>
                        <td className="right num">{fmtNum(e.frp_max)} MW</td>
                        <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {e.nearest_facility_name || e.nearest_facility_type ? <>{fmtDistance(e.nearest_facility_distance_m)} · {e.nearest_facility_name ?? e.nearest_facility_type}</> : <span className="faint">—</span>}
                        </td>
                        <td className="num">{relTime(e.last_detected)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pager">
                <span>{d.total.toLocaleString()} events</span><span className="spacer" />
                <button className="btn sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
                <span className="num">{offset + 1}–{Math.min(offset + limit, d.total)}</span>
                <button className="btn sm" disabled={offset + limit >= d.total} onClick={() => setOffset(offset + limit)}>Next</button>
              </div>
            </>
          )}
        </Async>
      </div>
    </div>
  );
}
