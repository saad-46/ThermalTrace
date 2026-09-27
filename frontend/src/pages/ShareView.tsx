/** Read-only investigation view for presentation, review, reporting and screen sharing: the evidence as recorded, with
 *  no action or admin controls. Opens outside the application shell and prints cleanly. */
import { ArrowLeft, Printer } from "lucide-react";
import { Fragment } from "react";
import { Link, useParams } from "react-router-dom";
import { Flame } from "../components/brand";
import { ContextMap } from "../components/ContextMap";
import { EventHeader } from "../components/investigation";
import { ErrorState, ReviewPill, Skeleton } from "../components/ui";
import { ActivityChart, ClassificationExplained, EvidenceCompleteness, KnowledgeBadge, StageState, freshness } from "../components/workspace";
import { fmtDateTime, fmtDistance, titleCase } from "../lib/format";
import { useEvent } from "../lib/hooks";
import { useTheme } from "../lib/session";
import { FACILITY_LABELS, reviewLabel } from "../lib/taxonomy";
import { InvestigationStatus } from "./EventPage";

export default function ShareView() {
  const { ref } = useParams();
  const q = useEvent(ref);
  const [theme] = useTheme();
  if (q.isLoading) return <div className="share"><Skeleton lines={12} /></div>;
  if (q.error || !q.data) return <div className="share"><ErrorState error={q.error ?? "Not found"} retry={() => q.refetch()} /></div>;
  const ev = q.data;
  const stages = ev.evidence_stages?.stages ?? [];
  const by = Object.fromEntries(stages.map((s) => [s.key, s]));
  const top = ev.facilities[0];
  return (
    <div className="share" data-testid="share-view">
      <header className="share-bar no-print">
        <span className="row" style={{ gap: 8 }}><Flame size={18} /> <b>ThermalTrace</b> <span className="faint">· read-only investigation view</span></span>
        <span className="row" style={{ gap: 6 }}>
          <Link className="btn ghost sm" to={`/events/${ev.public_id}`}><ArrowLeft size={13} /> Workspace</Link>
          <button className="btn sm" onClick={() => window.print()}><Printer size={13} /> Print</button>
        </span>
      </header>
      <div className="share-body">
        <EventHeader ev={ev} />
        <InvestigationStatus ev={ev} />
        <div className="share-grid">
          <section className="panel"><div className="panel-head"><h2>Map</h2></div><div className="panel-body" style={{ padding: 0 }}>
            <ContextMap theme={theme} rings={{ latitude: ev.latitude, longitude: ev.longitude }}
              events={[{ id: ev.id, public_id: ev.public_id, latitude: ev.latitude, longitude: ev.longitude, classification: ev.classification, focus: true }]}
              facilities={ev.facilities.slice(0, 8)} height={300} />
            <div className="faint" style={{ fontSize: 11.5, padding: "6px 12px" }}>Rings: 2 km (rule threshold) and 10 km (facility search radius) around the event.</div>
          </div></section>
          <section className="panel"><div className="panel-head"><h2>Evidence availability</h2></div><div className="panel-body"><EvidenceCompleteness ev={ev} /></div></section>
        </div>
        <section className="panel"><div className="panel-head"><h2>How ThermalTrace thinks</h2></div>
          <div className="table-wrap"><table className="table cards-on-mobile"><thead><tr><th scope="col">#</th><th scope="col">Stage</th><th scope="col">State</th><th scope="col">Value</th><th scope="col">Kind</th><th scope="col">Freshness</th><th scope="col">Limitation</th></tr></thead>
            <tbody>{stages.map((s, i) => (
              <tr key={s.key}><td data-label="#" className="num">{i + 1}</td><td data-label="Stage"><b>{s.title}</b></td><td data-label="State"><StageState s={s.state} /></td>
                <td data-label="Value">{s.value}{s.reason && s.state !== "available" ? <div className="faint" style={{ fontSize: 11.5 }}>{s.reason}</div> : null}</td>
                <td data-label="Kind"><KnowledgeBadge k={s.knowledge} /></td><td data-label="Freshness" className="faint">{freshness(s)}</td>
                <td data-label="Limitation" className="faint" style={{ fontSize: 11.5 }}>{s.limitation}</td></tr>
            ))}</tbody></table></div>
        </section>
        <div className="share-grid">
          <section className="panel"><div className="panel-head"><h2>Classification</h2></div><div className="panel-body"><ClassificationExplained ev={ev} /></div></section>
          <div className="stack" style={{ gap: 12 }}>
            <section className="panel"><div className="panel-head"><h2>Facility</h2></div><div className="panel-body">
              {top ? (
                <dl className="kv">
                  <dt>Facility</dt><dd>{top.name ?? "Unnamed"} ({FACILITY_LABELS[top.facility_type] ?? top.facility_type})</dd>
                  <dt>Distance</dt><dd>{fmtDistance(top.distance_m)}</dd>
                  <dt>Attribution</dt><dd>candidate #{top.rank}, score {top.attribution_score.toFixed(2)}</dd>
                  <dt>Sources</dt><dd>{top.source_count}</dd>
                </dl>
              ) : <div className="faint">No mapped facility within 10 km.</div>}
              <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>Attribution is supporting evidence from proximity, not proof of causation.</div>
            </div></section>
            <section className="panel"><div className="panel-head"><h2>Imagery status</h2></div><div className="panel-body">
              <dl className="kv">
                {["satellite", "spectral", "weather", "landcover"].map((k) => by[k] && (
                  <Fragment key={k}><dt>{by[k].title}</dt><dd><StageState s={by[k].state} /> {by[k].state === "available" ? by[k].value : by[k].reason ?? ""}</dd></Fragment>
                ))}
              </dl>
            </div></section>
          </div>
        </div>
        <section className="panel"><div className="panel-head"><h2>Thermal activity</h2></div><div className="panel-body"><ActivityChart ev={ev} /></div></section>
        <section className="panel"><div className="panel-head"><h2>Analyst conclusion</h2></div><div className="panel-body stack" style={{ gap: 8 }}>
          <div className="row wrap" style={{ gap: 8 }}>
            <ReviewPill status={ev.review_status} />
            <span className="faint">{ev.reviews.length
              ? "A human decision, separate from the automated interpretation above."
              : "No analyst decision recorded. The interpretation above is automated."}</span>
          </div>
          {ev.reviews.length > 0 && (
            <div className="table-wrap"><table className="table cards-on-mobile"><thead><tr><th scope="col">When</th><th scope="col">Reviewer</th><th scope="col">Decision</th><th scope="col">Status change</th><th scope="col">Reason</th></tr></thead>
              <tbody>{ev.reviews.map((r) => (
                <tr key={r.id}><td data-label="When" className="num">{fmtDateTime(r.created_at)}</td><td data-label="Reviewer">{r.reviewer ?? "analyst"}</td>
                  <td data-label="Decision">{titleCase(r.decision)}</td>
                  <td data-label="Status change">{r.new_status ? `${reviewLabel(r.previous_status)} → ${reviewLabel(r.new_status)}` : "—"}</td>
                  <td data-label="Reason" style={{ whiteSpace: "pre-wrap" }}>{r.notes ?? "—"}</td></tr>
              ))}</tbody></table></div>
          )}
        </div></section>
        <section className="panel"><div className="panel-head"><h2>Analyst notes</h2></div><div className="panel-body">
          {ev.notes.length ? (
            <ul className="plain-list">{ev.notes.map((n) => (
              <li key={n.id} style={{ borderTop: "1px solid var(--border)", padding: "6px 0" }}>
                <div style={{ whiteSpace: "pre-wrap" }}>{n.body}</div>
                {n.url && <div className="faint mono" style={{ fontSize: 11, wordBreak: "break-all" }}>{n.url}</div>}
                <div className="faint" style={{ fontSize: 11 }}>{n.author ?? "analyst"} · {fmtDateTime(n.created_at)}</div>
              </li>
            ))}</ul>
          ) : <div className="faint">No notes recorded.</div>}
        </div></section>
        <p className="faint" style={{ fontSize: 11.5 }}>
          Automated classifications, confidence and attribution are supporting evidence. They do not establish causation and do not replace human
          review. Confidence reflects the available evidence, not the probability of a fire. Generated {fmtDateTime(new Date().toISOString())} from the
          investigation record of {ev.public_id}.
        </p>
      </div>
    </div>
  );
}
