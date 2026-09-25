import { SlidersHorizontal, X } from "lucide-react";
import { useState } from "react";
import { sinceFromDays, type EventFilters } from "../lib/hooks";
import { CLASS_META, CLASS_ORDER, FACILITY_LABELS, PERSISTENCE_META, STATE_META } from "../lib/taxonomy";

export interface FilterState {
  days: number | null;
  classification: string[];
  persistence: string[];
  confidence_state: string[];
  sensor: string[];
  facility_type: string[];
  min_frp: number | null;
  min_observations: number | null;
  q: string;
}
export const DEFAULT_FILTERS: FilterState = {
  days: 7, classification: [], persistence: [], confidence_state: [], sensor: [], facility_type: [], min_frp: null, min_observations: null, q: "",
};
const SENSORS = ["Terra", "Aqua", "S-NPP", "NOAA-20", "NOAA-21"];
const FAC_TYPES = ["refinery", "oil_gas", "power_plant_coal", "steel_plant", "cement_plant", "coal_mine", "mine", "factory", "industrial_area"];

export function toQuery(f: FilterState): EventFilters {
  return {
    since: sinceFromDays(f.days),
    classification: f.classification.length ? f.classification : undefined,
    persistence: f.persistence.length ? f.persistence : undefined,
    confidence_state: f.confidence_state.length ? f.confidence_state : undefined,
    sensor: f.sensor.length ? f.sensor : undefined,
    facility_type: f.facility_type.length ? f.facility_type : undefined,
    min_frp: f.min_frp ?? undefined,
    min_observations: f.min_observations ?? undefined,
    q: f.q || undefined,
  };
}

export function activeCount(f: FilterState): number {
  return [f.classification, f.persistence, f.confidence_state, f.sensor, f.facility_type].filter((x) => x.length).length
    + (f.min_frp ? 1 : 0) + (f.min_observations ? 1 : 0) + (f.q ? 1 : 0);
}

function toggle(list: string[], v: string) {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

export function TimeRange({ value, onChange }: { value: number | null; onChange: (d: number | null) => void }) {
  const opts: [number | null, string][] = [[1, "24 h"], [3, "3 d"], [7, "7 d"], [30, "30 d"], [null, "All"]];
  return (
    <div className="seg" role="radiogroup" aria-label="Time range">
      {opts.map(([d, l]) => <button key={l} role="radio" aria-checked={value === d} className={value === d ? "on" : ""} onClick={() => onChange(d)}>{l}</button>)}
    </div>
  );
}

export function FilterPanel({ f, set, onClose }: { f: FilterState; set: (f: FilterState) => void; onClose?: () => void }) {
  return (
    <div className="stack" style={{ gap: 12, padding: 12, maxWidth: 520 }}>
      <div className="row"><h3>Filters</h3><span style={{ flex: 1 }} />
        <button className="btn ghost sm" onClick={() => set({ ...DEFAULT_FILTERS, days: f.days })}>Reset</button>
        {onClose && <button className="btn ghost sm icon" onClick={onClose} aria-label="Close filters"><X size={14} /></button>}
      </div>
      <div className="field"><label>Classification</label><div className="chips">
        {CLASS_ORDER.map((c) => (
          <button key={c} className={`chip ${f.classification.includes(c) ? "on" : ""}`} aria-pressed={f.classification.includes(c)} onClick={() => set({ ...f, classification: toggle(f.classification, c) })}>
            <i className="swatch" style={{ background: CLASS_META[c].color }} />{CLASS_META[c].short}
          </button>
        ))}</div></div>
      <div className="field"><label>Persistence</label><div className="chips">
        {Object.entries(PERSISTENCE_META).map(([k, m]) => (
          <button key={k} className={`chip ${f.persistence.includes(k) ? "on" : ""}`} aria-pressed={f.persistence.includes(k)} onClick={() => set({ ...f, persistence: toggle(f.persistence, k) })}>{m.label}</button>
        ))}</div></div>
      <div className="field"><label>Confidence (system)</label><div className="chips">
        {(["HIGH_CONFIDENCE", "MODERATE_CONFIDENCE", "LOW_CONFIDENCE", "INSUFFICIENT_EVIDENCE"] as const).map((k) => (
          <button key={k} className={`chip ${f.confidence_state.includes(k) ? "on" : ""}`} aria-pressed={f.confidence_state.includes(k)} onClick={() => set({ ...f, confidence_state: toggle(f.confidence_state, k) })}>{STATE_META[k].label}</button>
        ))}</div></div>
      <div className="field"><label>Sensor platform</label><div className="chips">
        {SENSORS.map((s) => <button key={s} className={`chip ${f.sensor.includes(s) ? "on" : ""}`} aria-pressed={f.sensor.includes(s)} onClick={() => set({ ...f, sensor: toggle(f.sensor, s) })}>{s}</button>)}
      </div></div>
      <div className="field"><label>Facility within 5 km</label><div className="chips">
        {FAC_TYPES.map((t) => <button key={t} className={`chip ${f.facility_type.includes(t) ? "on" : ""}`} aria-pressed={f.facility_type.includes(t)} onClick={() => set({ ...f, facility_type: toggle(f.facility_type, t) })}>{FACILITY_LABELS[t]}</button>)}
      </div></div>
      <div className="row wrap">
        <div className="field"><label htmlFor="minfrp">Min. peak FRP (MW)</label>
          <input id="minfrp" className="input" type="number" min={0} style={{ width: 120 }} value={f.min_frp ?? ""} onChange={(e) => set({ ...f, min_frp: e.target.value ? +e.target.value : null })} /></div>
        <div className="field"><label htmlFor="minobs">Min. detections</label>
          <input id="minobs" className="input" type="number" min={1} style={{ width: 120 }} value={f.min_observations ?? ""} onChange={(e) => set({ ...f, min_observations: e.target.value ? +e.target.value : null })} /></div>
      </div>
    </div>
  );
}

export function FilterButton({ f, set }: { f: FilterState; set: (f: FilterState) => void }) {
  const [open, setOpen] = useState(false);
  const n = activeCount(f);
  return (
    <div style={{ position: "relative" }}>
      <button className="btn" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <SlidersHorizontal size={14} /> Filters{n ? <span className="pill thermal" style={{ height: 18 }}>{n}</span> : null}
      </button>
      {open && <div className="float" style={{ position: "absolute", top: "110%", left: 0, zIndex: 40, width: 480 }}><FilterPanel f={f} set={set} onClose={() => setOpen(false)} /></div>}
    </div>
  );
}
