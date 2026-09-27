/** Two events side by side for investigation. Facts only: no ranking, no winner, no score. */
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { PriorityPill } from "../components/triage";
import { Async, ClassLabel, Empty, PersistencePill, ReviewPill, StatePill } from "../components/ui";
import { api } from "../lib/api";
import { compass, fmtDateTime, fmtDistance, fmtNum } from "../lib/format";
import { FACILITY_LABELS } from "../lib/taxonomy";
import type { Compare, CompareRecord, ReviewStatus } from "../lib/types";

type Row = [string, (r: CompareRecord) => React.ReactNode];

const ROWS: Row[] = [
  ["Location", (r) => <>{[r.place, r.state].filter(Boolean).join(", ") || "—"} <span className="faint mono" style={{ fontSize: 11 }}>{r.latitude.toFixed(3)}, {r.longitude.toFixed(3)}</span></>],
  ["Observed", (r) => `${fmtDateTime(r.first_detected)} → ${fmtDateTime(r.last_detected)}`],
  ["Classification", (r) => <ClassLabel cls={r.classification} />],
  ["Confidence", (r) => <><StatePill state={r.display_state} /> <span className="num faint">{fmtNum(r.confidence_score, 2)}</span></>],
  ["Triage priority", (r) => <PriorityPill score={r.priority_score} />],
  ["FRP", (r) => `peak ${fmtNum(r.frp_max, 1)} MW · mean ${fmtNum(r.frp_mean, 1)} MW`],
  ["Brightness", (r) => (r.brightness_max != null ? `max ${fmtNum(r.brightness_max, 0)} K` : "not reported")],
  ["Persistence", (r) => <><PersistencePill p={r.persistence_class} /> <span className="faint">{r.days_active} active day(s), {r.observation_count} detections</span></>],
  ["Facility", (r) => (r.facility ? `${r.facility.name ?? "Unnamed"} (${FACILITY_LABELS[r.facility.type] ?? r.facility.type})` : "None within 10 km")],
  ["Facility distance", (r) => (r.facility ? `${fmtDistance(r.facility.distance_m)} · attribution #${r.facility.rank}, ${r.facility.attribution_score.toFixed(2)}` : "—")],
  ["Land cover", (r) => (r.landcover ? `${r.landcover.dominant.replace(/_/g, " ")}${r.landcover.share != null ? ` ${Math.round(r.landcover.share * 100)}%` : ""}` : "Not retrieved")],
  ["Weather", (r) => (r.weather ? `${r.weather.condition ?? "—"}, ${fmtNum(r.weather.temperature_c, 1)} °C, wind ${fmtNum(r.weather.wind_speed_ms, 1)} m/s from ${compass(r.weather.wind_direction_deg)}` : "Not retrieved")],
  ["Imagery", (r) => (r.imagery.scenes ? `${r.imagery.scenes} Sentinel-2 scene(s)` : "No scene stored")],
  ["NDVI / NBR", (r) => (r.imagery.spectral_status === "ok" && r.imagery.deltas
    ? `NDVI ${r.imagery.deltas.ndvi >= 0 ? "+" : ""}${r.imagery.deltas.ndvi.toFixed(2)}, NBR ${r.imagery.deltas.nbr >= 0 ? "+" : ""}${r.imagery.deltas.nbr.toFixed(2)} (${(r.imagery.finding ?? "").replace(/_/g, " ")})`
    : r.imagery.reason ?? "Not computed")],
  ["SHAP (top features)", (r) => (r.shap_top?.length ? r.shap_top.map((c) => `${c.feature} ${c.contribution >= 0 ? "+" : ""}${c.contribution.toFixed(2)}`).join(" · ") : "No trained-model explanation")],
  ["Review state", (r) => <ReviewPill status={r.review_status as ReviewStatus} />],
  ["Evidence availability", (r) => `${r.completeness.available} / ${r.completeness.total} stages`],
];

function Picker({ a, b }: { a: string; b: string }) {
  const [x, setX] = useState(a), [y, setY] = useState(b);
  const nav = useNavigate();
  return (
    <form className="row wrap" style={{ gap: 6 }} onSubmit={(e) => { e.preventDefault(); nav(`/compare?a=${encodeURIComponent(x.trim().toUpperCase())}&b=${encodeURIComponent(y.trim().toUpperCase())}`); }}>
      <input className="input" aria-label="First event" placeholder="TT-…" value={x} onChange={(e) => setX(e.target.value)} style={{ width: 170 }} />
      <input className="input" aria-label="Second event" placeholder="TT-…" value={y} onChange={(e) => setY(e.target.value)} style={{ width: 170 }} />
      <button className="btn" type="submit" disabled={!x.trim() || !y.trim()}>Compare</button>
    </form>
  );
}

export default function ComparePage() {
  const [params] = useSearchParams();
  const a = params.get("a") ?? "", b = params.get("b") ?? "";
  const q = useQuery({ queryKey: ["compare", a, b], enabled: !!a && !!b, queryFn: () => api<Compare>("/events/compare", { query: { a, b } }) });
  return (
    <div className="page">
      {a && <Link to={`/events/${a}`} className="btn ghost sm" style={{ marginBottom: 10 }}><ArrowLeft size={13} /> Back to {a}</Link>}
      <div className="page-head">
        <div><h1>Compare events</h1><div className="sub">Recorded evidence side by side, for investigation. No ranking and no winner; similar values do not mean a shared cause.</div></div>
        <div className="actions"><Picker a={a} b={b} /></div>
      </div>
      {!a || !b ? <Empty title="Choose two events">Enter two event ids, or use Compare from an event or its similar events.</Empty> : (
        <Async q={q} lines={10}>{(c) => (
          <div className="stack" style={{ gap: 10 }} data-testid="compare-page">
            <div className="faint" style={{ fontSize: 12 }}>The events are {fmtDistance(c.distance_m)} apart. {c.note}</div>
            <div className="table-wrap">
              <table className="table compare-table cards-on-mobile">
                <caption className="sr-only">Recorded evidence for {c.a.public_id} and {c.b.public_id}, side by side. No ranking.</caption>
                <thead><tr>
                  <th scope="col">Evidence</th>
                  {[c.a, c.b].map((r) => <th key={r.id} scope="col"><Link className="mono" to={`/events/${r.public_id}`}>{r.public_id}</Link></th>)}
                </tr></thead>
                <tbody>{ROWS.map(([label, f]) => (
                  <tr key={label}>
                    <th scope="row">{label}</th>
                    <td data-label={c.a.public_id}>{f(c.a)}</td>
                    <td data-label={c.b.public_id}>{f(c.b)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </div>
        )}</Async>
      )}
    </div>
  );
}
