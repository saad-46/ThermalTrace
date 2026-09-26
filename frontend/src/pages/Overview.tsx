import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { StackedBars } from "../components/charts";
import { EventRowMini } from "../components/evidence";
import { Async, ClassLabel, Empty, StatePill } from "../components/ui";
import { api } from "../lib/api";
import { coordsLabel, locationLabel, relTime } from "../lib/format";
import { useAlerts, useEvents, useSources } from "../lib/hooks";
import { CLASS_META, SOURCE_NAMES } from "../lib/taxonomy";
import type { EventSummary } from "../lib/types";

interface Summary {
  totals: { events: number; active: number; persistent: number; needs_review: number; confirmed: number; rejected: number; detections: number };
  by_classification: { k: string; n: number }[];
}

export default function Overview() {
  const summary = useQuery({ queryKey: ["summary", 7], queryFn: () => api<Summary>("/analytics/summary", { query: { days: 7 } }) });
  const trends = useQuery({ queryKey: ["trends", 14], queryFn: () => api<{ rows: { bucket: string; classification: string; detections: number }[] }>("/analytics/trends", { query: { days: 14 } }) });
  const persistent = useQuery({ queryKey: ["persistent-sources", 8], queryFn: () => api<EventSummary[]>("/analytics/persistent-sources", { query: { limit: 8 } }) });
  const review = useEvents({ confidence_state: ["INSUFFICIENT_EVIDENCE"], review_status: ["unreviewed"], min_observations: 3 }, "observations", 8, 0);
  const alerts = useAlerts("new");
  const sources = useSources();

  const buckets = (() => {
    const m = new Map<string, Record<string, number>>();
    for (const r of trends.data?.rows ?? []) {
      const k = r.bucket.slice(5, 10);
      m.set(k, { ...(m.get(k) ?? {}), [r.classification]: (m.get(k)?.[r.classification] ?? 0) + r.detections });
    }
    return [...m.entries()].map(([key, values]) => ({ key, values }));
  })();

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Overview</h1><div className="sub">Last 7 days across the monitored region. Counts are FIRMS-derived events, not verified incidents.</div></div>
        <div className="actions"><Link className="btn primary" to="/map">Open live map</Link></div>
      </div>
      <Async q={summary} lines={2}>{(s) => (
        <div className="metrics" style={{ marginBottom: 12 }} data-tour-id="overview-metrics">
          <div className="metric"><div className="label">Events (7 d)</div><div className="value">{s.totals.events.toLocaleString()}</div><div className="hint">{s.totals.detections.toLocaleString()} detections</div></div>
          <div className="metric"><div className="label">Active now</div><div className="value">{s.totals.active.toLocaleString()}</div><div className="hint">seen within 5 days</div></div>
          <div className="metric"><div className="label">Persistent</div><div className="value">{s.totals.persistent}</div><div className="hint">sustained sources</div></div>
          <div className="metric"><div className="label">Needs review</div><div className="value">{s.totals.needs_review.toLocaleString()}</div><div className="hint">insufficient evidence, unreviewed</div></div>
          <div className="metric"><div className="label">Analyst decisions</div><div className="value">{s.totals.confirmed + s.totals.rejected}</div><div className="hint">{s.totals.confirmed} confirmed · {s.totals.rejected} rejected</div></div>
        </div>
      )}</Async>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.6fr) minmax(0, 1fr)" }}>
        <div className="stack" style={{ gap: 12 }}>
          <section className="panel" data-tour-id="overview-trends">
            <div className="panel-head"><h2>Detections per day by classification</h2><span className="right faint">14 days</span></div>
            <div className="panel-body">
              <Async q={trends} empty={() => (buckets.length ? null : <Empty title="No detections in range" />)}>
                {() => <StackedBars buckets={buckets} series={Object.keys(CLASS_META).concat("unclassified")} colors={{ ...Object.fromEntries(Object.entries(CLASS_META).map(([k, v]) => [k, v.color])), unclassified: "#ced4da" }} />}
              </Async>
            </div>
          </section>
          <section className="panel">
            <div className="panel-head"><h2>Persistent thermal sources</h2><span className="right"><Link to="/analytics">All</Link></span></div>
            <div className="panel-body">
              <Async q={persistent} empty={(d) => (d.length ? null : <Empty title="None yet" />)}>{(d) => (
                <table className="table"><thead><tr><th scope="col">Event</th><th scope="col">Where</th><th scope="col">Classification</th><th scope="col">Status</th><th scope="col" className="right">Active days</th></tr></thead>
                  <tbody>{d.map((e) => (
                    <tr key={e.id}><td><Link className="mono" to={`/events/${e.public_id}`}>{e.public_id}</Link></td>
                      <td>{locationLabel(e) || "—"} <span className="faint mono" style={{ fontSize: 11 }}>{coordsLabel(e)}</span></td>
                      <td><ClassLabel cls={e.classification} short /></td><td><StatePill state={e.display_state} /></td><td className="right num">{e.days_active}</td></tr>
                  ))}</tbody></table>
              )}</Async>
            </div>
          </section>
        </div>
        <div className="stack" style={{ gap: 12 }}>
          <section className="panel">
            <div className="panel-head"><h2>Review queue</h2><span className="right"><Link to="/events">Open</Link></span></div>
            <div className="panel-body" style={{ paddingTop: 4 }}>
              <Async q={review} empty={(d) => (d.items.length ? null : <Empty title="Queue is clear" />)}>{(d) => <>{d.items.map((e) => <EventRowMini key={e.id} e={e} />)}</>}</Async>
            </div>
          </section>
          <section className="panel">
            <div className="panel-head"><h2>New alerts</h2><span className="right"><Link to="/alerts">All</Link></span></div>
            <div className="panel-body">
              <Async q={alerts} empty={(d) => (d.items.length ? null : <Empty title="No new alerts">Create alert rules to be notified.</Empty>)}>{(d) => (
                <div className="stack">{d.items.slice(0, 6).map((a) => <Link key={a.id} to={`/events/${a.event_public_id}`} style={{ color: "var(--text)" }}><div style={{ fontWeight: 500 }}>{a.title}</div><div className="faint" style={{ fontSize: 11.5 }}>{a.rule_name} · {relTime(a.triggered_at)}</div></Link>)}</div>
              )}</Async>
            </div>
          </section>
          <section className="panel" data-tour-id="overview-sources">
            <div className="panel-head"><h2>Source health</h2><span className="right"><Link to="/sources">Details</Link></span></div>
            <div className="panel-body">
              <Async q={sources}>{(d) => (
                <div className="stack" style={{ gap: 5 }}>{d.filter((s) => s.id !== "demo").map((s) => (
                  <div key={s.id} className="row" style={{ justifyContent: "space-between" }}>
                    <span className="row"><i className={`dot ${s.status === "healthy" ? "ok" : s.status === "degraded" ? "warn" : s.status === "down" ? "bad" : ""}`} />{SOURCE_NAMES[s.id] ?? s.name}</span>
                    <span className="faint" style={{ fontSize: 12 }}>{s.last_success_at ? relTime(s.last_success_at) : s.status.replace("_", " ")}</span>
                  </div>
                ))}</div>
              )}</Async>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
