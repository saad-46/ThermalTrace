import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AnalyticsFilterBar, apiQuery, useAnalyticsFilters } from "../components/analyticsFilters";
import { StackedBars } from "../components/charts";
import { EventRowMini } from "../components/evidence";
import { Async, ClassLabel, Empty, StatePill } from "../components/ui";
import { api } from "../lib/api";
import { coordsLabel, fmtNum, locationLabel, relTime, sharePct } from "../lib/format";
import { useAlerts, useEvents, useSources } from "../lib/hooks";
import { CLASS_META, FACILITY_LABELS, SOURCE_NAMES } from "../lib/taxonomy";
import type { AnalyticsOverview, EventSummary, Recurring } from "../lib/types";

const pct = (n: number, d: number) => (d ? sharePct(n / d) : "—");

export default function Overview() {
  const f = useAnalyticsFilters(7);
  const query = apiQuery(f.q);
  const overview = useQuery({ queryKey: ["analytics-overview", f.queryKey], queryFn: () => api<AnalyticsOverview>("/analytics/overview", { query }) });
  const series = useQuery({ queryKey: ["analytics-series", f.queryKey], queryFn: () => api<{ bucket: string; rows: { bucket: string; classification: string; events: number; detections: number }[] }>("/analytics/series", { query }) });
  const recurringDays = Math.min(Math.max(f.q.days ?? 7, 7), 90);
  const recurring = useQuery({ queryKey: ["recurring", recurringDays], queryFn: () => api<Recurring>("/analytics/recurring", { query: { days: recurringDays, min_events: 3 } }) });
  const persistent = useQuery({ queryKey: ["persistent-sources", 8], queryFn: () => api<EventSummary[]>("/analytics/persistent-sources", { query: { limit: 8 } }) });
  const review = useEvents({ confidence_state: ["INSUFFICIENT_EVIDENCE"], review_status: ["unreviewed"], min_observations: 3 }, "observations", 8, 0);
  const alerts = useAlerts("new");
  const sources = useSources();

  const buckets = (() => {
    const m = new Map<string, Record<string, number>>();
    for (const r of series.data?.rows ?? []) {
      const k = r.bucket.slice(0, 10);
      m.set(k, { ...(m.get(k) ?? {}), [r.classification]: (m.get(k)?.[r.classification] ?? 0) + r.events });
    }
    return [...m.entries()].map(([key, values]) => ({ key: key.slice(5), values }));
  })();

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Overview</h1><div className="sub">Counts are FIRMS-derived events in the selected range, not verified incidents.</div></div>
        <div className="actions"><Link className="btn primary" to={`/map${f.q.days ? `?days=${f.q.days}` : ""}`}>Open live map</Link></div>
      </div>
      <AnalyticsFilterBar f={f} />
      <Async q={overview} lines={2}>{(o) => {
        const t = o.totals, c = o.evidence_coverage;
        return (
          <div className="metrics" style={{ marginBottom: 12 }} data-tour-id="overview-metrics">
            <div className="metric"><div className="label">Thermal events</div><div className="value">{t.events.toLocaleString()}</div><div className="hint">{t.detections.toLocaleString()} detections · {t.active.toLocaleString()} active</div></div>
            <div className="metric"><div className="label">Active investigations</div><div className="value">{t.active_investigations.toLocaleString()}</div><div className="hint">under review or escalated</div></div>
            <div className="metric"><div className="label">Needs review</div><div className="value">{t.needs_review.toLocaleString()}</div><div className="hint">insufficient evidence, unreviewed</div></div>
            <div className="metric"><div className="label">Confirmed</div><div className="value">{t.confirmed.toLocaleString()}</div><div className="hint">through imagery or analyst review · {t.rejected} rejected · {t.reviewed} reviewed</div></div>
            <div className="metric"><div className="label">High-priority queue</div><div className="value">{t.high_priority_queue.toLocaleString()}</div><div className="hint">triage priority ≥ 70, open (not a risk score)</div></div>
            <div className="metric"><div className="label">Recurring activity</div><div className="value">{o.recurring_facilities.toLocaleString()}</div><div className="hint">facilities with ≥ 3 events within 2 km</div></div>
            <div className="metric" title={c.note}><div className="label">Evidence coverage</div><div className="value">{c.mean_stages != null ? `${fmtNum(c.mean_stages, 1)} / ${c.stages_total}` : "—"}</div>
              <div className="hint">mean stages · weather {pct(c.weather, c.events)} · satellite scenes {pct(c.satellite, c.events)}</div></div>
            <div className="metric"><div className="label">Processing</div><div className="value" style={{ fontSize: 16 }}>{o.processing.running} running</div>
              <div className="hint">{o.processing.queued} queued{o.processing.last_failure ? ` · last job failure ${relTime(o.processing.last_failure)}` : ""}</div></div>
          </div>
        );
      }}</Async>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.6fr) minmax(0, 1fr)" }}>
        <div className="stack" style={{ gap: 12 }}>
          <section className="panel" data-tour-id="overview-trends">
            <div className="panel-head"><h2>Events by classification</h2><span className="right faint">per {series.data?.bucket ?? "day"}</span></div>
            <div className="panel-body">
              <Async q={series} empty={() => (buckets.length ? null : <Empty title="No activity is available for this period" />)}>
                {() => <StackedBars buckets={buckets} series={Object.keys(CLASS_META).concat("unclassified")} colors={{ ...Object.fromEntries(Object.entries(CLASS_META).map(([k, v]) => [k, v.color])), unclassified: "#ced4da" }} />}
              </Async>
            </div>
          </section>
          <section className="panel" data-tour-id="overview-recurring">
            <div className="panel-head"><h2>Recurring activity</h2><span className="right faint">≥ 3 events in {recurringDays} days · observed activity, not risk</span></div>
            <Async q={recurring} empty={(d) => (d.facilities.length || d.places.length ? null : <div className="panel-body"><Empty title="No recurring activity in this period" /></div>)}>{(d) => (
              <div className="table-wrap"><table className="table cards-on-mobile"><thead><tr><th scope="col">Facility or place</th><th scope="col">Type</th><th scope="col" className="right">This period</th><th scope="col" className="right">Previous</th><th scope="col">Last activity</th></tr></thead>
                <tbody>
                  {d.facilities.slice(0, 8).map((r) => (
                    <tr key={r.id}><td data-label="Facility"><Link to={`/facilities/${r.id}`}>{r.name ?? "Unnamed facility"}</Link></td><td data-label="Type">{FACILITY_LABELS[r.facility_type] ?? r.facility_type}</td>
                      <td data-label="This period" className="right num">{r.current}</td><td data-label="Previous" className="right num">{r.previous}</td><td data-label="Last" className="num">{relTime(r.last_activity)}</td></tr>
                  ))}
                  {d.places.slice(0, 5).map((r) => (
                    <tr key={`${r.latitude},${r.longitude}`}><td data-label="Place"><Link to={`/map?lat=${r.latitude}&lon=${r.longitude}&z=11`}>{[r.place, r.state].filter(Boolean).join(", ") || `${r.latitude.toFixed(2)}, ${r.longitude.toFixed(2)}`}</Link></td>
                      <td data-label="Type">place (no facility within 2 km)</td><td data-label="This period" className="right num">{r.current}</td><td data-label="Previous" className="right num">{r.previous}</td><td className="faint">—</td></tr>
                  ))}
                </tbody></table></div>
            )}</Async>
          </section>
          <section className="panel">
            <div className="panel-head"><h2>Persistent thermal sources</h2><span className="right"><Link to="/analytics">All</Link></span></div>
            <div className="panel-body">
              <Async q={persistent} empty={(d) => (d.length ? null : <Empty title="None yet" />)}>{(d) => (
                <table className="table cards-on-mobile"><thead><tr><th scope="col">Event</th><th scope="col">Where</th><th scope="col">Classification</th><th scope="col">Status</th><th scope="col" className="right">Active days</th></tr></thead>
                  <tbody>{d.map((e) => (
                    <tr key={e.id}><td data-label="Event"><Link className="mono" to={`/events/${e.public_id}`}>{e.public_id}</Link></td>
                      <td data-label="Where">{locationLabel(e) || "—"} <span className="faint mono" style={{ fontSize: 11 }}>{coordsLabel(e)}</span></td>
                      <td data-label="Class"><ClassLabel cls={e.classification} short /></td><td data-label="Status"><StatePill state={e.display_state} /></td><td data-label="Active days" className="right num">{e.days_active}</td></tr>
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
