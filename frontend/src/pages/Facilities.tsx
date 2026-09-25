import { Search } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Async, Empty } from "../components/ui";
import { fmtNum } from "../lib/format";
import { useFacilities } from "../lib/hooks";
import { FACILITY_LABELS, SOURCE_NAMES } from "../lib/taxonomy";

const TYPES = ["refinery", "oil_gas", "power_plant_coal", "power_plant_gas", "steel_plant", "cement_plant", "chemical_plant", "coal_mine", "mine", "factory", "industrial_area", "landfill", "power_plant_other"];

export default function Facilities() {
  const nav = useNavigate();
  const [type, setType] = useState<string>("");
  const [source, setSource] = useState<string>("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [withEvents, setWithEvents] = useState(true);
  const res = useFacilities({ facility_type: type || undefined, source: source || undefined, q: q || undefined, limit: 50, offset, with_events: withEvents });
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Facilities</h1><div className="sub">Consolidated from OpenStreetMap and facility registries. Confidence rises when independent sources agree. Coverage is incomplete.</div></div>
      </div>
      <div className="panel">
        <div className="panel-head" style={{ flexWrap: "wrap" }}>
          <div className="row" style={{ position: "relative" }}>
            <Search size={13} style={{ position: "absolute", left: 8 }} className="faint" aria-hidden />
            <input className="input" style={{ paddingLeft: 26, width: 220 }} placeholder="Name or operator" aria-label="Search facilities" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
          </div>
          <select className="select" aria-label="Facility type" value={type} onChange={(e) => { setType(e.target.value); setOffset(0); }}>
            <option value="">All types</option>{TYPES.map((t) => <option key={t} value={t}>{FACILITY_LABELS[t]}</option>)}
          </select>
          <select className="select" aria-label="Source" value={source} onChange={(e) => { setSource(e.target.value); setOffset(0); }}>
            <option value="">All sources</option>{["osm", "wri_gppd", "gem", "cea"].map((s) => <option key={s} value={s}>{SOURCE_NAMES[s]}</option>)}
          </select>
          <label className="check"><input type="checkbox" checked={withEvents} onChange={(e) => setWithEvents(e.target.checked)} /> Sort by thermal activity</label>
        </div>
        <Async q={res} lines={10} empty={(d) => (d.items.length ? null : <Empty title="No facilities match" />)}>{(d) => (
          <>
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Facility</th><th>Type</th><th>Operator</th><th className="right">Capacity</th><th>Sources</th><th className="right">Confidence</th><th className="right">Events ≤3 km</th></tr></thead>
              <tbody>{d.items.map((f) => (
                <tr key={f.id} className="click" tabIndex={0} onClick={() => nav(`/facilities/${f.id}`)} onKeyDown={(k) => k.key === "Enter" && nav(`/facilities/${f.id}`)}>
                  <td style={{ fontWeight: 500 }}>{f.name ?? <span className="faint">Unnamed</span>}<div className="faint mono" style={{ fontSize: 11 }}>{f.latitude.toFixed(3)}, {f.longitude.toFixed(3)}</div></td>
                  <td>{FACILITY_LABELS[f.facility_type] ?? f.facility_type}</td>
                  <td className="muted">{f.operator ?? "—"}</td>
                  <td className="right num">{f.capacity_value ? `${fmtNum(f.capacity_value, 0)} ${f.capacity_unit}` : "—"}</td>
                  <td>{SOURCE_NAMES[f.primary_source] ?? f.primary_source}{f.source_count > 1 && <span className="faint"> +{f.source_count - 1}</span>}</td>
                  <td className="right num">{f.confidence.toFixed(2)}</td>
                  <td className="right num">{f.event_count ?? 0}</td>
                </tr>
              ))}</tbody>
            </table></div>
            <div className="pager"><span>{d.total.toLocaleString()} facilities</span><span className="spacer" />
              <button className="btn sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button>
              <button className="btn sm" disabled={offset + 50 >= d.total} onClick={() => setOffset(offset + 50)}>Next</button></div>
          </>
        )}</Async>
      </div>
    </div>
  );
}
