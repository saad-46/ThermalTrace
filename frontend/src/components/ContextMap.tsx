/** A small static-context map: thermal events (circles), facilities (squares), an optional extent polygon and the
 *  2 km / 10 km rings around a focus point. Used by the cluster page and the shareable investigation view. */
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import { CLASS_META } from "../lib/taxonomy";
import { addFacilityIcons, enhanceBasemap, mapStyleUrl, ring, RINGS_M, withCartoKey } from "./MapCanvas";

export interface CtxEvent { id: string; public_id: string; latitude: number; longitude: number; classification?: string | null; focus?: boolean }
export interface CtxFacility { id: string; name: string | null; facility_type: string; latitude: number; longitude: number }

export function ContextMap({ events, facilities = [], extent, rings, theme, height = 320, label = "Investigation map" }: {
  events: CtxEvent[]; facilities?: CtxFacility[]; extent?: GeoJSON.Geometry | null; rings?: { latitude: number; longitude: number } | null;
  theme: "light" | "dark"; height?: number; label?: string;
}) {
  const el = useRef<HTMLDivElement>(null);
  const key = JSON.stringify([events.map((e) => e.id), facilities.map((f) => f.id), rings, theme]);
  useEffect(() => {
    if (!el.current || (!events.length && !facilities.length)) return;
    const dark = theme === "dark";
    const pts: [number, number][] = [...events.map((e) => [e.longitude, e.latitude] as [number, number]), ...facilities.map((f) => [f.longitude, f.latitude] as [number, number])];
    if (rings) pts.push(...ring(rings.latitude, rings.longitude, RINGS_M[RINGS_M.length - 1]).map((p) => p as [number, number]));
    const lons = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
    const pad = 0.01;
    const map = new maplibregl.Map({
      container: el.current, style: mapStyleUrl(theme), attributionControl: { compact: true },
      bounds: [[Math.min(...lons) - pad, Math.min(...lats) - pad], [Math.max(...lons) + pad, Math.max(...lats) + pad]], fitBoundsOptions: { padding: 28, maxZoom: 14 },
      transformRequest: (url) => ({ url: withCartoKey(url) }), dragRotate: false, pitchWithRotate: false, cooperativeGestures: true,
      // keeps the rendered frame so the map prints (share view / browser print); these maps are small and static
      canvasContextAttributes: { preserveDrawingBuffer: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    map.on("load", () => {
      enhanceBasemap(map, dark);
      addFacilityIcons(map, dark);
      const text = dark ? "#c9ced6" : "#4a505c", halo = dark ? "#16181d" : "#fff";
      if (extent) {
        map.addSource("extent", { type: "geojson", data: { type: "Feature", properties: {}, geometry: extent } });
        map.addLayer({ id: "extent", type: "fill", source: "extent", paint: { "fill-color": "#ff7a2e", "fill-opacity": 0.06 } });
        map.addLayer({ id: "extent-line", type: "line", source: "extent", paint: { "line-color": "#ff7a2e", "line-width": 1, "line-dasharray": [2, 2] } });
      }
      if (rings) {
        map.addSource("rings", { type: "geojson", data: { type: "FeatureCollection", features: RINGS_M.map((r) => ({
          type: "Feature", properties: { label: `${r / 1000} km` }, geometry: { type: "LineString", coordinates: ring(rings.latitude, rings.longitude, r) } })) } });
        map.addLayer({ id: "rings", type: "line", source: "rings", paint: { "line-color": dark ? "#7d8490" : "#868e96", "line-width": 1, "line-dasharray": [4, 3] } });
        map.addLayer({ id: "rings-label", type: "symbol", source: "rings", layout: { "symbol-placement": "line", "text-field": ["get", "label"], "text-size": 10,
          "text-font": ["Open Sans Regular", "Noto Sans Regular"] }, paint: { "text-color": text, "text-halo-color": halo, "text-halo-width": 1.2 } });
      }
      map.addSource("facilities", { type: "geojson", data: { type: "FeatureCollection", features: facilities.map((f) => ({
        type: "Feature", properties: { type: f.facility_type, name: f.name ?? "" }, geometry: { type: "Point", coordinates: [f.longitude, f.latitude] } })) } });
      map.addLayer({ id: "facilities", type: "symbol", source: "facilities", layout: {
        "icon-image": ["coalesce", ["image", ["concat", "fac-", ["get", "type"]]], ["image", "fac-other"]], "icon-size": 1.1, "icon-allow-overlap": true,
        "text-field": ["get", "name"], "text-size": 10, "text-offset": [0, 1.2], "text-anchor": "top", "text-optional": true,
        "text-font": ["Open Sans Regular", "Noto Sans Regular"] }, paint: { "text-color": text, "text-halo-color": halo, "text-halo-width": 1.2 } });
      const colors = Object.fromEntries(Object.entries(CLASS_META).map(([k, v]) => [k, v.color]));
      map.addSource("events", { type: "geojson", data: { type: "FeatureCollection", features: events.map((e) => ({
        type: "Feature", properties: { id: e.public_id, color: colors[e.classification ?? ""] ?? "#9aa1ab", focus: e.focus ? 1 : 0 },
        geometry: { type: "Point", coordinates: [e.longitude, e.latitude] } })) } });
      map.addLayer({ id: "events-halo", type: "circle", source: "events", filter: ["==", ["get", "focus"], 1], paint: {
        "circle-radius": 16, "circle-color": "#ff7a2e", "circle-opacity": 0.28, "circle-blur": 0.8 } });
      map.addLayer({ id: "events", type: "circle", source: "events", paint: {
        "circle-radius": ["case", ["==", ["get", "focus"], 1], 7, 4.5], "circle-color": ["get", "color"], "circle-opacity": 0.9,
        "circle-stroke-color": ["case", ["==", ["get", "focus"], 1], dark ? "#fff" : "#16181d", dark ? "#16181d" : "#fff"],
        "circle-stroke-width": ["case", ["==", ["get", "focus"], 1], 2, 0.8] } });
      map.getContainer().dataset.ready = "1";
    });
    return () => map.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  if (!events.length && !facilities.length) return <div className="faint" style={{ padding: 12 }}>Nothing to map.</div>;
  return <div ref={el} className="ctx-map" style={{ height }} role="region" aria-label={label} />;
}
