import { Layers, Maximize2, Pause, Play, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { EventRowMini } from "../components/evidence";
import { DEFAULT_FILTERS, FilterButton, TimeRange, toQuery, type FilterState } from "../components/filters";
import { EventActions, EventHeader, Investigation } from "../components/investigation";
import MapCanvas, { DEFAULT_LAYERS, LANDCOVER_COLORS, type LayerState } from "../components/MapCanvas";
import { Boundary, Empty, ErrorState, Skeleton } from "../components/ui";
import { fmtDateTime } from "../lib/format";
import { useEvent, useEvents } from "../lib/hooks";
import { useTheme } from "../lib/session";
import { CLASS_META, CLASS_ORDER } from "../lib/taxonomy";
import type { EventDetail } from "../lib/types";

/** Map layers by purpose; the default map stays clean (progressive disclosure). */
const LAYER_GROUPS: { title: string; items: [keyof LayerState, string, string][] }[] = [
  { title: "Thermal activity", items: [
    ["events", "Thermal events", "Clustered FIRMS events (circles), coloured by classification"],
    ["heat", "Thermal activity density", "Density of observed events in view (replaces markers); observed activity, not fire risk"],
  ] },
  { title: "Selected event", items: [
    ["detections", "Event pixels & footprint", "Selected event's FIRMS pixels (purple = night)"],
    ["radius", "2 km and 10 km rings", "Rule threshold and facility search radius around the selected event"],
    ["dispersion", "Potential dispersion direction", "Down-wind vector from weather at detection time (not plume tracking)"],
  ] },
  { title: "Infrastructure", items: [
    ["facilities", "Facilities", "OSM and registries (squares), zoom ≥ 6"],
    ["industrial", "Industrial areas", "OpenStreetMap landuse=industrial, zoom ≥ 9"],
    ["quarries", "Quarries and mines", "OpenStreetMap landuse=quarry, zoom ≥ 9"],
  ] },
  { title: "Geography", items: [
    ["states", "State boundaries", "Natural Earth states (India point of view)"],
    ["districts", "District boundaries", "OpenStreetMap admin level 5, zoom ≥ 8.5"],
    ["roads", "Roads", "National roads from zoom 4.5, then primary and secondary"],
    ["rivers", "Rivers", "OpenStreetMap waterways"],
    ["landcover", "Land cover (OpenStreetMap)", "Farmland, wood, grass, wetland, sand. Event evidence uses ESA WorldCover"],
    ["imagery", "Satellite basemap", "Sentinel-2 cloudless 2021 mosaic (EOX), context only"],
  ] },
];

function MapLegend({ layers, selected }: { layers: LayerState; selected: boolean }) {
  return (
    <details className="float legend" open aria-label="Legend" data-tour-id="map-legend">
      <summary>Legend</summary>
      {layers.events && !layers.heat && <>
        {CLASS_ORDER.map((c) => <div key={c} className="item"><span className="sw" style={{ background: CLASS_META[c].color }} />{CLASS_META[c].short}</div>)}
        <div className="item faint note">Circles = thermal events · size = peak FRP · grey ring = insufficient evidence</div>
      </>}
      {layers.heat && <div className="item note"><span className="ramp" aria-hidden /> Observed activity density (not risk)</div>}
      {layers.facilities && <div className="item note"><span className="sw sq" aria-hidden /> Squares = facilities · blue ring = linked to the selected event</div>}
      {(layers.industrial || layers.quarries) && <div className="item note">
        {layers.industrial && <><span className="sw sq" style={{ background: "#8a5a2b" }} aria-hidden /> Industrial </>}
        {layers.quarries && <><span className="sw sq" style={{ background: "#6b5d52" }} aria-hidden /> Quarry</>}</div>}
      {layers.landcover && <div className="item note">
        <div className="faint" style={{ width: "100%" }}>Land cover · OpenStreetMap (map context; event evidence uses ESA WorldCover)</div>
        {Object.entries(LANDCOVER_COLORS).map(([k, c]) => <span key={k} className="lc-chip"><span className="sw sq" style={{ background: c }} aria-hidden />{k}</span>)}</div>}
      {selected && layers.radius && <div className="item faint note">Dashed rings: 2 km and 10 km around the selected event</div>}
    </details>
  );
}

function Replay({ ev, onFrame }: { ev: EventDetail; onFrame: (t: string | null) => void }) {
  const times = useMemo(() => [...new Set(ev.detections.map((d) => d.acq_datetime))].sort(), [ev]);
  const [i, setI] = useState(times.length - 1);
  const [playing, setPlaying] = useState(false);
  useEffect(() => { setI(times.length - 1); setPlaying(false); }, [times]);
  useEffect(() => { onFrame(i >= times.length - 1 ? null : times[i]); }, [i, times, onFrame]);
  useEffect(() => {
    if (!playing) return;
    const t = window.setInterval(() => setI((v) => { if (v >= times.length - 1) { setPlaying(false); return v; } return v + 1; }), 350);
    return () => window.clearInterval(t);
  }, [playing, times.length]);
  if (times.length < 2) return null;
  return (
    <div className="row" style={{ gap: 8 }}>
      <button className="btn sm icon" onClick={() => { if (i >= times.length - 1) setI(0); setPlaying((p) => !p); }} aria-label={playing ? "Pause replay" : "Play replay"}>
        {playing ? <Pause size={13} /> : <Play size={13} />}
      </button>
      <input type="range" min={0} max={times.length - 1} value={i} onChange={(e) => { setPlaying(false); setI(+e.target.value); }} aria-label="Replay position" style={{ flex: 1 }} />
      <span className="mono faint" style={{ fontSize: 11, minWidth: 118 }}>{fmtDateTime(times[i])}</span>
    </div>
  );
}

export default function LiveMap() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("event");
  const [theme] = useTheme();
  // ?days= carries the dashboard's time range to the map
  const [filters, setFilters] = useState<FilterState>(() => ({ ...DEFAULT_FILTERS, days: params.get("days") ? Number(params.get("days")) : DEFAULT_FILTERS.days }));
  const [layers, setLayers] = useState<LayerState>(DEFAULT_LAYERS);
  const [showLayers, setShowLayers] = useState(false);
  const [vp, setVp] = useState<{ count: number; truncated: boolean; loading: boolean; error: string | null }>({ count: 0, truncated: false, loading: true, error: null });
  const [replayUntil, setReplayUntil] = useState<string | null>(null);
  const query = useMemo(() => toQuery(filters), [filters]);
  const ev = useEvent(selected ?? undefined);
  const priority = useEvents({ ...query, persistence: query.persistence ?? ["persistent", "recurring"] }, "persistence", 12, 0);
  const flyTo = useMemo(() => {
    const lat = params.get("lat"), lon = params.get("lon");
    return lat && lon ? { lat: +lat, lon: +lon, zoom: params.get("z") ? +params.get("z")! : 11 } : null;
  }, [params]);
  const select = (id: string | null) => {
    setReplayUntil(null);
    const next = new URLSearchParams(params);
    if (id) next.set("event", id); else next.delete("event");
    setParams(next, { replace: false });
  };

  return (
    <div className="workspace">
      <div className="map-wrap" data-tour-id="map-canvas">
        <Boundary label="Map">
          <MapCanvas filters={query} layers={layers} theme={theme} selectedId={ev.data?.id ?? selected} focus={ev.data ?? null}
            onSelect={select} onViewport={setVp} replayUntil={replayUntil} flyTo={flyTo} />
        </Boundary>
        {/* Top-left column: the toolbar, then the legend. The north-west corner of the map is outside India (Pakistan,
            Afghanistan), so nothing here covers Indian territory, Lakshadweep or the Kerala coast. */}
        <div className="map-overlay map-topleft">
        <div className="map-toolbar">
          <TimeRange value={filters.days} onChange={(days) => setFilters({ ...filters, days })} />
          <FilterButton f={filters} set={setFilters} />
          <div style={{ position: "relative" }}>
            <button className="btn" onClick={() => setShowLayers((v) => !v)} aria-expanded={showLayers}><Layers size={14} /> Layers</button>
            {showLayers && (
              <div className="float layers" style={{ position: "absolute", top: "110%", left: 0 }} data-tour-id="map-layers">
                <h4>Map layers</h4>
                {LAYER_GROUPS.map((g) => (
                  <div key={g.title} className="layer-group">
                    <div className="layer-group-title">{g.title}</div>
                    {g.items.map(([k, label, hint]) => (
                      <label key={k} className="check" title={hint}>
                        <input type="checkbox" checked={layers[k]} onChange={(e) => setLayers({ ...layers, [k]: e.target.checked })} /> {label}
                      </label>
                    ))}
                  </div>
                ))}
                <button className="btn ghost sm" onClick={() => setLayers(DEFAULT_LAYERS)}>Reset to defaults</button>
              </div>
            )}
          </div>
        </div>
        <MapLegend layers={layers} selected={!!selected} />
        </div>
        <div className="map-overlay float map-status" role="status">
          {vp.loading ? "Loading events in view…" : vp.error ? <span style={{ color: "var(--bad)" }}>Events unavailable: {vp.error}</span>
            : `${vp.count.toLocaleString()} events in view${vp.truncated ? " (most recent 3,000 — zoom in for all)" : ""}`}
        </div>
      </div>

      <aside className="side" aria-label="Event context" data-tour-id={selected ? "map-event-panel" : undefined}>
        {selected ? (
          ev.isLoading ? <div className="panel-body"><Skeleton lines={8} /></div>
          : ev.error ? <ErrorState error={ev.error} retry={() => ev.refetch()} />
          : ev.data && (
            <>
              <div className="section">
                <div className="row" style={{ alignItems: "flex-start" }}>
                  <EventHeader ev={ev.data} />
                  <span style={{ flex: 1 }} />
                  <Link className="btn sm icon" to={`/events/${ev.data.public_id}`} aria-label="Open full investigation" title="Open full investigation"><Maximize2 size={13} /></Link>
                  <button className="btn sm icon" onClick={() => select(null)} aria-label="Close event"><X size={13} /></button>
                </div>
                <div style={{ marginTop: 10 }}><EventActions ev={ev.data} compact /></div>
                <div style={{ marginTop: 10 }}><Replay ev={ev.data} onFrame={setReplayUntil} /></div>
              </div>
              <Investigation ev={ev.data} compact />
            </>
          )
        ) : (
          <>
            <div className="section">
              <h2>Persistent & recurring sources</h2>
              <div className="faint" style={{ fontSize: 12, marginTop: 2 }}>Ranked by persistence evidence in the selected time range, not by threat. Select a point on the map or an item below.</div>
            </div>
            <div className="section" style={{ paddingTop: 0 }}>
              {priority.isLoading ? <Skeleton lines={6} /> : priority.error ? <ErrorState error={priority.error} retry={() => priority.refetch()} />
                : priority.data?.items.length ? priority.data.items.map((e) => <EventRowMini key={e.id} e={e} to={`/map?event=${e.public_id}`} />)
                : <Empty title="No recurring sources in this range">Widen the time range or clear filters.</Empty>}
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
