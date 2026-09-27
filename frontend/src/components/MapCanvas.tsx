import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, LngLatBoundsLike, Map as MLMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre >= 5 runs tile processing in a module worker. Let Vite bundle it (ES format, see
// vite.config.ts) and hand MapLibre the emitted URL; otherwise production builds reference a
// worker file that is never emitted.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import type { EventFilters } from "../lib/hooks";
import { CLASS_META, FACILITY_COLORS } from "../lib/taxonomy";
import { FacilityCard, type FacilityProps } from "./FacilityCard";
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
export const RINGS_M = [2000, 10000];

maplibregl.setWorkerUrl(maplibreWorkerUrl);

/** Island groups, labelled beside the islands (label placement only; the islands themselves come from the boundary). */
const ISLAND_GROUPS: GeoJSON.Feature[] = [
  { type: "Feature", properties: { name: "Lakshadweep", anchor: "right", offset: [-0.6, 0] }, geometry: { type: "Point", coordinates: [71.6, 10.6] } },
  { type: "Feature", properties: { name: "Andaman & Nicobar", anchor: "left", offset: [0.8, 0] }, geometry: { type: "Point", coordinates: [93.9, 10.2] } },
];

/** A point at the centre of every polygon of the boundary smaller than ~25 km: islets that would otherwise vanish. */
export function isletPoints(geo: GeoJSON.Feature | GeoJSON.FeatureCollection): GeoJSON.FeatureCollection {
  const out: GeoJSON.Feature[] = [];
  for (const f of geo.type === "FeatureCollection" ? geo.features : [geo]) {
    const g = f.geometry;
    const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
    for (const p of polys) {
      let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
      for (const [x, y] of p[0]) { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y); }
      if (e - w < 0.25 && n - s < 0.25) out.push({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [(w + e) / 2, (s + n) / 2] } });
    }
  }
  return { type: "FeatureCollection", features: out };
}

const STYLE_LIGHT = (import.meta.env.VITE_MAP_STYLE_LIGHT as string) || "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const CARTO_KEY = (import.meta.env.VITE_CARTO_API_KEY as string | undefined) ?? "";

/** CARTO basemaps take the API key as a `key` query parameter. The style JSON does not forward it to the
 *  tiles, sprites and glyphs it references, so it is added to every request to a CARTO host. */
export function withCartoKey(url: string, key: string = CARTO_KEY): string {
  if (!key) return url;
  let u: URL;
  try { u = new URL(url); } catch { return url; }
  if (!/(^|\.)basemaps\.cartocdn\.com$/.test(u.hostname) || u.searchParams.has("key")) return url;
  u.searchParams.set("key", key);
  return u.toString();
}

const STYLE_DARK = (import.meta.env.VITE_MAP_STYLE_DARK as string) || "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
export const mapStyleUrl = (theme: "light" | "dark") => (theme === "dark" ? STYLE_DARK : STYLE_LIGHT);
const INDIA: LngLatBoundsLike = [[68.1, 6.7], [97.4, 37.1]]; // replaced by the loaded boundary's extent

interface IndiaBoundary {
  india: GeoJSON.Feature;
  mask: GeoJSON.Feature;
  states: GeoJSON.FeatureCollection;
  bbox: [number, number, number, number];
}
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

const classColorExpr: maplibregl.ExpressionSpecification = [
  "match", ["get", "classification"],
  ...Object.entries(CLASS_META).flatMap(([k, v]) => [k, v.color]),
  "#9aa1ab",
] as unknown as maplibregl.ExpressionSpecification;

/** India-wide context from the basemap's own vector tiles (CARTO streets, OpenMapTiles schema; global OSM data).
 *  The stock dark style hides roads below z10 (#1a1a1a on near-black) and has no district layer (India's districts
 *  are admin_level 5). These layers add a zoom-dependent hierarchy: national roads first, then primary and
 *  secondary roads, districts, industrial areas and quarries, without inventing any feature. */
