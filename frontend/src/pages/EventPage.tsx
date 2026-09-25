import { ArrowLeft, Map as MapIcon } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { AnswerGrid, ConfidenceBreakdown, EvidenceList, EvidenceMatrix, FacilityList, Fingerprint, ModelPanel, PersistencePanel, Provenance, Timeline } from "../components/evidence";
import { EventActions, EventHeader, ReviewPanel, SatellitePanel, SimilarEvents, WeatherPanel } from "../components/investigation";
import { EvidenceChain, PriorityPanel } from "../components/triage";
import { ErrorState, Skeleton } from "../components/ui";
import { useEvent } from "../lib/hooks";

function P({ title, children, flush }: { title: string; children: React.ReactNode; flush?: boolean }) {
  return (
    <section className="panel"><div className="panel-head"><h2>{title}</h2></div><div className={`panel-body ${flush ? "flush" : ""}`}>{children}</div></section>
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
      <div className="row" style={{ marginBottom: 10 }}>
        <Link to="/events" className="btn ghost sm"><ArrowLeft size={13} /> Events</Link>
        <Link to={`/map?event=${ev.public_id}`} className="btn ghost sm"><MapIcon size={13} /> Show on map</Link>
      </div>
      <div className="page-head" style={{ alignItems: "flex-start" }}>
        <EventHeader ev={ev} />
        <div className="actions"><EventActions ev={ev} /></div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.35fr) minmax(0, 1fr)", gap: 12, alignItems: "start" }}>
        <div className="stack" style={{ gap: 12 }}>
          <P title="Investigation summary"><AnswerGrid ev={ev} /></P>
          <P title="Evidence chain"><EvidenceChain ev={ev} /></P>
          <P title="Evidence confidence matrix" flush><div className="table-wrap"><EvidenceMatrix ev={ev} /></div></P>
          <P title="Evidence bundle">
            {(["observed", "derived", "external", "model"] as const).map((k) => {
              const items = ev.evidence.filter((e) => e.knowledge_type === k);
              return items.length ? <div key={k} style={{ marginBottom: 10 }}><h4 style={{ marginBottom: 4 }}>{{ observed: "Observed", derived: "Derived", external: "External context", model: "Model output" }[k]}</h4><EvidenceList items={items} /></div> : null;
            })}
          </P>
          <P title="Nearby facilities" flush><div className="table-wrap"><FacilityList ev={ev} /></div></P>
          <P title="Persistence & evolution"><PersistencePanel ev={ev} /></P>
          <P title="Data provenance" flush><Provenance ev={ev} /></P>
        </div>
        <div className="stack" style={{ gap: 12 }}>
          <P title="Analyst review"><ReviewPanel ev={ev} /></P>
          <P title="Confidence components"><ConfidenceBreakdown ev={ev} /></P>
          <P title="Why is this prioritised?"><PriorityPanel p={ev.priority_components} /></P>
          <P title="Model evidence"><ModelPanel ev={ev} /></P>
          <P title="Satellite imagery"><SatellitePanel ev={ev} /></P>
          <P title="Weather at last detection"><WeatherPanel ev={ev} /></P>
          <P title="Thermal fingerprint"><Fingerprint ev={ev} /></P>
          <P title="Timeline"><Timeline ev={ev} /></P>
          <P title="Similar events"><SimilarEvents ev={ev} /></P>
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
