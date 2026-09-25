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

interface Run { id: string; source_id: string; dataset: string | null; mode: string; status: string; started_at: string; duration_ms: number | null; records_fetched: number; records_inserted: number; records_duplicate: number; records_rejected: number; error_detail: string | null }

const TRIGGERS: [string, string, Record<string, unknown>][] = [
  ["firms_poll", "Poll FIRMS (24 h, all sensors)", { window: "24h" }],
  ["process_events", "Cluster & classify new detections", {}],
  ["enrich_batch", "Enrich next 40 events", { limit: 40 }],
  ["import_registry", "Import WRI power plant registry", { source: "wri_gppd" }],
];

export default function DataSources() {
  const { can } = useSession();
  const toast = useToast();
  const sources = useSources();
  const jobs = useJobs();
  const [runSource, setRunSource] = useState<string>("");
  const runs = useQuery({ queryKey: ["runs", runSource], queryFn: () => api<{ items: Run[] }>("/ingestion/runs", { query: { source: runSource || undefined, limit: 40 } }), refetchInterval: 15_000 });
  const trigger = async (kind: string, payload: Record<string, unknown>) => {
    try { await post("/ingestion/trigger", { kind, payload }); toast("Job queued"); jobs.refetch(); } catch (e) { toast(errText(e), "error"); }
  };
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Data sources</h1><div className="sub">Every provider, its health and freshness. Failures surface here — they are never masked with substitute data.</div></div>
      </div>
      <section className="panel" style={{ marginBottom: 12 }}>
        <Async q={sources}>{(d) => (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Source</th><th>Status</th><th>Last success</th><th>Latest record</th><th className="right">Records</th><th className="right">Latency</th><th className="right">Error rate</th><th>Dataset / cadence</th></tr></thead>
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
      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1.6fr) minmax(0,1fr)" }}>
        <section className="panel">
          <div className="panel-head"><h2>Ingestion runs</h2>
            <select className="select right" aria-label="Filter runs by source" value={runSource} onChange={(e) => setRunSource(e.target.value)}>
              <option value="">All sources</option>{["firms", "osm", "wri_gppd", "gem", "cea", "demo"].map((s) => <option key={s} value={s}>{SOURCE_NAMES[s]}</option>)}
            </select></div>
          <Async q={runs} empty={(d) => (d.items.length ? null : <Empty title="No runs yet" />)}>{(d) => (
            <div className="table-wrap" style={{ maxHeight: 460 }}><table className="table">
              <thead><tr><th>Started</th><th>Source / dataset</th><th>Mode</th><th>Status</th><th className="right">Fetched</th><th className="right">New</th><th className="right">Dupes</th><th className="right">Rejected</th><th className="right">Duration</th></tr></thead>
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
            <div className="table-wrap" style={{ maxHeight: 380 }}><table className="table"><thead><tr><th>Job</th><th>Status</th><th>Created</th></tr></thead>
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
