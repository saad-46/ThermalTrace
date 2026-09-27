/** Global dashboard filters: time range (24 h / 7 / 30 / 90 days / custom), state, district, facility and classification.
 *  Kept in the URL so a filtered view can be shared; applied server-side (nothing is filtered in the browser). */
import { useQuery } from "@tanstack/react-query";
import { SlidersHorizontal, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { CLASS_META, CLASS_ORDER } from "../lib/taxonomy";

export const RANGES: { key: string; label: string; days: number }[] = [
  { key: "1", label: "24 h", days: 1 }, { key: "7", label: "7 d", days: 7 }, { key: "30", label: "30 d", days: 30 }, { key: "90", label: "90 d", days: 90 },
];

export interface AnalyticsQuery { days?: number; since?: string; until?: string; state?: string; district?: string; facility_id?: string; classification?: string[] }

export function useAnalyticsFilters(defaultDays = 30) {
  const [params, setParams] = useSearchParams();
  const q: AnalyticsQuery = useMemo(() => {
    const since = params.get("since") ?? undefined, until = params.get("until") ?? undefined;
    return {
      days: since ? undefined : Number(params.get("days") ?? defaultDays),
      since, until, state: params.get("state") ?? undefined, district: params.get("district") ?? undefined,
      facility_id: params.get("facility_id") ?? undefined, classification: params.getAll("classification"),
    };
  }, [params, defaultDays]);
  const set = (patch: Partial<AnalyticsQuery>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      next.delete(k);
      if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
      else if (v !== undefined && v !== null && v !== "") next.set(k, String(v));
    }
    if ("days" in patch && patch.days) { next.delete("since"); next.delete("until"); }
    if ("since" in patch && patch.since) next.delete("days");
    if ("state" in patch) next.delete("district");
    setParams(next, { replace: true });
  };
  const describe = () => {
    const range = q.since ? `${fmtDateTime(q.since)} → ${q.until ? fmtDateTime(q.until) : "now"}` : RANGES.find((r) => r.days === q.days)?.label ?? `${q.days} d`;
    return [range, q.state, q.district, q.facility_id ? "one facility" : null, q.classification?.length ? q.classification.map((c) => CLASS_META[c as keyof typeof CLASS_META]?.short ?? c).join(", ") : null]
      .filter(Boolean).join(" · ");
  };
  return { q, set, describe, queryKey: JSON.stringify(q) };
}

export function AnalyticsFilterBar({ f }: { f: ReturnType<typeof useAnalyticsFilters> }) {
  const { q, set } = f;
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState({ since: q.since?.slice(0, 16) ?? "", until: q.until?.slice(0, 16) ?? "" });
  const opts = useQuery({ queryKey: ["filter-options"], staleTime: 600_000, queryFn: () => api<{ states: { state: string; events: number }[] }>("/analytics/filter-options") });
  const districts = useQuery({ queryKey: ["filter-districts", q.state], enabled: !!q.state, staleTime: 600_000,
    queryFn: () => api<{ districts: { district: string; events: number }[] }>("/analytics/filter-options", { query: { state: q.state } }) });
  const active = [q.state, q.district, q.facility_id, ...(q.classification ?? [])].filter(Boolean).length;
  return (
    <div className="afilters" data-tour-id="analytics-filters">
      <div className="row wrap" style={{ gap: 6 }}>
        <div className="seg" role="group" aria-label="Time range">
          {RANGES.map((r) => <button key={r.key} className={!q.since && q.days === r.days ? "on" : ""} onClick={() => set({ days: r.days })}>{r.label}</button>)}
          <button className={q.since ? "on" : ""} onClick={() => setOpen(true)}>Custom</button>
        </div>
        <button className="btn sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}><SlidersHorizontal size={13} /> Filters{active ? ` (${active})` : ""}</button>
        <span className="faint" style={{ fontSize: 12 }} aria-live="polite">Showing: <b>{f.describe()}</b></span>
      </div>
      {open && (
        <div className="afilters-sheet float" role="dialog" aria-label="Filters">
          <div className="row" style={{ justifyContent: "space-between" }}><b>Filters</b><button className="btn ghost sm icon" onClick={() => setOpen(false)} aria-label="Close filters"><X size={14} /></button></div>
          <div className="field"><label>Custom range (UTC)</label>
            <div className="row wrap" style={{ gap: 6 }}>
              <input type="datetime-local" className="input" aria-label="From" value={custom.since} onChange={(e) => setCustom({ ...custom, since: e.target.value })} />
              <input type="datetime-local" className="input" aria-label="To" value={custom.until} onChange={(e) => setCustom({ ...custom, until: e.target.value })} />
              <button className="btn sm" disabled={!custom.since} onClick={() => set({ since: `${custom.since}:00Z`, until: custom.until ? `${custom.until}:00Z` : undefined })}>Apply range</button>
            </div></div>
          <div className="row wrap" style={{ gap: 8 }}>
            <div className="field"><label htmlFor="af-state">State</label>
              <select id="af-state" className="select" value={q.state ?? ""} onChange={(e) => set({ state: e.target.value || undefined })}>
                <option value="">All of India</option>{opts.data?.states.map((s) => <option key={s.state} value={s.state}>{s.state} ({s.events.toLocaleString()})</option>)}
              </select></div>
            <div className="field"><label htmlFor="af-district">District</label>
              <select id="af-district" className="select" value={q.district ?? ""} disabled={!q.state} onChange={(e) => set({ district: e.target.value || undefined })}>
                <option value="">{q.state ? "All districts" : "Choose a state first"}</option>
                {districts.data?.districts.map((d) => <option key={d.district} value={d.district}>{d.district} ({d.events})</option>)}
              </select>
              <div className="help faint" style={{ fontSize: 11 }}>Districts are known only for geocoded events.</div></div>
          </div>
          <div className="field"><label>Classification</label><div className="chips">
            {CLASS_ORDER.map((c) => { const on = q.classification?.includes(c); return (
              <button key={c} type="button" className={`chip ${on ? "on" : ""}`} aria-pressed={on}
                onClick={() => set({ classification: on ? q.classification!.filter((x) => x !== c) : [...(q.classification ?? []), c] })}>
                <i className="swatch" style={{ background: CLASS_META[c].color }} />{CLASS_META[c].short}</button>); })}
          </div></div>
          {q.facility_id && <div className="row" style={{ gap: 6 }}><span className="chip on">Facility filter active</span><button className="btn ghost sm" onClick={() => set({ facility_id: undefined })}>Clear facility</button></div>}
          <div className="row" style={{ gap: 6 }}>
            <button className="btn ghost sm" onClick={() => set({ state: undefined, district: undefined, facility_id: undefined, classification: [] })}>Reset filters</button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Query params for the API (arrays repeat). */
export function apiQuery(q: AnalyticsQuery): Record<string, string | number | string[] | undefined> {
  return { days: q.days, since: q.since, until: q.until, state: q.state, district: q.district, facility_id: q.facility_id,
    classification: q.classification?.length ? q.classification : undefined };
}
