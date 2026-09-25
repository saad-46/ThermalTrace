import { useQuery } from "@tanstack/react-query";
import { Building2, Crosshair, MapPin, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { fmtDistance } from "../lib/format";
import { FACILITY_LABELS } from "../lib/taxonomy";
import type { SearchResults } from "../lib/types";
import { ClassLabel, StatePill } from "./ui";

type Item = { key: string; label: React.ReactNode; to: string };

/** Header search: event ids, places, facilities, classifications, coordinates (server-side). */
export default function GlobalSearch({ compact }: { compact?: boolean }) {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(q.trim()), 200);
    return () => window.clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const res = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api<SearchResults>("/search", { query: { q: debounced } }),
    enabled: debounced.length >= 2,
  });

  const d = res.data;
  const items: Item[] = [];
  if (d?.coordinates) {
    items.push({ key: "coord", to: `/map?lat=${d.coordinates.latitude}&lon=${d.coordinates.longitude}&z=11`,
      label: <><Crosshair size={13} /> Go to {d.coordinates.latitude.toFixed(4)}, {d.coordinates.longitude.toFixed(4)}</> });
  }
  d?.events.forEach((e) => items.push({ key: `e${e.id}`, to: `/events/${e.public_id}`, label: (
    <><span className="mono">{e.public_id}</span> <ClassLabel cls={e.classification} short />
      <span className="faint">{[e.admin_district, e.admin_state].filter(Boolean).join(", ")}{e.distance_m != null ? ` · ${fmtDistance(e.distance_m)}` : ""}</span>
      {e.confidence_state && <span style={{ marginLeft: "auto" }}><StatePill state={e.confidence_state} /></span>}</>) }));
  d?.places.forEach((p) => items.push({ key: `p${p.admin_district}${p.admin_state}`, to: `/map?lat=${p.latitude}&lon=${p.longitude}&z=9`,
    label: <><MapPin size={13} /> {[p.admin_district, p.admin_state].filter(Boolean).join(", ")} <span className="faint">{p.events} event(s)</span></> }));
  d?.facilities.forEach((f) => items.push({ key: `f${f.id}`, to: `/facilities/${f.id}`,
    label: <><Building2 size={13} /> {f.name ?? "Unnamed"} <span className="faint">{FACILITY_LABELS[f.facility_type] ?? f.facility_type}{f.operator ? ` · ${f.operator}` : ""}</span></> }));
  d?.classifications.forEach((c) => items.push({ key: `c${c.key}`, to: `/events?classification=${c.key}`,
    label: <>Events classified as <ClassLabel cls={c.key} /></> }));

  const go = (it: Item) => {
    setOpen(false);
    setQ("");
    input.current?.blur();
    nav(it.to);
  };
  const show = open && debounced.length >= 2;
  return (
    <div className="gsearch" style={{ maxWidth: compact ? "100%" : 440 }}>
      <div className="gsearch-box">
        <Search size={13} className="faint" aria-hidden />
        <input ref={input} value={q} role="combobox" aria-expanded={show} aria-controls="gsearch-list" aria-label="Search events, places, facilities, coordinates"
          placeholder={compact ? "Search" : "Search event ID, district, facility, coordinates…  ( / )"}
          onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0); }}
          onFocus={() => setOpen(true)} onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
            if (e.key === "Enter" && items[active]) go(items[active]);
            if (e.key === "Escape") { setOpen(false); input.current?.blur(); }
          }} />
        {q && <button className="btn ghost sm icon" aria-label="Clear search" onMouseDown={(e) => e.preventDefault()} onClick={() => setQ("")}><X size={12} /></button>}
      </div>
      {show && (
        <div id="gsearch-list" role="listbox" className="float gsearch-list">
          {res.isLoading ? <div className="faint" style={{ padding: 10 }}>Searching…</div>
            : res.error ? <div style={{ padding: 10, color: "var(--bad)" }}>Search unavailable</div>
            : items.length === 0 ? <div className="faint" style={{ padding: 10 }}>No matches for “{debounced}”.</div>
            : items.map((it, i) => (
              <button key={it.key} role="option" aria-selected={i === active} className={`gsearch-item ${i === active ? "on" : ""}`}
                onMouseDown={(e) => e.preventDefault()} onMouseEnter={() => setActive(i)} onClick={() => go(it)}>{it.label}</button>
            ))}
        </div>
      )}
    </div>
  );
}
