import { useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useState } from "react";
import { ExtLink } from "../components/evidence";
import { Async, Empty, errText, useToast } from "../components/ui";
import { api, post } from "../lib/api";
import { fmtDate, fmtDateTime, fmtNum, relTime, titleCase } from "../lib/format";
import { useJobs, useSources } from "../lib/hooks";
import { useSession } from "../lib/session";
import { SOURCE_NAMES } from "../lib/taxonomy";

interface FacilityIndex {
  coverage: { total: number; fresh: number; failed: number; events: number; events_covered: number; last_synced: string | null };
  fresh_days: number;
  tiles: { tile_key: string; status: string; event_count: number; features_found: number | null; facilities_new: number | null; last_synced_at: string | null; error: string | null }[];
}
interface Run { id: string; source_id: string; dataset: string | null; mode: string; status: string; started_at: string; duration_ms: number | null; records_fetched: number; records_inserted: number; records_duplicate: number; records_rejected: number; error_detail: string | null }

const TRIGGERS: [string, string, Record<string, unknown>][] = [
  ["firms_poll", "Poll FIRMS (24 h, all sensors)", { window: "24h" }],
  ["process_events", "Cluster & classify new detections", {}],
  ["enrich_batch", "Enrich next 40 events", { limit: 40 }],
  ["facility_sync", "Sync next 4 facility tiles (OSM)", { limit: 4 }],
  ["import_registry", "Import WRI power plant registry", { source: "wri_gppd" }],
];

