import { ArrowLeft, Columns2, Map as MapIcon, Network, Presentation } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AnswerGrid, ConfidenceBreakdown, EvidenceList, EvidenceMatrix, FacilityList, Fingerprint, ModelPanel, PersistencePanel, Provenance } from "../components/evidence";
import { EventActions, EventHeader, ReviewPanel, SatellitePanel, SimilarEvents, WeatherPanel } from "../components/investigation";
import { LandCoverPanel, SpectralChangePanel } from "../components/landcover";
import { PriorityPanel, PriorityPill } from "../components/triage";
import { ErrorState, PersistencePill, Skeleton, StatePill } from "../components/ui";
import {
  ActivityChart, ClassificationExplained, EventTimeline, EvidenceCompleteness, InvestigationStages, RecurrencePanel,
} from "../components/workspace";
import { useEvent } from "../lib/hooks";
import { coordsLabel, fmtDateTime, fmtDistance, fmtNum, locationLabel, relTime } from "../lib/format";
import { CLASS_META } from "../lib/taxonomy";
import type { EventDetail } from "../lib/types";

function P({ title, children, flush, tourId, right }: { title: string; children: React.ReactNode; flush?: boolean; tourId?: string; right?: React.ReactNode }) {
  return (
    <section className="panel" data-tour-id={tourId}>
      <div className="panel-head"><h2>{title}</h2>{right && <span className="right">{right}</span>}</div>
      <div className={`panel-body ${flush ? "flush" : ""}`}>{children}</div>
    </section>
  );
}

/** Compact facts under the header: what the analyst needs at a glance, each from the event record. */
export function InvestigationStatus({ ev }: { ev: EventDetail }) {
  const top = ev.facilities[0];
  const items: [string, React.ReactNode][] = [
    ["Location", <>{locationLabel(ev) || "—"} <span className="faint mono" style={{ fontSize: 11 }}>{coordsLabel(ev)}</span></>],
    ["Observed", `${fmtDateTime(ev.first_detected)} → ${fmtDateTime(ev.last_detected)}`],
    ["Interpretation", ev.classification ? CLASS_META[ev.classification].label : "Not classified"],
    ["Confidence", <><StatePill state={ev.display_state} /> <span className="num faint">{fmtNum(ev.confidence_score, 2)}</span></>],
    ["Triage priority", <PriorityPill score={ev.priority_score} tier={ev.priority_components?.tier} />],
    ["Persistence", <><PersistencePill p={ev.persistence_class} /> <span className="faint">{ev.days_active} day(s)</span></>],
    ["Nearest facility", top ? `${top.name ?? "Unnamed"} · ${fmtDistance(top.distance_m)}` : "None within 10 km"],
  ];
  const fr = ev.evidence_stages?.freshness;
  const when = (v: string | null | undefined) => (v ? <span title={fmtDateTime(v)}>{relTime(v)}</span> : "—");
  items.push(
    ["Heat last observed", when(fr?.latest_observation_at ?? ev.last_detected)],
    ["Evidence refreshed", fr ? when(fr.latest_evidence_refresh_at) : "—"],
    ["Record updated", when(fr?.record_updated_at ?? ev.updated_at)],
  );
  return (
    <div className="inv-status" data-testid="investigation-status">
      {items.map(([k, v]) => <div key={k} className="inv-fact"><span className="inv-k">{k}</span><span className="inv-v">{v}</span></div>)}
      <div className="inv-fact wide"><EvidenceCompleteness ev={ev} compact /></div>
    </div>
  );
}

function CompareLauncher({ ev }: { ev: EventDetail }) {
  const [open, setOpen] = useState(false);
  const [other, setOther] = useState("");
  const nav = useNavigate();
  if (!open) return <button className="btn ghost sm" onClick={() => setOpen(true)}><Columns2 size={13} /> Compare…</button>;
  return (
    <form className="row" style={{ gap: 4 }} onSubmit={(e) => { e.preventDefault(); if (other.trim()) nav(`/compare?a=${ev.public_id}&b=${encodeURIComponent(other.trim().toUpperCase())}`); }}>
      <input className="input sm" autoFocus placeholder="Other event id (TT-…)" value={other} onChange={(e) => setOther(e.target.value)} aria-label="Event to compare with" style={{ width: 170 }} />
      <button className="btn sm" type="submit" disabled={!other.trim()}>Compare</button>
      <button className="btn ghost sm" type="button" onClick={() => setOpen(false)}>Cancel</button>
    </form>
  );
}

