import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, LngLatBoundsLike, Map as MLMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre >= 5 runs tile processing in a module worker. Let Vite bundle it (ES format, see
// vite.config.ts) and hand MapLibre the emitted URL; otherwise production builds reference a
// worker file that is never emitted.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { EventFilters } from "../lib/hooks";
import { CLASS_META, FACILITY_COLORS, FACILITY_LABELS } from "../lib/taxonomy";
import type { EventDetail } from "../lib/types";

export interface LayerState {
  events: boolean;
  facilities: boolean;
  detections: boolean;
  dispersion: boolean;
  imagery: boolean;
  heat: boolean;
  radius: boolean;
}
export const DEFAULT_LAYERS: LayerState = { events: true, facilities: true, detections: true, dispersion: true, imagery: false, heat: false, radius: true };
/** Rule "near" threshold (2 km) and backend facility search radius (ATTRIBUTION_RADIUS_M, 10 km). */
const RINGS_M = [2000, 10000];

maplibregl.setWorkerUrl(maplibreWorkerUrl);

const STYLE_LIGHT = (import.meta.env.VITE_MAP_STYLE_LIGHT as string) || "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const STYLE_DARK = (import.meta.env.VITE_MAP_STYLE_DARK as string) || "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const INDIA: LngLatBoundsLike = [[68, 6.5], [97.5, 35.7]];
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

const classColorExpr: maplibregl.ExpressionSpecification = [
  "match", ["get", "classification"],
  ...Object.entries(CLASS_META).flatMap(([k, v]) => [k, v.color]),
  "#9aa1ab",
] as unknown as maplibregl.ExpressionSpecification;
const facColorExpr: maplibregl.ExpressionSpecification = [
  "match", ["get", "type"], ...Object.entries(FACILITY_COLORS).flatMap(([k, v]) => [k, v]), "#868e96",
] as unknown as maplibregl.ExpressionSpecification;

function destination(lat: number, lon: number, bearing: number, meters: number): [number, number] {
  const R = 6_371_008.8, d = meters / R, b = (bearing * Math.PI) / 180, p1 = (lat * Math.PI) / 180, l1 = (lon * Math.PI) / 180;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [(l2 * 180) / Math.PI, (p2 * 180) / Math.PI];
}

function ring(lat: number, lon: number, meters: number): GeoJSON.Position[] {
  return Array.from({ length: 73 }, (_, i) => destination(lat, lon, i * 5, meters));
}

function focusGeo(ev: EventDetail | null) {
  if (!ev) return { dets: EMPTY, footprint: EMPTY, arrow: EMPTY, links: EMPTY, rings: EMPTY };
  const dets: GeoJSON.FeatureCollection = {
    type: "FeatureCollection",
    features: ev.detections.map((d) => ({ type: "Feature", geometry: { type: "Point", coordinates: [d.longitude, d.latitude] },
      properties: { frp: d.frp ?? 0, night: d.daynight === "N" ? 1 : 0, t: d.acq_datetime, sat: d.satellite } })),
  };
  const footprint: GeoJSON.FeatureCollection = ev.footprint
    ? { type: "FeatureCollection", features: [{ type: "Feature", geometry: ev.footprint, properties: {} }] } : EMPTY;
  const w = ev.weather[0];
  let arrow: GeoJSON.FeatureCollection = EMPTY;
  if (w && w.wind_direction_deg != null) {
    const bearing = (w.wind_direction_deg + 180) % 360;
    const len = 2500 + Math.min(w.wind_speed_ms ?? 0, 15) * 400;
    const tip = destination(ev.latitude, ev.longitude, bearing, len);
    const l = destination(tip[1], tip[0], bearing + 150, 450), r = destination(tip[1], tip[0], bearing - 150, 450);
    arrow = { type: "FeatureCollection", features: [
      { type: "Feature", geometry: { type: "LineString", coordinates: [[ev.longitude, ev.latitude], tip] }, properties: {} },
      { type: "Feature", geometry: { type: "LineString", coordinates: [l, tip, r] }, properties: {} },
    ] };
  }
  const links: GeoJSON.FeatureCollection = {
    type: "FeatureCollection",
    features: ev.facilities.slice(0, 3).map((f) => ({ type: "Feature", properties: { d: Math.round(f.distance_m) },
      geometry: { type: "LineString", coordinates: [[ev.longitude, ev.latitude], [f.longitude, f.latitude]] } })),
  };
  const rings: GeoJSON.FeatureCollection = {
    type: "FeatureCollection",
    features: RINGS_M.map((r) => ({ type: "Feature", properties: { label: `${r / 1000} km` },
      geometry: { type: "LineString", coordinates: ring(ev.latitude, ev.longitude, r) } })),
  };
  return { dets, footprint, arrow, links, rings };
}

interface Props {
  filters: EventFilters;
  layers: LayerState;
  theme: "light" | "dark";
  selectedId: string | null;
  focus: EventDetail | null;
  onSelect: (id: string | null) => void;
  onViewport?: (info: { count: number; truncated: boolean; loading: boolean; error: string | null }) => void;
  replayUntil?: string | null;
  flyTo?: { lat: number; lon: number; zoom?: number } | null;
}

export default function MapCanvas({ filters, layers, theme, selectedId, focus, onSelect, onViewport, replayUntil, flyTo }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(0);
  const filtersKey = JSON.stringify(filters);
  const loadSeq = useRef(0);
  const cbs = useRef({ onSelect, onViewport });
  cbs.current = { onSelect, onViewport };

  // --- init / theme (style swap rebuilds custom layers) -----------------------------------------
  useEffect(() => {
    if (!el.current) return;
    // Keep the current view across theme switches; never pass undefined center/zoom (NaN transform).
    const prev = mapRef.current;
    const view = prev ? { center: prev.getCenter(), zoom: prev.getZoom() } : { bounds: INDIA };
    const map = new maplibregl.Map({
      container: el.current,
      style: theme === "dark" ? STYLE_DARK : STYLE_LIGHT,
      ...view,
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    map.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: false }, trackUserLocation: false }), "bottom-right");
    map.on("load", () => {
      map.addSource("imagery", { type: "raster", tileSize: 256, maxzoom: 15,
        tiles: ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/g/{z}/{y}/{x}.jpg"],
        attribution: "Sentinel-2 cloudless 2021 by EOX IT Services (Contains modified Copernicus Sentinel data 2021)" });
      map.addLayer({ id: "imagery", type: "raster", source: "imagery", layout: { visibility: "none" } }, map.getStyle().layers.find((l) => l.type === "symbol")?.id);

      map.addSource("events", { type: "geojson", data: EMPTY, cluster: true, clusterRadius: 38, clusterMaxZoom: 8,
        attribution: "NASA FIRMS" });
      map.addSource("events-raw", { type: "geojson", data: EMPTY });
      map.addSource("facilities", { type: "geojson", data: EMPTY, attribution: "© OpenStreetMap contributors · WRI GPPD" });
      map.addSource("focus-dets", { type: "geojson", data: EMPTY });
      map.addSource("focus-footprint", { type: "geojson", data: EMPTY });
      map.addSource("focus-arrow", { type: "geojson", data: EMPTY });
      map.addSource("focus-links", { type: "geojson", data: EMPTY });
      map.addSource("focus-rings", { type: "geojson", data: EMPTY });

      map.addLayer({ id: "heat", type: "heatmap", source: "events-raw", layout: { visibility: "none" }, paint: {
        "heatmap-weight": ["interpolate", ["linear"], ["get", "obs"], 1, 0.2, 50, 1],
        "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 3, 8, 9, 24],
        "heatmap-opacity": 0.75,
        "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"], 0, "rgba(0,0,0,0)", 0.3, "#ffd8a8", 0.6, "#ff922b", 1, "#c92a2a"],
      } });
      map.addLayer({ id: "fac", type: "circle", source: "facilities", minzoom: 6, paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 2.5, 12, 5], "circle-color": facColorExpr,
        "circle-stroke-color": "#fff", "circle-stroke-width": 1, "circle-opacity": 0.85 } });
      map.addLayer({ id: "fac-label", type: "symbol", source: "facilities", minzoom: 10, layout: {
        "text-field": ["coalesce", ["get", "name"], ""], "text-size": 10.5, "text-offset": [0, 1.1], "text-anchor": "top", "text-optional": true },
        paint: { "text-color": theme === "dark" ? "#c9ced6" : "#4a505c", "text-halo-color": theme === "dark" ? "#16181d" : "#fff", "text-halo-width": 1.2 } });
      map.addLayer({ id: "focus-rings", type: "line", source: "focus-rings", paint: {
        "line-color": theme === "dark" ? "#7d8490" : "#868e96", "line-width": 1, "line-dasharray": [4, 3] } });
      map.addLayer({ id: "focus-rings-label", type: "symbol", source: "focus-rings", layout: {
        "symbol-placement": "line", "text-field": ["get", "label"], "text-size": 10, "text-font": ["Open Sans Regular", "Noto Sans Regular"] },
        paint: { "text-color": theme === "dark" ? "#b0b6bf" : "#4a505c", "text-halo-color": theme === "dark" ? "#16181d" : "#fff", "text-halo-width": 1.2 } });
      map.addLayer({ id: "focus-footprint", type: "fill", source: "focus-footprint", paint: { "fill-color": "#e8590c", "fill-opacity": 0.08 } });
      map.addLayer({ id: "focus-footprint-line", type: "line", source: "focus-footprint", paint: { "line-color": "#e8590c", "line-width": 1, "line-dasharray": [2, 2] } });
      map.addLayer({ id: "focus-links", type: "line", source: "focus-links", paint: { "line-color": "#1c6fd1", "line-width": 1, "line-dasharray": [1, 2] } });
      map.addLayer({ id: "focus-dets", type: "circle", source: "focus-dets", paint: {
        "circle-radius": ["interpolate", ["linear"], ["get", "frp"], 0, 3, 50, 7, 300, 11],
        "circle-color": ["case", ["==", ["get", "night"], 1], "#862e9c", "#e8590c"], "circle-opacity": 0.55,
        "circle-stroke-color": "#fff", "circle-stroke-width": 0.5 } });
      map.addLayer({ id: "focus-arrow", type: "line", source: "focus-arrow", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#1c6fd1", "line-width": 2.2 } });

      map.addLayer({ id: "clusters", type: "circle", source: "events", filter: ["has", "point_count"], paint: {
        "circle-color": theme === "dark" ? "#2a2e36" : "#ffffff", "circle-stroke-color": "#e8590c", "circle-stroke-width": 1.5,
        "circle-radius": ["step", ["get", "point_count"], 13, 20, 17, 100, 22, 500, 27] } });
      map.addLayer({ id: "cluster-count", type: "symbol", source: "events", filter: ["has", "point_count"],
        layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 11, "text-font": ["Open Sans Semibold", "Noto Sans Regular"] },
        paint: { "text-color": theme === "dark" ? "#e8eaed" : "#16181d" } });
      map.addLayer({ id: "ev", type: "circle", source: "events", filter: ["!", ["has", "point_count"]], paint: {
        "circle-radius": ["interpolate", ["linear"], ["get", "frp"], 0, 4, 20, 6, 100, 9, 500, 13],
        "circle-color": classColorExpr,
        "circle-opacity": ["case", ["==", ["get", "status"], "dormant"], 0.45, 0.9],
        "circle-stroke-width": 1,
        "circle-stroke-color": ["match", ["get", "state"], ["INSUFFICIENT_EVIDENCE"], "#9aa1ab", ["ANALYST_CONFIRMED", "CONFIRMED"], "#2b8a3e", ["ANALYST_REJECTED"], "#c92a2a", "#ffffff"] } });
      map.addLayer({ id: "ev-selected", type: "circle", source: "events", filter: ["==", ["get", "id"], ""], paint: {
        "circle-radius": 15, "circle-color": "transparent", "circle-stroke-color": theme === "dark" ? "#fff" : "#16181d", "circle-stroke-width": 2 } });

      map.on("click", "clusters", async (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const zoom = await (map.getSource("events") as GeoJSONSource).getClusterExpansionZoom(f.properties.cluster_id);
        map.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom });
      });
      map.on("click", "ev", (e) => {
        const id = e.features?.[0]?.properties?.id;
        if (id) cbs.current.onSelect(id);
      });
      map.on("click", "fac", (e) => {
        const p = e.features?.[0]?.properties;
        if (!p) return;
        new maplibregl.Popup({ closeButton: false, maxWidth: "260px" }).setLngLat(e.lngLat)
          .setHTML(`<b>${(p.name || "Unnamed facility").replace(/</g, "&lt;")}</b><br/>${FACILITY_LABELS[p.type] ?? p.type}<br/><span style="color:var(--text-3)">source: ${p.source}${p.sources > 1 ? ` (+${p.sources - 1})` : ""} · confidence ${(+p.confidence).toFixed(2)}</span>`)
          .addTo(map);
      });
      for (const l of ["ev", "clusters", "fac"]) {
        map.on("mouseenter", l, () => (map.getCanvas().style.cursor = "pointer"));
        map.on("mouseleave", l, () => (map.getCanvas().style.cursor = ""));
      }
      setReady((n) => n + 1);
    });
    mapRef.current = map;
    prev?.remove();
    return () => {
      if (mapRef.current === map) {
        map.remove();
        mapRef.current = null;
      }
    };
  }, [theme]);

  // --- viewport-bounded loading ------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    let timer: number | undefined;
    const load = async () => {
      const seq = ++loadSeq.current;
      const b = map.getBounds();
      const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v, i) => Math.max(i % 2 ? -90 : -180, Math.min(i % 2 ? 90 : 180, v)).toFixed(4)).join(",");
      cbs.current.onViewport?.({ count: 0, truncated: false, loading: true, error: null });
      try {
        const [evs, facs] = await Promise.all([
          api<GeoJSON.FeatureCollection & { truncated: boolean }>("/events/geojson", { query: { ...filters, bbox, limit: 3000 } as never }),
          layers.facilities && map.getZoom() >= 6
            ? api<GeoJSON.FeatureCollection>("/facilities/geojson", { query: { bbox, limit: 4000 } })
            : Promise.resolve(EMPTY),
        ]);
        if (seq !== loadSeq.current || !map.getSource("events")) return;
        (map.getSource("events") as GeoJSONSource).setData(evs);
        (map.getSource("events-raw") as GeoJSONSource).setData(evs);
        (map.getSource("facilities") as GeoJSONSource).setData(facs);
        cbs.current.onViewport?.({ count: evs.features.length, truncated: evs.truncated, loading: false, error: null });
      } catch (e) {
        if (seq === loadSeq.current) cbs.current.onViewport?.({ count: 0, truncated: false, loading: false, error: (e as Error).message });
      }
    };
    const schedule = () => { window.clearTimeout(timer); timer = window.setTimeout(load, 250); };
    map.on("moveend", schedule);
    load();
    return () => { map.off("moveend", schedule); window.clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, filtersKey, layers.facilities]);

  // --- layer visibility ---------------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const vis = (id: string, on: boolean) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    ["clusters", "cluster-count", "ev", "ev-selected"].forEach((l) => vis(l, layers.events && !layers.heat));
    vis("heat", layers.heat);
    ["fac", "fac-label"].forEach((l) => vis(l, layers.facilities));
    ["focus-dets", "focus-footprint", "focus-footprint-line", "focus-links"].forEach((l) => vis(l, layers.detections));
    vis("focus-arrow", layers.dispersion);
    ["focus-rings", "focus-rings-label"].forEach((l) => vis(l, layers.radius));
    vis("imagery", layers.imagery);
  }, [ready, layers]);

  // --- selection + focus overlays ------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getLayer("ev-selected")) return;
    map.setFilter("ev-selected", ["==", ["get", "id"], selectedId ?? ""]);
    const g = focusGeo(focus && focus.id === selectedId ? focus : null);
    const dets = replayUntil
      ? { ...g.dets, features: g.dets.features.filter((f) => (f.properties as { t: string }).t <= replayUntil) }
      : g.dets;
    (map.getSource("focus-dets") as GeoJSONSource).setData(dets);
    (map.getSource("focus-footprint") as GeoJSONSource).setData(g.footprint);
    (map.getSource("focus-arrow") as GeoJSONSource).setData(g.arrow);
    (map.getSource("focus-links") as GeoJSONSource).setData(g.links);
    (map.getSource("focus-rings") as GeoJSONSource).setData(g.rings);
  }, [ready, selectedId, focus, replayUntil]);

  const lastFocus = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !focus || focus.id !== selectedId || lastFocus.current === focus.id) return;
    lastFocus.current = focus.id;
    if (map.getZoom() < 10 || !map.getBounds().contains([focus.longitude, focus.latitude])) {
      map.flyTo({ center: [focus.longitude, focus.latitude], zoom: Math.max(map.getZoom(), 11.5), speed: 1.6 });
    }
  }, [ready, focus, selectedId]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && ready && flyTo) map.flyTo({ center: [flyTo.lon, flyTo.lat], zoom: flyTo.zoom ?? 10 });
  }, [ready, flyTo]);

  return <div ref={el} className="map" role="region" aria-label="Thermal events map" />;
}