export function enhanceBasemap(map: MLMap, dark: boolean) {
  if (!map.getSource("carto")) return; // a custom style without the CARTO source: leave it as it is
  const before = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
  const road = dark ? "#6f6a63" : "#c8b8a4";
  const add = (layer: maplibregl.LayerSpecification) => { if (!map.getLayer(layer.id)) map.addLayer(layer, before); };
  add({ id: "tt-landuse-industrial", type: "fill", source: "carto", "source-layer": "landuse", minzoom: 9,
    filter: ["in", ["get", "class"], ["literal", ["industrial", "quarry"]]],
    paint: { "fill-color": dark ? "#8a5a2b" : "#e0b27a", "fill-opacity": ["interpolate", ["linear"], ["zoom"], 9, 0.12, 13, 0.2] } });
  add({ id: "tt-districts", type: "line", source: "carto", "source-layer": "boundary", minzoom: 8.5,
    filter: ["all", ["==", ["get", "admin_level"], 5], ["==", ["get", "maritime"], 0]],
    paint: { "line-color": dark ? "#8b93a1" : "#9aa1ab", "line-dasharray": [3, 2], "line-opacity": ["interpolate", ["linear"], ["zoom"], 8.5, 0.25, 11, 0.5],
             "line-width": ["interpolate", ["linear"], ["zoom"], 8.5, 0.5, 12, 1] } });
  add({ id: "tt-roads-secondary", type: "line", source: "carto", "source-layer": "transportation", minzoom: 9.5, maxzoom: 13,
    filter: ["in", ["get", "class"], ["literal", ["secondary", "tertiary"]]], layout: { "line-cap": "round" },
    paint: { "line-color": road, "line-opacity": 0.45, "line-width": ["interpolate", ["linear"], ["zoom"], 9.5, 0.4, 13, 1.2] } });
  add({ id: "tt-roads-primary", type: "line", source: "carto", "source-layer": "transportation", minzoom: 7, maxzoom: 11,
    filter: ["==", ["get", "class"], "primary"], layout: { "line-cap": "round" },
    paint: { "line-color": road, "line-opacity": ["interpolate", ["linear"], ["zoom"], 7, 0.35, 10, 0.6], "line-width": ["interpolate", ["linear"], ["zoom"], 7, 0.4, 11, 1.4] } });
  add({ id: "tt-roads-major", type: "line", source: "carto", "source-layer": "transportation", minzoom: 4.5, maxzoom: 11,
    filter: ["in", ["get", "class"], ["literal", ["motorway", "trunk"]]], layout: { "line-cap": "round" },
    paint: { "line-color": dark ? "#8a7a66" : "#d4a373", "line-opacity": ["interpolate", ["linear"], ["zoom"], 4.5, 0.4, 9, 0.75],
             "line-width": ["interpolate", ["linear"], ["zoom"], 4.5, 0.5, 8, 1, 11, 2] } });
  // labels: states and major cities earlier, road names once roads are legible
  const range = (id: string, min: number, max: number) => map.getLayer(id) && map.setLayerZoomRange(id, min, max);
  range("place_state", 4.5, 10);
  range("place_city_r5", 6.5, 15);
  range("roadname_major", 10, 24);
  range("roadname_pri", 12, 24);
  if (dark) {
    for (const id of ["roadname_major", "roadname_pri", "roadname_sec", "roadname_minor"]) if (map.getLayer(id)) map.setPaintProperty(id, "text-color", "#8d939c");
    if (map.getLayer("place_state")) map.setPaintProperty("place_state", "text-color", "rgba(203, 214, 222, 0.7)");
    if (map.getLayer("waterway")) map.setPaintProperty("waterway", "line-color", "#2e4a60");
  }
}

