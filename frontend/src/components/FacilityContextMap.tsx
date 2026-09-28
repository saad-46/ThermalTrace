/** Map context for one facility: its location, the selected event (if any), the distance between them and the rule
 *  (2 km) and search (10 km) radii around the event, or around the facility when no event is selected.
 *
 *  A Map / Satellite toggle swaps the vector basemap for EOX Sentinel-2 cloudless annual mosaics (keyless public raster
 *  tiles, loaded by the browser only when Satellite is first chosen). The mosaic is geographic context: a cloud-free
 *  composite of many scenes with no single acquisition date, never fire or burn evidence. */
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { AlertTriangle, RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fmtDistance } from "../lib/format";
import { FACILITY_LABELS } from "../lib/taxonomy";
import type { DisplayState, SourceClass } from "../lib/types";
import { addFacilityIcons, classColorExpr, enhanceBasemap, mapStyleUrl, ring, RINGS_M, withCartoKey } from "./MapCanvas";

/** Years with a published EOX s2cloudless Web Mercator layer (each checked to serve tiles over India). */
export const SAT_YEARS = [2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018] as const;
/** VITE_SATELLITE_IMAGERY=off turns the layer off (e.g. a commercial deployment without an imagery licence). */
const SAT_ENABLED = String(import.meta.env.VITE_SATELLITE_IMAGERY ?? "").trim().toLowerCase() !== "off";
const SAT_TIMEOUT_MS = 20000;
const satTiles = (year: number) => `https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-${year}_3857/default/g/{z}/{y}/{x}.jpg`;
export const satAttribution = (year: number) => `Sentinel-2 cloudless ${year} by EOX IT Services (Contains modified Copernicus Sentinel data ${year})`;

export type MapView = "map" | "satellite";
type SatState = { state: "idle" | "loading" | "available" | "none" | "failed" | "unconfigured" | "invalid"; detail?: string };
export interface NearbyEvent {
  public_id: string; latitude: number | null; longitude: number | null; classification: SourceClass | null;
  frp_max: number | null; confidence_state: DisplayState; status: string;
}

const validCoords = (lat: number, lon: number) => Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180;

/** Tile errors from the imagery source, reduced to one honest message. */
function classify(statuses: number[]): SatState {
  if (statuses.every((s) => s === 404)) return { state: "none" };
  if (statuses.some((s) => s === 401 || s === 403)) return { state: "failed", detail: "The imagery provider refused the request." };
  if (statuses.some((s) => s === 429)) return { state: "failed", detail: "The imagery provider is rate-limiting requests; try again shortly." };
  if (statuses.some((s) => !s)) return { state: "failed", detail: "Network error while contacting the imagery provider." };
  return { state: "failed", detail: "The imagery provider returned an error." };
}