export default function DataSources() {
  const { can } = useSession();
  const toast = useToast();
  const sources = useSources();
  const jobs = useJobs();
  const [runSource, setRunSource] = useState<string>("");
  const index = useQuery({ queryKey: ["facility-index"], queryFn: () => api<FacilityIndex>("/sources/facility-index"), refetchInterval: 30_000 });
  const runs = useQuery({ queryKey: ["runs", runSource], queryFn: () => api<{ items: Run[] }>("/ingestion/runs", { query: { source: runSource || undefined, limit: 40 } }), refetchInterval: 15_000 });
  const trigger = async (kind: string, payload: Record<string, unknown>) => {
    try { await post("/ingestion/trigger", { kind, payload }); toast("Job queued"); jobs.refetch(); } catch (e) { toast(errText(e), "error"); }
  };
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Data sources</h1><div className="sub">Every provider, its health and freshness. Failures surface here — they are never masked with substitute data.</div></div>
      </div>
      <section className="panel" style={{ marginBottom: 12 }} data-tour-id="sources-table">
        <Async q={sources}>{(d) => (
          <div className="table-wrap"><table className="table">
            <thead><tr><th scope="col">Source</th><th scope="col">Status</th><th scope="col">Last success</th><th scope="col">Latest record</th><th scope="col" className="right">Records</th><th scope="col" className="right">Latency</th><th scope="col" className="right">Error rate</th><th scope="col">Dataset / cadence</th></tr></thead>
            <tbody>{d.map((s) => (
              <tr key={s.id}>
                <td><div style={{ fontWeight: 500 }}><ExtLink href={s.homepage.startsWith("http") ? s.homepage : "#"}>{SOURCE_NAMES[s.id] ?? s.name}</ExtLink></div>
                  <div className="faint" style={{ fontSize: 11.5 }}>{s.kind} · {s.access.replace("_", " ")} · {s.license}</div>
                  {s.configuration?.note && <div className="faint" style={{ fontSize: 11.5 }}>{s.configuration.note}</div>}</td>
                <td><span className="row"><i className={`dot ${s.status === "healthy" || s.status === "enabled" ? "ok" : s.status === "degraded" ? "warn" : s.status === "down" ? "bad" : ""}`} />{titleCase(s.status)}</span>
                  {s.last_error && s.status !== "healthy" && <div className="faint" style={{ fontSize: 11, maxWidth: 220 }} title={s.last_error}>{s.last_error.slice(0, 90)}</div>}</td>
                <td className="num">{relTime(s.last_success_at)}</td>
                <td className="num">{s.last_record_at ? fmtDateTime(s.last_record_at) : "—"}</td>
                <td className="right num">{s.records_total.toLocaleString()}</td>
                <td className="right num">{s.latency_ms_ewma ? `${fmtNum(s.latency_ms_ewma, 0)} ms` : "—"}</td>
                <td className="right num">{s.error_rate == null ? "—" : `${(s.error_rate * 100).toFixed(1)}%`}</td>
                <td style={{ fontSize: 12 }}>{s.dataset_version ? <>{s.dataset_version}{s.dataset_published_at ? ` (published ${fmtDate(s.dataset_published_at)})` : ""}<br /></> : null}<span className="faint">{s.cadence}</span></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}</Async>
      </section>
      <section className="panel" style={{ marginBottom: 12 }} data-tour-id="facility-index">
        <div className="panel-head"><h2>Local facility index</h2>
          <span className="right faint">OSM facilities synced by 1° tile (busiest first) so enrichment does not query Overpass per event</span></div>
        <Async q={index} empty={(d) => (d.coverage.total ? null : <Empty title="No tiles registered yet">Tiles are registered when the first sync job runs.</Empty>)}>{(d) => (
          <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1.6fr)" }}>
            <div className="metrics" style={{ border: "none", alignContent: "start" }}>
              <div className="metric"><div className="label">Tiles fresh</div><div className="value">{d.coverage.fresh} / {d.coverage.total}</div><div className="hint">refreshed every {d.fresh_days} days</div></div>
              <div className="metric"><div className="label">Events covered</div><div className="value">{d.coverage.events ? Math.round((d.coverage.events_covered / d.coverage.events) * 100) : 0}%</div><div className="hint">{d.coverage.events_covered.toLocaleString()} of {d.coverage.events.toLocaleString()}</div></div>
              <div className="metric"><div className="label">Last tile sync</div><div className="value" style={{ fontSize: 15 }}>{relTime(d.coverage.last_synced)}</div><div className="hint">{d.coverage.failed} failed (retried after 6 h)</div></div>
            </div>
            <div className="table-wrap" style={{ maxHeight: 220 }}><table className="table">
              <thead><tr><th scope="col">Tile (SW corner)</th><th scope="col">Status</th><th scope="col" className="right">Events</th><th scope="col" className="right">OSM features</th><th scope="col">Synced</th></tr></thead>
              <tbody>{d.tiles.map((t) => (
                <tr key={t.tile_key} title={t.error ?? ""}><td className="mono">{t.tile_key.replace(":", "°N ")}°E</td>
                  <td><span className={`pill ${t.status === "ok" ? "live" : t.status === "failed" ? "rejected" : ""}`}>{t.status}</span></td>
                  <td className="right num">{t.event_count}</td><td className="right num">{t.features_found ?? "—"}</td><td className="num">{relTime(t.last_synced_at)}</td></tr>
              ))}</tbody></table></div>
          </div>
        )}</Async>
      </section>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1.6fr) minmax(0,1fr)" }}>
        <section className="panel" data-tour-id="ingestion-runs">
          <div className="panel-head"><h2>Ingestion runs</h2>
            <select className="select right" aria-label="Filter runs by source" value={runSource} onChange={(e) => setRunSource(e.target.value)}>
              <option value="">All sources</option>{["firms", "osm", "wri_gppd", "gem", "cea", "demo"].map((s) => <option key={s} value={s}>{SOURCE_NAMES[s]}</option>)}
            </select></div>
          <Async q={runs} empty={(d) => (d.items.length ? null : <Empty title="No runs yet" />)}>{(d) => (
            <div className="table-wrap" style={{ maxHeight: 460 }}><table className="table">
              <thead><tr><th scope="col">Started</th><th scope="col">Source / dataset</th><th scope="col">Mode</th><th scope="col">Status</th><th scope="col" className="right">Fetched</th><th scope="col" className="right">New</th><th scope="col" className="right">Dupes</th><th scope="col" className="right">Rejected</th><th scope="col" className="right">Duration</th></tr></thead>
              <tbody>{d.items.map((r) => (
                <tr key={r.id} title={r.error_detail ?? ""}>
                  <td className="num">{relTime(r.started_at)}</td><td>{SOURCE_NAMES[r.source_id] ?? r.source_id}<div className="faint mono" style={{ fontSize: 11 }}>{r.dataset}</div></td>
                  <td><span className={`pill ${r.mode === "live" ? "live" : r.mode === "demo" ? "demo" : ""}`}>{r.mode}</span></td>
                  <td><span className={`pill ${r.status === "success" ? "live" : r.status === "failed" ? "rejected" : r.status === "partial" ? "low" : ""}`}>{r.status}</span>
                    {r.error_detail && <div className="faint" style={{ fontSize: 11, maxWidth: 200 }}>{r.error_detail.slice(0, 80)}</div>}</td>
                  <td className="right num">{r.records_fetched}</td><td className="right num">{r.records_inserted}</td><td className="right num">{r.records_duplicate}</td><td className="right num">{r.records_rejected}</td>
                  <td className="right num">{r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)} s` : "—"}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )}</Async>
        </section>
        <section className="panel">
          <div className="panel-head"><h2>Background jobs</h2></div>
          {can("supervisor") && <div className="section stack" style={{ gap: 6 }}>
            {TRIGGERS.map(([k, label, payload]) => <button key={k} className="btn sm" style={{ justifyContent: "flex-start" }} onClick={() => trigger(k, payload)}><Play size={12} /> {label}</button>)}
          </div>}
          <Async q={jobs} empty={(d) => (d.items.length ? null : <Empty title="No jobs" />)}>{(d) => (
            <div className="table-wrap" style={{ maxHeight: 380 }}><table className="table"><thead><tr><th scope="col">Job</th><th scope="col">Status</th><th scope="col">Created</th></tr></thead>
              <tbody>{d.items.map((j) => (
                <tr key={j.id} title={j.error ?? JSON.stringify(j.result ?? {})}><td>{j.kind}<div className="faint" style={{ fontSize: 11 }}>attempt {j.attempts}/{j.max_attempts}</div></td>
                  <td><span className={`pill ${j.status === "succeeded" ? "live" : j.status === "failed" ? "rejected" : j.status === "running" ? "high" : ""}`}>{j.status}</span></td>
                  <td className="num">{relTime(j.created_at)}</td></tr>
              ))}</tbody></table></div>
          )}</Async>
        </section>
      </div>
    </div>
  );
}