/** Facilities are squares (thermal events are circles): one icon per facility type, drawn once per style. */
export function addFacilityIcons(map: MLMap, dark: boolean) {
  const px = 2, size = 12 * px;
  for (const [type, color] of [...Object.entries(FACILITY_COLORS), ["other", "#868e96"]] as [string, string][]) {
    const id = `fac-${type}`;
    if (map.hasImage(id)) continue;
    const c = document.createElement("canvas");
    c.width = c.height = size;
    const g = c.getContext("2d");
    if (!g) return; // no canvas (tests): facilities are simply not drawn, the map still works
    g.fillStyle = dark ? "#0b0c0f" : "#ffffff";
    g.beginPath(); g.roundRect(1, 1, size - 2, size - 2, 3 * px); g.fill();
    g.fillStyle = color;
    g.beginPath(); g.roundRect(3 * px, 3 * px, size - 6 * px, size - 6 * px, 1.5 * px); g.fill();
    map.addImage(id, g.getImageData(0, 0, size, size), { pixelRatio: px });
  }
}

function destination(lat: number, lon: number, bearing: number, meters: number): [number, number] {
  const R = 6_371_008.8, d = meters / R, b = (bearing * Math.PI) / 180, p1 = (lat * Math.PI) / 180, l1 = (lon * Math.PI) / 180;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [(l2 * 180) / Math.PI, (p2 * 180) / Math.PI];
}

