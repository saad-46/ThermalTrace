import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import { Component, createContext, useCallback, useContext, useState, type ErrorInfo, type ReactNode } from "react";
import { ApiError } from "../lib/api";
import { relTime } from "../lib/format";
import { useStatus } from "../lib/hooks";
import { CLASS_META, PERSISTENCE_META, STATE_META, confidenceNote } from "../lib/taxonomy";
import type { DataMode, DisplayState, PersistenceClass, SourceClass } from "../lib/types";

export function StatePill({ state, title }: { state: DisplayState | null | undefined; title?: string }) {
  const meta = STATE_META[state ?? "INSUFFICIENT_EVIDENCE"];
  return (
    <span className={`pill ${meta.tone}`} title={title ?? `${meta.hint}. ${confidenceNote(state)}`}>
      {meta.label}
    </span>
  );
}

export function ClassLabel({ cls, short }: { cls: SourceClass | null | undefined; short?: boolean }) {
  if (!cls) return <span className="faint">Unprocessed</span>;
  const m = CLASS_META[cls];
  return (
    <span className="cls" title={m.hint}>
      <i style={{ background: m.color }} aria-hidden />
      {short ? m.short : m.label}
    </span>
  );
}

export function PersistencePill({ p }: { p: PersistenceClass | null | undefined }) {
  if (!p) return <span className="faint">—</span>;
  return (
    <span className={`pill ${p === "persistent" ? "thermal" : ""}`} title={PERSISTENCE_META[p].hint}>
      {PERSISTENCE_META[p].label}
    </span>
  );
}

export function ModePill({ mode }: { mode: DataMode }) {
  const label = mode === "live" ? "Live" : mode === "demo" ? "Demo data" : "Historical";
  return <span className={`pill ${mode}`}>{label}</span>;
}

export function Meter({ value, tone, label }: { value: number; tone?: string; label?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className={`meter ${tone ?? ""}`} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} aria-label={label}>
      <i style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Skeleton({ lines = 3, height = 12 }: { lines?: number; height?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skel" style={{ height, width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="empty">
      {icon ?? <Inbox size={20} strokeWidth={1.5} />}
      <div className="title">{title}</div>
      {children && <div>{children}</div>}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error instanceof ApiError ? error : null;
  const title = e?.isUnavailable ? "Data source unavailable" : e?.status === 403 ? "Not permitted" : "Could not load data";
  return (
    <div className="error-box" role="alert">
      <AlertTriangle size={20} strokeWidth={1.5} />
      <div className="title">{title}</div>
      <div>{e?.message ?? String(error)}</div>
      {e?.requestId && <div className="faint mono">request {e.requestId}</div>}
      {retry && (
        <button className="btn sm" onClick={retry}>
          <RefreshCw size={13} /> Retry
        </button>
      )}
    </div>
  );
}

/** Wraps a react-query result into loading / error / empty / content states. */
export function Async<T>({ q, empty, children, lines }: {
  q: { data: T | undefined; isLoading: boolean; error: unknown; refetch: () => unknown };
  empty?: (d: T) => ReactNode | null;
  children: (d: T) => ReactNode;
  lines?: number;
}) {
  if (q.isLoading) return <div className="panel-body"><Skeleton lines={lines ?? 4} /></div>;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  if (q.data === undefined) return null;
  const e = empty?.(q.data);
  if (e) return <>{e}</>;
  return <>{children(q.data)}</>;
}

// ---------------------------------------------------------------- toasts
interface Toast { id: number; text: string; kind: "info" | "error"; }
const ToastCtx = createContext<(text: string, kind?: "info" | "error") => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: "info" | "error" = "info") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, text, kind }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);
export function errText(e: unknown): string {
  return e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Something went wrong";
}

// ---------------------------------------------------------------- freshness
function ageTone(iso: string | null | undefined, okH: number, warnH: number) {
  if (!iso) return "";
  const h = (Date.now() - new Date(iso).getTime()) / 3_600_000;
  return h <= okH ? "ok" : h <= warnH ? "warn" : "bad";
}

export function Freshness({ compact }: { compact?: boolean }) {
  const s = useStatus();
  if (!s.data) return <div className="fresh">{s.error ? <span className="item"><i className="dot bad" /> Status unavailable</span> : <span className="spinner" />}</div>;
  const d = s.data;
  const live = !!d.firms_sync && ageTone(d.firms_sync, 1.5, 6) === "ok";
  return (
    <div className="fresh" aria-label="Data freshness">
      <span className="item" title="Last successful NASA FIRMS sync">
        <i className={`dot ${live ? "live" : ageTone(d.firms_sync, 1.5, 6)}`} />
        {live ? <b style={{ fontWeight: 600 }}>LIVE</b> : "FIRMS"} · synced {relTime(d.firms_sync)}
      </span>
      {!compact && (
        <>
          <span className="item" title="Most recent satellite acquisition time among FIRMS detections">
            Latest detection {relTime(d.latest_detection)}
          </span>
          <span className="item" title="Last successful OSM / facility registry update">
            <i className={`dot ${ageTone(d.osm_sync ?? d.registry_sync, 24, 24 * 7)}`} /> Facilities {relTime(d.osm_sync ?? d.registry_sync)}
          </span>
          <span className="item" title="Most recent Sentinel-2 catalogue lookup">
            <i className={`dot ${ageTone(d.satellite_update, 24, 72)}`} /> Imagery {relTime(d.satellite_update)}
          </span>
          {!d.worker_online && <span className="item" style={{ color: "var(--warn)" }}><i className="dot warn" /> Background worker offline</span>}
        </>
      )}
    </div>
  );
}

export function DemoBanner() {
  const s = useStatus();
  if (!s.data || (!s.data.demo_mode && !s.data.demo_detections)) return null;
  return (
    <div className="banner demo" role="note">
      DEMO MODE — {s.data.demo_detections.toLocaleString()} synthetic detections are loaded. Demo records are labelled and are not observational data.
    </div>
  );
}

// ---------------------------------------------------------------- error boundary
export class Boundary extends Component<{ children: ReactNode; label: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn(`[${this.props.label}]`, error.message, info.componentStack?.split("\n")[1]);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="error-box" role="alert">
        <AlertTriangle size={20} strokeWidth={1.5} />
        <div className="title">{this.props.label} could not be displayed</div>
        <div>{/webgl/i.test(this.state.error.message) ? "WebGL is unavailable in this browser." : this.state.error.message}</div>
        <button className="btn sm" onClick={() => this.setState({ error: null })}><RefreshCw size={13} /> Retry</button>
      </div>
    );
  }
}
