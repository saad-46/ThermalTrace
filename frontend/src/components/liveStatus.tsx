/** System-wide live status: an expandable panel behind the header freshness indicator, and a provider detail drawer.
 *  Every value comes from GET /status/live and /sources/{id}/detail (recorded requests and jobs); nothing is assumed.
 *  A credential-free provider is never shown as inactive for lacking credentials. */
import { useQuery } from "@tanstack/react-query";
import { Activity, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { fmtDateTime, relTime, titleCase } from "../lib/format";
import { SOURCE_NAMES } from "../lib/taxonomy";
import type { LiveSourceStatus, LiveStatus, SourceDetail } from "../lib/types";
import { Skeleton } from "./ui";

const TONE: Record<LiveSourceStatus, string> = { healthy: "ok", configured: "info", optional: "", no_data: "", degraded: "warn", failed: "bad", not_configured: "" };
export const useLiveStatus = (enabled = true) =>
  useQuery({ queryKey: ["live-status"], enabled, refetchInterval: 30_000, queryFn: () => api<LiveStatus>("/status/live") });

export function StatusDot({ s }: { s: LiveSourceStatus }) { return <i className={`dot ${TONE[s]}`} aria-hidden />; }

export function LiveStatusButton() {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const q = useLiveStatus(true);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc); window.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); window.removeEventListener("keydown", onKey); };
  }, [open]);
  const d = q.data;
  const online = d?.worker_online;
  return (
    <div className="live-status" ref={ref} data-tour-id="live-status">
      <button className="btn ghost sm" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="dialog">
        <Activity size={13} /> {d ? <>{online ? "Processing online" : "Processing offline"} · {d.sources_active}/{d.sources_total} sources</> : "Status"}
      </button>
      {open && (
        <div className="live-panel float" role="dialog" aria-label="Live data status">
          {!d ? <Skeleton lines={5} /> : (
            <>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <b><i className={`dot ${online ? "live" : "warn"}`} /> {online ? "Processing online" : "Background worker offline"}</b>
                <span className="faint">{d.sources_active} / {d.sources_total} sources healthy</span>
              </div>
              <dl className="kv compact">
                <dt>FIRMS update</dt><dd>{relTime(d.last_firms_update)}</dd>
                <dt>Weather update</dt><dd>{relTime(d.last_weather_update)}</dd>
                <dt>Satellite search</dt><dd>{relTime(d.last_satellite_search)}</dd>
                <dt>Jobs</dt><dd>{d.jobs.running} running · {d.jobs.queued} queued{d.jobs.failed_24h ? ` · ${d.jobs.failed_24h} failed (24 h)` : ""}</dd>
                {d.jobs.running_jobs.length > 0 && <><dt>Running</dt><dd>{d.jobs.running_jobs.map((j) => `${j.kind.replace(/_/g, " ")} (${relTime(j.started_at)})`).join(", ")}</dd></>}
                <dt>Last failure</dt><dd>{d.last_failed_source ? `${SOURCE_NAMES[d.last_failed_source.id] ?? d.last_failed_source.name}, ${relTime(d.last_failed_source.at)}${d.last_failed_source.category ? ` (${d.last_failed_source.category.replace(/_/g, " ")})` : ""}` : "none recorded"}</dd>
              </dl>
              <ul className="live-sources">
                {d.sources.map((s) => (
                  <li key={s.id}><button className="live-src" onClick={() => setDetail(s.id)}>
                    <StatusDot s={s.status} /><span>{SOURCE_NAMES[s.id] ?? s.name}</span><span className={`live-label ${s.status}`}>{s.label}</span>
                  </button></li>
                ))}
              </ul>
              <div className="faint" style={{ fontSize: 11 }}>Healthy = a recent request succeeded. Configured = credentials present, not recently verified. Optional = only extra features need it.</div>
            </>
          )}
        </div>
      )}
      {detail && <SourceDetailDrawer id={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

export function SourceDetailDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["source-detail", id], queryFn: () => api<SourceDetail>(`/sources/${id}/detail`) });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const s = q.data;
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-label="Data source detail" onClick={(e) => e.stopPropagation()} data-testid="source-detail">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>{s ? SOURCE_NAMES[s.id] ?? s.name : "Data source"}</h2>
          <button className="btn ghost sm icon" onClick={onClose} aria-label="Close"><X size={14} /></button>
        </div>
        {!s ? <Skeleton lines={8} /> : (
          <div className="stack" style={{ gap: 10 }}>
            <div className="row" style={{ gap: 6 }}><StatusDot s={s.status} /><b>{s.label}</b><span className="faint">{s.reason}</span></div>
            <dl className="kv">
              <dt>Purpose</dt><dd>{s.purpose ?? "—"}</dd>
              <dt>Authentication</dt><dd>{s.authentication}</dd>
              <dt>Optional</dt><dd>{s.optional ? `Yes. ${s.optional_detail ?? ""}` : "No"}</dd>
              <dt>Access</dt><dd>{titleCase(s.access)}</dd>
              <dt>Last success</dt><dd>{s.last_success_at ? `${fmtDateTime(s.last_success_at)} (${relTime(s.last_success_at)})` : "never recorded"}</dd>
              <dt>Last failure</dt><dd>{s.last_failure_at ? `${fmtDateTime(s.last_failure_at)} (${relTime(s.last_failure_at)})` : "none recorded"}</dd>
              <dt>Last error category</dt><dd>{s.last_error_category ? s.last_error_category.replace(/_/g, " ") : "—"}</dd>
              <dt>Records retrieved</dt><dd className="num">{s.records_total.toLocaleString()}</dd>
              <dt>Requests</dt><dd className="num">{s.requests_total.toLocaleString()} ({s.requests_failed.toLocaleString()} failed){s.latency_ms != null ? ` · ~${s.latency_ms} ms` : ""}</dd>
              <dt>Rate limit</dt><dd>{s.rate_limit}</dd>
            </dl>
            {s.checks && <div className="faint" style={{ fontSize: 11.5 }}>Capability checks: {Object.entries(s.checks).map(([k, v]) => `${k}: ${(v as { ok?: boolean }).ok ? "ok" : "failed"}`).join(" · ")}</div>}
            <div className="faint" style={{ fontSize: 11.5 }}>Secrets are never shown. Error details stay in the server logs; only the category is displayed.</div>
          </div>
        )}
      </aside>
    </div>
  );
}