export function ring(lat: number, lon: number, meters: number): GeoJSON.Position[] {
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
  const lastFocus = useRef<string | null>(null);
  const keepView = useRef(false); // set by a deep link, an event focus or the user moving the map
  const cbs = useRef({ onSelect, onViewport });
  cbs.current = { onSelect, onViewport };
  // Facility card: a MapLibre popup on wide maps, a bottom sheet on narrow ones (phones), both rendered by React.
  const [pick, setPick] = useState<{ p: FacilityProps; lngLat: [number, number]; sheet: boolean } | null>(null);
  const popupNode = useRef<HTMLDivElement | null>(null);
  if (!popupNode.current && typeof document !== "undefined") popupNode.current = document.createElement("div");

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
      transformRequest: (url) => ({ url: withCartoKey(url) }),
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    map.on("movestart", (e) => { if ((e as { originalEvent?: unknown }).originalEvent) keepView.current = true; });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    map.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: false }, trackUserLocation: false }), "bottom-right");
    map.on("load", () => {
      // India first: the basemap stays visible around India but is subdued (a translucent veil outside the boundary),
      // India gets a faint warm fill, its state lines and a restrained amber border. Boundary: Natural Earth, India
      // point of view, loaded from the backend (which uses the same geometry for spatial filtering).
      const dark = theme === "dark";
      enhanceBasemap(map, dark);
      addFacilityIcons(map, dark);
      map.addSource("india-mask", { type: "geojson", data: EMPTY });
      map.addSource("india", { type: "geojson", data: EMPTY, attribution: "Boundary: Natural Earth (India point of view)" });
      map.addSource("india-states", { type: "geojson", data: EMPTY });
      map.addLayer({ id: "india-mask", type: "fill", source: "india-mask",
        paint: { "fill-color": dark ? "#07080a" : "#f1f3f5", "fill-opacity": dark ? 0.55 : 0.6 } });
      map.addLayer({ id: "india-fill", type: "fill", source: "india",
        paint: { "fill-color": "#ff8a3d", "fill-opacity": dark ? 0.035 : 0.03 } });
      map.addLayer({ id: "india-states", type: "line", source: "india-states",
        paint: { "line-color": dark ? "#9aa3b2" : "#868e96", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.4, 8, 0.9],
                 "line-opacity": dark ? 0.32 : 0.45 } });
      map.addLayer({ id: "india-glow", type: "line", source: "india",
        paint: { "line-color": "#ff8a3d", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 4, 8, 7], "line-blur": 4,
                 "line-opacity": dark ? 0.2 : 0.12 } });
      map.addLayer({ id: "india-outline", type: "line", source: "india",
        paint: { "line-color": dark ? "#f0a24a" : "#d9480f", "line-opacity": 0.9,
                 "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.9, 8, 1.5] } });
      // Islands too small to see at country zoom (Lakshadweep's islets are a few km across): a dot on each small
      // polygon of the boundary itself, and a quiet label per island group. Hidden once the outlines are legible.
      map.addSource("india-islets", { type: "geojson", data: EMPTY });
      map.addLayer({ id: "india-islets", type: "circle", source: "india-islets", maxzoom: 7, paint: {
        "circle-color": dark ? "#f0a24a" : "#d9480f", "circle-opacity": 0.85,
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 1.4, 7, 2.2] } });
      map.addSource("india-island-labels", { type: "geojson", data: { type: "FeatureCollection", features: ISLAND_GROUPS } });
      map.addLayer({ id: "india-island-labels", type: "symbol", source: "india-island-labels", minzoom: 3.2, maxzoom: 8,
        layout: { "text-field": ["get", "name"], "text-font": ["Open Sans Semibold", "Noto Sans Regular"], "text-size": 9.5,
                  "text-letter-spacing": 0.12, "text-transform": "uppercase", "text-max-width": 8,
                  "text-anchor": ["get", "anchor"], "text-offset": ["get", "offset"] },
        paint: { "text-color": dark ? "#c9a27a" : "#8a4a1c", "text-opacity": 0.75,
                 "text-halo-color": dark ? "#0b0c0f" : "#ffffff", "text-halo-width": 1 } });
      // Country names from the basemap: understated, never competing with anomalies.
      for (const l of map.getStyle().layers) {
        if (l.type === "symbol" && /country/i.test(l.id)) {
          map.setPaintProperty(l.id, "text-opacity", 0.55);
          map.setLayoutProperty(l.id, "text-letter-spacing", 0.2);
        }
      }
      api<IndiaBoundary>("/public/boundary", { query: { detail: "map" } }).then((b) => {
        if (!map.getSource("india")) return;
        (map.getSource("india") as GeoJSONSource).setData(b.india);
        (map.getSource("india-mask") as GeoJSONSource).setData(b.mask);
        (map.getSource("india-states") as GeoJSONSource).setData(b.states);
        (map.getSource("india-islets") as GeoJSONSource).setData(isletPoints(b.india));
        // fit India only on a fresh map nobody has moved yet (a deep link to an event or a place flies there first)
        if (!prev && !keepView.current) map.fitBounds([[b.bbox[0], b.bbox[1]], [b.bbox[2], b.bbox[3]]], { padding: { top: 30, bottom: 18, left: 20, right: 44 }, duration: 0 });
        map.getContainer().dataset.india = "loaded";
      }).catch(() => { map.getContainer().dataset.india = "unavailable"; }); // the map still works without it

      map.addSource("imagery", { type: "raster", tileSize: 256, maxzoom: 15,
        tiles: ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/g/{z}/{y}/{x}.jpg"],
        attribution: "Sentinel-2 cloudless 2021 by EOX IT Services (Contains modified Copernicus Sentinel data 2021)" });
      map.addLayer({ id: "imagery", type: "raster", source: "imagery", layout: { visibility: "none" } }, map.getStyle().layers.find((l) => l.type === "symbol")?.id);

      map.addSource("events", { type: "geojson", data: EMPTY, cluster: true, clusterRadius: 34, clusterMaxZoom: 8,
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
      map.addLayer({ id: "fac-linked", type: "circle", source: "facilities", minzoom: 6, filter: ["in", ["get", "id"], ["literal", []]], paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 7, 12, 11], "circle-color": "rgba(90,162,240,0.12)",
        "circle-stroke-color": dark ? "#5aa2f0" : "#1c6fd1", "circle-stroke-width": 1.6 } });
      map.addLayer({ id: "fac", type: "symbol", source: "facilities", minzoom: 6, layout: {
        "icon-image": ["coalesce", ["image", ["concat", "fac-", ["get", "type"]]], ["image", "fac-other"]],
        "icon-size": ["interpolate", ["linear"], ["zoom"], 6, 0.6, 10, 0.9, 14, 1.15],
        "icon-allow-overlap": true, "icon-ignore-placement": true },
        paint: { "icon-opacity": 0.95 } });
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

      // Clusters: a soft thermal halo and a small dark disc with a thin amber ring; size grows gently with the count.
      const clusterR: maplibregl.ExpressionSpecification = ["step", ["get", "point_count"], 8, 10, 10, 50, 12, 200, 14.5, 1000, 17];
      map.addLayer({ id: "clusters-halo", type: "circle", source: "events", filter: ["has", "point_count"], paint: {
        "circle-color": "#ff7a2e", "circle-radius": ["*", clusterR, 1.9], "circle-blur": 1,
        "circle-opacity": ["interpolate", ["linear"], ["get", "point_count"], 2, 0.18, 500, 0.38] } });
      map.addLayer({ id: "clusters", type: "circle", source: "events", filter: ["has", "point_count"], paint: {
        "circle-color": dark ? "rgba(18,19,23,0.88)" : "rgba(255,255,255,0.92)", "circle-stroke-color": dark ? "#f0a24a" : "#e8590c",
        "circle-stroke-width": 1, "circle-stroke-opacity": 0.9, "circle-radius": clusterR } });
      map.addLayer({ id: "cluster-count", type: "symbol", source: "events", filter: ["has", "point_count"],
        layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": ["step", ["get", "point_count"], 9.5, 100, 10.5],
                  "text-font": ["Open Sans Semibold", "Noto Sans Regular"], "text-allow-overlap": true },
        paint: { "text-color": dark ? "#ffd9ad" : "#8a2c05" } });
      map.addLayer({ id: "ev", type: "circle", source: "events", filter: ["!", ["has", "point_count"]], paint: {
        "circle-radius": ["interpolate", ["linear"], ["get", "frp"], 0, 3.5, 20, 5, 100, 7, 500, 10],
        "circle-color": classColorExpr,
        "circle-opacity": ["case", ["==", ["get", "status"], "dormant"], 0.45, 0.9],
        "circle-stroke-width": 0.8,
        "circle-stroke-color": ["match", ["get", "state"], ["INSUFFICIENT_EVIDENCE"], "#9aa1ab", ["ANALYST_CONFIRMED", "CONFIRMED"], "#2b8a3e", ["ANALYST_REJECTED"], "#c92a2a", dark ? "#16181d" : "#ffffff"] } });
      map.addLayer({ id: "ev-selected-halo", type: "circle", source: "events", filter: ["==", ["get", "id"], ""], paint: {
        "circle-radius": 22, "circle-color": "#ff7a2e", "circle-opacity": 0.28, "circle-blur": 0.8 } }, "ev");
      map.addLayer({ id: "ev-selected", type: "circle", source: "events", filter: ["==", ["get", "id"], ""], paint: {
        "circle-radius": 14, "circle-color": "transparent", "circle-stroke-color": dark ? "#fff" : "#16181d", "circle-stroke-width": 2.5 } });

      map.on("click", "clusters", async (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const zoom = await (map.getSource("events") as GeoJSONSource).getClusterExpansionZoom(f.properties.cluster_id);
        // at least one visible step in: at fractional zooms the expansion zoom can be only a hair above the current one
        map.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom: Math.max(zoom, map.getZoom() + 1) });
      });
      map.on("click", "ev", (e) => {
        const id = e.features?.[0]?.properties?.id;
        if (id) cbs.current.onSelect(id);
      });
      map.on("click", "fac", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const [lon, lat] = (f.geometry as GeoJSON.Point).coordinates;
        setPick({ p: f.properties as FacilityProps, lngLat: [lon, lat], sheet: map.getContainer().clientWidth < 560 });
      });
      for (const l of ["ev", "clusters", "fac"]) {
        map.on("mouseenter", l, () => (map.getCanvas().style.cursor = "pointer"));
        map.on("mouseleave", l, () => (map.getCanvas().style.cursor = ""));
      }
      setReady((n) => n + 1);
    });
    mapRef.current = map;
    setPick(null);
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
    ["clusters-halo", "clusters", "cluster-count", "ev", "ev-selected", "ev-selected-halo"].forEach((l) => vis(l, layers.events && !layers.heat));
    vis("heat", layers.heat);
    ["fac", "fac-label", "fac-linked"].forEach((l) => vis(l, layers.facilities));
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
    map.setFilter("ev-selected-halo", ["==", ["get", "id"], selectedId ?? ""]);
    const cur = focus && focus.id === selectedId ? focus : null;
    // facilities the selected event was attributed against (search radius), ringed on the map
    map.setFilter("fac-linked", ["in", ["get", "id"], ["literal", cur ? cur.facilities.map((f) => f.id) : []]]);
    const g = focusGeo(cur);
    const dets = replayUntil
      ? { ...g.dets, features: g.dets.features.filter((f) => (f.properties as { t: string }).t <= replayUntil) }
      : g.dets;
    (map.getSource("focus-dets") as GeoJSONSource).setData(dets);
    (map.getSource("focus-footprint") as GeoJSONSource).setData(g.footprint);
    (map.getSource("focus-arrow") as GeoJSONSource).setData(g.arrow);
    (map.getSource("focus-links") as GeoJSONSource).setData(g.links);
    (map.getSource("focus-rings") as GeoJSONSource).setData(g.rings);
  }, [ready, selectedId, focus, replayUntil]);

  // --- facility card ------------------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !pick || pick.sheet || !popupNode.current) return;
    const popup = new maplibregl.Popup({ closeButton: false, maxWidth: "320px", offset: 10, className: "tt-popup", focusAfterOpen: false })
      .setLngLat(pick.lngLat).setDOMContent(popupNode.current).addTo(map);
    const onClose = () => setPick(null);
    popup.on("close", onClose);
    return () => { popup.off("close", onClose); popup.remove(); };
  }, [pick]);
  useEffect(() => {
    if (!pick) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setPick(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pick]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !focus || focus.id !== selectedId || lastFocus.current === focus.id) return;
    lastFocus.current = focus.id;
    keepView.current = true;
    if (map.getZoom() < 10 || !map.getBounds().contains([focus.longitude, focus.latitude])) {
      map.flyTo({ center: [focus.longitude, focus.latitude], zoom: Math.max(map.getZoom(), 11.5), speed: 1.6 });
    }
  }, [ready, focus, selectedId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !flyTo) return;
    keepView.current = true;
    map.flyTo({ center: [flyTo.lon, flyTo.lat], zoom: flyTo.zoom ?? 10 });
  }, [ready, flyTo]);

  const card = pick && (
    <FacilityCard p={pick.p} lngLat={pick.lngLat} focus={focus && focus.id === selectedId ? focus : null}
      onClose={() => setPick(null)} variant={pick.sheet ? "sheet" : "popup"} />
  );
  return (
    <>
      <div ref={el} className="map" role="region" aria-label="Thermal events map" />
      {card && (pick!.sheet
        // phones: a bottom sheet above every panel and the tab bar (event panels also sit at the bottom of the map)
        ? createPortal(<div className="fac-sheet" style={{ bottom: (document.querySelector(".m-nav")?.getBoundingClientRect().height ?? 0) + 8 }}>{card}</div>, document.body)
        : popupNode.current && createPortal(card, popupNode.current))}
    </>
  );
}
