import { useQuery } from "@tanstack/react-query";
import { Async, Empty } from "../components/ui";
import { api, post } from "../lib/api";
import { relTime, titleCase } from "../lib/format";
import { useSession } from "../lib/session";
import { errText, useToast } from "../components/ui";

interface Sys {
  database: { latency_ms: number; size: string; postgis: string; tables: { table: string; rows: number }[] };
  workers: { worker_id: string; last_seen_at: string; started_at: string; jobs_done: number; is_scheduler: boolean }[];
  queue: { status: string; n: number }[];
  recent_failures: { id: string; kind: string; finished_at: string; error: string }[];
  configuration: Record<string, { configured?: boolean; note?: string | null }>;
}
interface Models { models: { id: string; kind: string; description: string; label_provenance: string; is_active: boolean; metrics: Record<string, unknown>; training_summary: Record<string, unknown>; created_at: string; current_classifications: number }[]; features: { name: string; origin: string; description: string }[] }
interface Audit { id: number; occurred_at: string; email: string | null; action: string; entity_type: string | null; entity_id: string | null; ip: string | null }

export default function SystemHealth() {
  const { can } = useSession();
  const toast = useToast();
  const sys = useQuery({ queryKey: ["admin-system"], queryFn: () => api<Sys>("/admin/system"), refetchInterval: 15_000, enabled: can("admin") });
  const models = useQuery({ queryKey: ["models"], queryFn: () => api<Models>("/models") });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api<Audit[]>("/admin/audit", { query: { limit: 50 } }), enabled: can("admin") });
  if (!can("admin")) return <div className="page"><Empty title="Administrators only" /></div>;
  const train = async () => {
    try { await post("/ingestion/trigger", { kind: "train_model", payload: {} }); toast("Training queued — the model card appears here when done"); } catch (e) { toast(errText(e), "error"); }
  };
  const activate = async (id: string) => {
    try { await post(`/models/${id}/activate`); toast(`${id} activated; events are being re-analysed`); models.refetch(); } catch (e) { toast(errText(e), "error"); }
  };
  return (
    <div className="page">
      <div className="page-head"><div><h1>System health</h1><div className="sub">Workers, queue, database, model versions and audit trail. Credentials are never displayed.</div></div></div>
      <Async q={sys}>{(s) => (
        <div className="stack" style={{ gap: 12 }}>
          <div className="metrics">
            <div className="metric"><div className="label">Database latency</div><div className="value">{s.database.latency_ms} ms</div><div className="hint">{s.database.size} · PostGIS {s.database.postgis}</div></div>
            <div className="metric"><div className="label">Workers online</div><div className="value">{s.workers.filter((w) => Date.now() - new Date(w.last_seen_at).getTime() < 180_000).length}</div><div className="hint">of {s.workers.length} registered</div></div>
            {s.queue.map((q) => <div key={q.status} className="metric"><div className="label">Jobs {q.status}</div><div className="value">{q.n}</div></div>)}
          </div>
          <div className="grid cols-2">
            <section className="panel"><div className="panel-head"><h2>Workers</h2></div>
              <table className="table"><thead><tr><th scope="col">Worker</th><th scope="col">Last heartbeat</th><th scope="col" className="right">Jobs</th></tr></thead>
                <tbody>{s.workers.map((w) => <tr key={w.worker_id}><td className="mono" style={{ fontSize: 11.5 }}>{w.worker_id}{w.is_scheduler && <span className="pill" style={{ marginLeft: 6 }}>scheduler</span>}</td><td className="num">{relTime(w.last_seen_at)}</td><td className="right num">{w.jobs_done}</td></tr>)}</tbody></table></section>
            <section className="panel"><div className="panel-head"><h2>Integration configuration</h2></div><div className="panel-body stack" style={{ gap: 5 }}>
              {Object.entries(s.configuration).map(([k, v]) => (
                <div key={k} className="row" style={{ alignItems: "flex-start" }}><i className={`dot ${v.configured ? "ok" : ""}`} style={{ marginTop: 5 }} />
                  <div><b>{titleCase(k)}</b> <span className="faint">{v.configured ? "configured" : "not configured"}</span>{v.note && <div className="faint" style={{ fontSize: 11.5 }}>{v.note}</div>}</div></div>
              ))}</div></section>
          </div>
          <section className="panel"><div className="panel-head"><h2>Recent job failures</h2></div>
            {s.recent_failures.length ? <table className="table"><tbody>{s.recent_failures.map((f) => <tr key={f.id}><td>{f.kind}</td><td className="num">{relTime(f.finished_at)}</td><td className="mono faint" style={{ fontSize: 11 }}>{f.error}</td></tr>)}</tbody></table> : <Empty title="No failed jobs" />}</section>
        </div>
      )}</Async>
      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><h2>Model versions</h2><div className="right"><button className="btn sm" onClick={train}>Train LightGBM on current labels</button></div></div>
        <Async q={models}>{(m) => (
          <div>{m.models.map((v) => (
            <div key={v.id} className="section">
              <div className="row"><b className="mono">{v.id}</b><span className="pill">{v.kind}</span>{v.is_active && <span className="pill live">active</span>}
                <span className="faint">{v.current_classifications} current classifications · {relTime(v.created_at)}</span><span style={{ flex: 1 }} />
                {v.kind === "lightgbm" && !v.is_active && <button className="btn sm" onClick={() => activate(v.id)}>Activate</button>}</div>
              <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>{v.description}</div>
              <div style={{ fontSize: 12.5 }}><b>Labels:</b> {v.label_provenance}</div>
              {v.metrics && "macro_f1_holdout" in v.metrics && <div style={{ fontSize: 12.5 }}><b>Hold-out macro-F1:</b> {String(v.metrics.macro_f1_holdout ?? "n/a")} <span className="faint">— {String(v.metrics.caveat ?? "")}</span></div>}
            </div>
          ))}
          <details className="section"><summary style={{ cursor: "pointer" }}>Feature pipeline ({m.features.length} features)</summary>
            <table className="table" style={{ marginTop: 8 }}><thead><tr><th scope="col">Feature</th><th scope="col">Origin</th><th scope="col">Description</th></tr></thead>
              <tbody>{m.features.map((f) => <tr key={f.name}><td className="mono">{f.name}</td><td>{f.origin}</td><td className="muted">{f.description}</td></tr>)}</tbody></table></details></div>
        )}</Async>
      </section>
      <section className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><h2>Audit log</h2></div>
        <Async q={audit} empty={(d) => (d.length ? null : <Empty title="No audit entries" />)}>{(d) => (
          <div className="table-wrap" style={{ maxHeight: 360 }}><table className="table"><thead><tr><th scope="col">When</th><th scope="col">User</th><th scope="col">Action</th><th scope="col">Entity</th><th scope="col">IP</th></tr></thead>
            <tbody>{d.map((a) => <tr key={a.id}><td className="num">{relTime(a.occurred_at)}</td><td>{a.email ?? "—"}</td><td className="mono" style={{ fontSize: 11.5 }}>{a.action}</td><td className="faint mono" style={{ fontSize: 11 }}>{a.entity_type} {a.entity_id?.slice(0, 8)}</td><td className="faint">{a.ip}</td></tr>)}</tbody></table></div>
        )}</Async>
      </section>
    </div>
  );
}