export default function EventPage() {
  const { ref } = useParams();
  const q = useEvent(ref);
  if (q.isLoading) return <div className="page"><Skeleton lines={10} /></div>;
  if (q.error || !q.data) return <div className="page"><ErrorState error={q.error ?? "Not found"} retry={() => q.refetch()} /></div>;
  const ev = q.data;
  return (
    <div className="page">
      <div className="row wrap" style={{ marginBottom: 10, gap: 6 }}>
        <Link to="/events" className="btn ghost sm"><ArrowLeft size={13} /> Events</Link>
        <Link to={`/map?event=${ev.public_id}`} className="btn ghost sm"><MapIcon size={13} /> Show on map</Link>
        <Link to={`/events/${ev.public_id}/cluster`} className="btn ghost sm" data-tour-id="view-cluster"><Network size={13} /> View cluster</Link>
        <CompareLauncher ev={ev} />
        <Link to={`/events/${ev.public_id}/view`} className="btn ghost sm"><Presentation size={13} /> Shareable view</Link>
      </div>
      <div className="page-head" style={{ alignItems: "flex-start" }} data-tour-id="event-header">
        <EventHeader ev={ev} />
        <div className="actions" data-tour-id="event-actions"><EventActions ev={ev} /></div>
      </div>
      <InvestigationStatus ev={ev} />
      <div className="workspace-grid">
        <div className="stack" style={{ gap: 12 }}>
          <P title="Investigation summary" tourId="investigation-summary"><AnswerGrid ev={ev} /></P>
          <P title="How ThermalTrace thinks" tourId="evidence-chain"><InvestigationStages ev={ev} /></P>
          <P title="Event timeline" tourId="event-timeline"><EventTimeline ev={ev} /></P>
          <P title="Activity and persistence" tourId="persistence-panel"><div className="stack" style={{ gap: 12 }}><ActivityChart ev={ev} /><PersistencePanel ev={ev} /></div></P>
          <P title="Explainable classification" tourId="classification-explained"><ClassificationExplained ev={ev} /></P>
          <P title="Evidence confidence matrix" flush><div className="table-wrap"><EvidenceMatrix ev={ev} /></div></P>
          <P title="Evidence bundle">
            {(["observed", "derived", "external", "model"] as const).map((k) => {
              const items = ev.evidence.filter((e) => e.knowledge_type === k);
              return items.length ? <div key={k} style={{ marginBottom: 10 }}><h4 style={{ marginBottom: 4 }}>{{ observed: "Observed", derived: "Derived", external: "External context", model: "Model output (inferred)" }[k]}</h4><EvidenceList items={items} /></div> : null;
            })}
          </P>
          <P title="Nearby facilities" flush><div className="table-wrap"><FacilityList ev={ev} /></div></P>
          <P title="Land cover (ESA WorldCover)" tourId="landcover-panel"><LandCoverPanel ev={ev} /></P>
          <P title="Recurring activity at this location" tourId="recurring-activity"><RecurrencePanel ev={ev} /></P>
          <P title="Data provenance" flush><Provenance ev={ev} /></P>
        </div>
        <div className="stack" style={{ gap: 12 }}>
          <P title="Analyst review" tourId="review-panel"><ReviewPanel ev={ev} /></P>
          <P title="Evidence availability" tourId="evidence-completeness"><EvidenceCompleteness ev={ev} /></P>
          <P title="Spectral change (NDVI / NBR)" tourId="spectral-panel"><SpectralChangePanel ev={ev} /></P>
          <P title="Satellite imagery"><SatellitePanel ev={ev} /></P>
          <P title="Weather at last detection"><WeatherPanel ev={ev} /></P>
          <P title="Confidence components"><ConfidenceBreakdown ev={ev} /></P>
          <P title="Why is this prioritised?"><PriorityPanel p={ev.priority_components} /></P>
          <P title="Model evidence" tourId="model-panel"><ModelPanel ev={ev} /></P>
          <P title="Thermal fingerprint"><Fingerprint ev={ev} /></P>
          <P title="Similar observed events" tourId="similar-events"><SimilarEvents ev={ev} /></P>
          {ev.data_quality_detail && (
            <P title={`Data quality: ${ev.data_quality_detail.grade}`}>
              <table className="table"><tbody>{ev.data_quality_detail.factors.map((f) => (
                <tr key={f.factor}><td>{f.factor.replace(/_/g, " ")}</td><td className="num">{f.score.toFixed(2)}</td><td className="muted" style={{ fontSize: 12 }}>{f.detail}</td></tr>
              ))}</tbody></table>
            </P>
          )}
        </div>
      </div>
    </div>
  );
}