export function FacilityContextMap({ facility, event, distanceM, theme, nearby, initialView = "map", onViewChange }: {
  facility: { latitude: number; longitude: number; facility_type: string; name: string | null; operator?: string | null; status?: string | null };
  event?: { latitude: number; longitude: number; public_id: string } | null;
  distanceM?: number | null;
  theme: "light" | "dark";
  /** Thermal events linked to this facility; drawn in satellite mode. */
  nearby?: NearbyEvent[];
  initialView?: MapView;
  onViewChange?: (v: MapView) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const satKey = useRef<string | null>(null); // "<year>:<attempt>" currently on the map
  const viewRef = useRef<MapView>(initialView);
  const [ready, setReady] = useState(false);
  const [view, setViewState] = useState<MapView>(initialView);
  const [year, setYear] = useState<number>(SAT_YEARS[0]);
  const [attempt, setAttempt] = useState(0);
  const [sat, setSat] = useState<SatState>({ state: "idle" });
  const navigate = useNavigate();
  const dark = theme === "dark";
  viewRef.current = view;

  const setView = (v: MapView) => { setViewState(v); onViewChange?.(v); };

  useEffect(() => {
    if (!el.current) return;
    const center = event ?? facility;
    const outer = ring(center.latitude, center.longitude, RINGS_M[RINGS_M.length - 1]);
    const lons = outer.map((p) => p[0]).concat(facility.longitude), lats = outer.map((p) => p[1]).concat(facility.latitude);
    const map = new maplibregl.Map({
      container: el.current, style: mapStyleUrl(theme), attributionControl: { compact: true },
      bounds: [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], fitBoundsOptions: { padding: 24 },
      transformRequest: (url) => ({ url: withCartoKey(url) }), dragRotate: false, pitchWithRotate: false, cooperativeGestures: true,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    map.on("load", () => {
      enhanceBasemap(map, dark);
      addFacilityIcons(map, dark);
      const labelColor = dark ? "#c9ced6" : "#4a505c", halo = dark ? "#16181d" : "#fff";
      map.addSource("rings", { type: "geojson", data: { type: "FeatureCollection", features: RINGS_M.map((r) => ({
        type: "Feature", properties: { label: `${r / 1000} km` }, geometry: { type: "LineString", coordinates: ring(center.latitude, center.longitude, r) } })) } });
      map.addLayer({ id: "rings", type: "line", source: "rings", paint: { "line-color": dark ? "#7d8490" : "#868e96", "line-width": 1, "line-dasharray": [4, 3] } });
      map.addLayer({ id: "rings-label", type: "symbol", source: "rings", layout: { "symbol-placement": "line", "text-field": ["get", "label"], "text-size": 10,
        "text-font": ["Open Sans Regular", "Noto Sans Regular"] }, paint: { "text-color": labelColor, "text-halo-color": halo, "text-halo-width": 1.2 } });
      // linked events: the same class colours and FRP sizing as the live map; shown only in satellite mode
      map.addSource("nearby", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({ id: "nearby", type: "circle", source: "nearby", layout: { visibility: "none" }, paint: {
        "circle-radius": ["interpolate", ["linear"], ["get", "frp"], 0, 3.5, 20, 5, 100, 7, 500, 10],
        "circle-color": classColorExpr, "circle-opacity": ["case", ["==", ["get", "status"], "dormant"], 0.55, 0.95],
        "circle-stroke-width": 1.2, "circle-stroke-color": "#ffffff" } });
      if (event) {
        map.addSource("link", { type: "geojson", data: { type: "Feature", properties: { d: distanceM != null ? fmtDistance(distanceM) : "" },
          geometry: { type: "LineString", coordinates: [[event.longitude, event.latitude], [facility.longitude, facility.latitude]] } } });
        map.addLayer({ id: "link", type: "line", source: "link", paint: { "line-color": dark ? "#5aa2f0" : "#1c6fd1", "line-width": 1.4, "line-dasharray": [1, 2] } });
        map.addLayer({ id: "link-label", type: "symbol", source: "link", layout: { "symbol-placement": "line-center", "text-field": ["get", "d"], "text-size": 11,
          "text-font": ["Open Sans Semibold", "Noto Sans Regular"] }, paint: { "text-color": labelColor, "text-halo-color": halo, "text-halo-width": 1.4 } });
        map.addSource("event", { type: "geojson", data: { type: "Feature", properties: { label: event.public_id, id: event.public_id }, geometry: { type: "Point", coordinates: [event.longitude, event.latitude] } } });
        map.addLayer({ id: "event-halo", type: "circle", source: "event", paint: { "circle-radius": 16, "circle-color": "#ff7a2e", "circle-opacity": 0.28, "circle-blur": 0.8 } });
        map.addLayer({ id: "event", type: "circle", source: "event", paint: { "circle-radius": 6, "circle-color": "#ff7a2e", "circle-stroke-color": dark ? "#fff" : "#16181d", "circle-stroke-width": 2 } });
        map.addLayer({ id: "event-label", type: "symbol", source: "event", layout: { "text-field": ["get", "label"], "text-size": 10.5, "text-offset": [0, 1.4], "text-anchor": "top",
          "text-font": ["Open Sans Semibold", "Noto Sans Regular"] }, paint: { "text-color": labelColor, "text-halo-color": halo, "text-halo-width": 1.2 } });
      }
      map.addSource("facility", { type: "geojson", data: { type: "Feature", properties: { type: facility.facility_type, label: facility.name ?? "" },
        geometry: { type: "Point", coordinates: [facility.longitude, facility.latitude] } } });
      // a light disc under the facility icon keeps it legible over imagery (satellite mode only)
      map.addLayer({ id: "facility-halo", type: "circle", source: "facility", layout: { visibility: "none" }, paint: {
        "circle-radius": 15, "circle-color": "#ffffff", "circle-opacity": 0.92, "circle-stroke-color": "#16181d", "circle-stroke-width": 1.5 } });
      map.addLayer({ id: "facility", type: "symbol", source: "facility", layout: {
        "icon-image": ["coalesce", ["image", ["concat", "fac-", ["get", "type"]]], ["image", "fac-other"]], "icon-size": 1.3, "icon-allow-overlap": true,
        "text-field": ["get", "label"], "text-size": 11, "text-offset": [0, 1.2], "text-anchor": "top", "text-optional": true,
        "text-font": ["Open Sans Semibold", "Noto Sans Regular"] }, paint: { "text-color": labelColor, "text-halo-color": halo, "text-halo-width": 1.2 } });
      // events open the existing event page, as the events table below does (satellite mode only: the map view is unchanged)
      const open = (e: maplibregl.MapLayerMouseEvent) => {
        const id = e.features?.[0]?.properties?.id;
        if (viewRef.current === "satellite" && id) navigate(`/events/${id}`);
      };
      const hover = (on: boolean) => () => { if (viewRef.current === "satellite") map.getCanvas().style.cursor = on ? "pointer" : ""; };
      for (const l of ["nearby", "event"]) {
        if (!map.getLayer(l)) continue;
        map.on("click", l, open); map.on("mouseenter", l, hover(true)); map.on("mouseleave", l, hover(false));
      }
      mapRef.current = map;
      map.getContainer().dataset.ready = "1";
      setReady(true);
    });
    return () => { setReady(false); mapRef.current = null; satKey.current = null; map.remove(); };
  }, [facility, event, distanceM, theme, dark, navigate]);

  // nearby events (kept separate so paging the events table never rebuilds the map)
  useEffect(() => {
    const src = ready ? mapRef.current?.getSource("nearby") as maplibregl.GeoJSONSource | undefined : undefined;
    if (!src) return;
    src.setData({ type: "FeatureCollection", features: (nearby ?? [])
      .filter((e) => e.public_id !== event?.public_id && e.latitude != null && e.longitude != null && validCoords(e.latitude, e.longitude))
      .map((e) => ({ type: "Feature", properties: { id: e.public_id, classification: e.classification, frp: e.frp_max ?? 0, status: e.status, state: e.confidence_state },
        geometry: { type: "Point", coordinates: [e.longitude!, e.latitude!] } })) });
  }, [ready, nearby, event]);

  // overlay styling: white rings and haloed labels stay readable over imagery
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const s = view === "satellite";
    const labelColor = s ? "#ffffff" : dark ? "#c9ced6" : "#4a505c", halo = s ? "rgba(10,12,16,0.85)" : dark ? "#16181d" : "#fff";
    const paint = (id: string, prop: string, v: unknown) => { if (map.getLayer(id)) map.setPaintProperty(id, prop as never, v as never); };
    const layout = (id: string, prop: string, v: unknown) => { if (map.getLayer(id)) map.setLayoutProperty(id, prop as never, v as never); };
    paint("rings", "line-color", s ? "#ffffff" : dark ? "#7d8490" : "#868e96");
    paint("rings", "line-width", s ? 1.5 : 1);
    for (const id of ["rings-label", "link-label", "event-label", "facility"]) { paint(id, "text-color", labelColor); paint(id, "text-halo-color", halo); paint(id, "text-halo-width", s ? 1.6 : id === "link-label" ? 1.4 : 1.2); }
    paint("link", "line-color", s ? "#9cd0ff" : dark ? "#5aa2f0" : "#1c6fd1");
    paint("event", "circle-stroke-color", s ? "#ffffff" : dark ? "#fff" : "#16181d");
    layout("facility-halo", "visibility", s ? "visible" : "none");
    layout("nearby", "visibility", s ? "visible" : "none");
    // events sit within a few hundred metres of the plant: over imagery they are drawn above the facility marker so
    // they stay visible and clickable; the map view keeps its original order (facility on top)
    const eventLayers = ["nearby", "event-halo", "event", "event-label"].filter((id) => map.getLayer(id));
    for (const id of eventLayers) map.moveLayer(id, s ? undefined : "facility-halo");
    if (!s) map.getCanvas().style.cursor = "";
    // on a narrow map the expanded imagery credit would cover the imagery; it stays one tap away (i) and in the card
    const attrib = map.getContainer().querySelector("details.maplibregl-ctrl-attrib");
    if (s && attrib && map.getContainer().clientWidth < 520) { attrib.removeAttribute("open"); attrib.classList.remove("maplibregl-compact-show"); }
  }, [ready, view, dark]);

  // imagery layer: added on first use, hidden (not removed) when switching back so toggling does not refetch tiles
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (view !== "satellite") {
      if (!map.getLayer("sat")) return;
      map.setPaintProperty("sat", "raster-opacity", 0);
      const t = window.setTimeout(() => { if (map.getLayer("sat")) map.setLayoutProperty("sat", "visibility", "none"); }, 320);
      return () => window.clearTimeout(t);
    }
    if (!SAT_ENABLED) { setSat({ state: "unconfigured" }); return; }
    if (!validCoords(facility.latitude, facility.longitude)) { setSat({ state: "invalid" }); return; }
    const key = `${year}:${attempt}`;
    if (satKey.current === key && map.getLayer("sat")) {
      map.setLayoutProperty("sat", "visibility", "visible");
      map.setPaintProperty("sat", "raster-opacity", 1);
      return;
    }
    if (map.getLayer("sat")) map.removeLayer("sat");
    if (map.getSource("sat")) map.removeSource("sat");
    if (typeof navigator !== "undefined" && navigator.onLine === false) { setSat({ state: "failed", detail: "This device is offline." }); return; }
    setSat({ state: "loading" });
    satKey.current = key;
    map.addSource("sat", { type: "raster", tileSize: 256, maxzoom: 17, tiles: [satTiles(year)], attribution: satAttribution(year) });
    // above the whole vector basemap (its roads and labels would clutter the imagery), below every ThermalTrace overlay
    map.addLayer({ id: "sat", type: "raster", source: "sat", paint: { "raster-opacity": 0, "raster-opacity-transition": { duration: 300, delay: 0 } } }, "rings");
    requestAnimationFrame(() => { if (map.getLayer("sat")) map.setPaintProperty("sat", "raster-opacity", 1); });
    let loaded = 0;
    const statuses: number[] = [];
    const onData = (e: maplibregl.MapSourceDataEvent) => {
      if (e.sourceId === "sat" && e.dataType === "source" && e.tile && ++loaded === 1) setSat({ state: "available" });
    };
    const onError = (e: maplibregl.ErrorEvent & { sourceId?: string }) => {
      if (e.sourceId !== "sat") return;
      statuses.push((e.error as { status?: number } | undefined)?.status ?? 0);
    };
    // MapLibre does not raise an error event for 404 tiles (it marks them errored and tries parents), so "no imagery"
    // is a settled source with nothing loaded; other failures arrive as error events with the HTTP status
    const started = Date.now();
    let settled = 0;
    const poll = window.setInterval(() => {
      if (loaded) { window.clearInterval(poll); return; }
      settled = map.getSource("sat") && map.isSourceLoaded("sat") ? settled + 1 : 0;
      if (settled >= 2 && Date.now() - started > 1500) { window.clearInterval(poll); setSat(statuses.length ? classify(statuses) : { state: "none" }); }
    }, 500);
    const timer = window.setTimeout(() => {
      window.clearInterval(poll);
      if (!loaded) setSat(statuses.length ? classify(statuses) : { state: "failed", detail: "The imagery provider did not respond in time." });
    }, SAT_TIMEOUT_MS);
    map.on("sourcedata", onData); map.on("error", onError);
    return () => {
      window.clearTimeout(timer); window.clearInterval(poll);
      map.off("sourcedata", onData); map.off("error", onError);
      if (!loaded) satKey.current = null; // unfinished: start again next time rather than keep a stuck "loading"
    };
  }, [ready, view, year, attempt, facility]);

  const isSat = view === "satellite";
  const typeLabel = FACILITY_LABELS[facility.facility_type] ?? facility.facility_type;
  const message = !isSat ? null
    : sat.state === "loading" ? "Loading satellite imagery…"
    : sat.state === "none" ? "No suitable satellite imagery available for this location."
    : sat.state === "failed" ? "Satellite imagery could not be loaded."
    : sat.state === "unconfigured" ? "Satellite imagery is not configured for this environment."
    : sat.state === "invalid" ? "Satellite imagery unavailable for this location: the facility coordinates are not valid."
    : null;
  const live = !isSat ? "Map view" : sat.state === "available" ? `Satellite view: Sentinel-2 cloudless ${year} mosaic loaded` : message ?? "Satellite view";
  const showYear = isSat && SAT_ENABLED && sat.state !== "invalid";

  return (
    <div className={`fac-map ${isSat ? "is-sat" : ""}`} data-view={view}>
      <div className="fac-map-bar">
        <div className="seg" role="group" aria-label="Map view">
          <button type="button" className={!isSat ? "on" : ""} aria-pressed={!isSat} onClick={() => setView("map")} data-testid="view-map">Map</button>
          <button type="button" className={isSat ? "on" : ""} aria-pressed={isSat} onClick={() => setView("satellite")} data-testid="view-satellite">Satellite</button>
        </div>
        {showYear && (
          <label className="fac-map-year">
            <span className="faint">Mosaic</span>
            <select className="select" value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="Satellite mosaic year" data-testid="satellite-year">
              {SAT_YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
        )}
      </div>
      <div className="fac-map-stage">
        <div ref={el} className="fac-context-map" role="region" aria-label={isSat ? "Facility satellite map" : "Facility location map"} data-testid="facility-map" />
        {message && (
          <div className={`fac-map-msg ${sat.state === "loading" ? "loading" : ""}`} data-testid="satellite-status" data-state={sat.state}>
            {sat.state === "loading" ? <span className="spinner" /> : <AlertTriangle size={16} strokeWidth={1.6} />}
            <span className="title">{message}</span>
            {sat.state === "failed" && sat.detail && <span className="faint">{sat.detail}</span>}
            {sat.state === "failed" && <button type="button" className="btn sm" onClick={() => setAttempt((n) => n + 1)}><RotateCw size={13} /> Retry</button>}
          </div>
        )}
      </div>
      <div className="sr-only" aria-live="polite">{live}</div>
      {isSat && (
        <section className="fac-sat-card" aria-label="Facility satellite view" data-testid="satellite-card">
          <div className="fac-sat-head">Facility satellite view</div>
          <dl className="kv">
            <dt>Facility</dt><dd>{facility.name ?? "Unnamed facility"}</dd>
            <dt>Type</dt><dd>{typeLabel}{facility.status ? ` · ${facility.status}` : ""}</dd>
            {facility.operator && <><dt>Operator</dt><dd>{facility.operator}</dd></>}
            <dt>Imagery date</dt><dd>{sat.state === "available" || sat.state === "loading" ? `${year} annual mosaic · no single acquisition date` : "Date unavailable"}</dd>
            <dt>Coverage</dt><dd>Facility · 2 km · 10 km rings{event ? ` around ${event.public_id}` : ""}</dd>
            <dt>Source</dt><dd>{SAT_ENABLED ? <>Sentinel-2 cloudless {year}, EOX IT Services (contains modified Copernicus Sentinel data; CC BY-NC-SA 4.0)</> : "Not configured"}</dd>
          </dl>
          <div className="faint fac-sat-note">Geographic context only: a cloud-free composite of many scenes. It does not show, confirm or date any fire or burn, and does not show that this facility caused a thermal anomaly.</div>
        </section>
      )}
    </div>
  );
}
