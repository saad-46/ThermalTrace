/** Map context for one facility: its location, the selected event (if any), the distance between them and the rule
 *  (2 km) and search (10 km) radii around the event, or around the facility when no event is selected. */
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import { fmtDistance } from "../lib/format";
import { addFacilityIcons, enhanceBasemap, mapStyleUrl, ring, RINGS_M, withCartoKey } from "./MapCanvas";

export function FacilityContextMap({ facility, event, distanceM, theme }: {
  facility: { latitude: number; longitude: number; facility_type: string; name: string | null };
  event?: { latitude: number; longitude: number; public_id: string } | null;
  distanceM?: number | null;
  theme: "light" | "dark";
}) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current) return;
    const dark = theme === "dark";
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
      if (event) {
        map.addSource("link", { type: "geojson", data: { type: "Feature", properties: { d: distanceM != null ? fmtDistance(distanceM) : "" },
          geometry: { type: "LineString", coordinates: [[event.longitude, event.latitude], [facility.longitude, facility.latitude]] } } });
        map.addLayer({ id: "link", type: "line", source: "link", paint: { "line-color": dark ? "#5aa2f0" : "#1c6fd1", "line-width": 1.4, "line-dasharray": [1, 2] } });
        map.addLayer({ id: "link-label", type: "symbol", source: "link", layout: { "symbol-placement": "line-center", "text-field": ["get", "d"], "text-size": 11,
          "text-font": ["Open Sans Semibold", "Noto Sans Regular"] }, paint: { "text-color": labelColor, "text-halo-color": halo, "text-halo-width": 1.4 } });
        map.addSource("event", { type: "geojson", data: { type: "Feature", properties: { label: event.public_id }, geometry: { type: "Point", coordinates: [event.longitude, event.latitude] } } });
        map.addLayer({ id: "event-halo", type: "circle", source: "event", paint: { "circle-radius": 16, "circle-color": "#ff7a2e", "circle-opacity": 0.28, "circle-blur": 0.8 } });
        map.addLayer({ id: "event", type: "circle", source: "event", paint: { "circle-radius": 6, "circle-color": "#ff7a2e", "circle-stroke-color": dark ? "#fff" : "#16181d", "circle-stroke-width": 2 } });
        map.addLayer({ id: "event-label", type: "symbol", source: "event", layout: { "text-field": ["get", "label"], "text-size": 10.5, "text-offset": [0, 1.4], "text-anchor": "top",
          "text-font": ["Open Sans Semibold", "Noto Sans Regular"] }, paint: { "text-color": labelColor, "text-halo-color": halo, "text-halo-width": 1.2 } });
      }
      map.addSource("facility", { type: "geojson", data: { type: "Feature", properties: { type: facility.facility_type, label: facility.name ?? "" },
        geometry: { type: "Point", coordinates: [facility.longitude, facility.latitude] } } });
      map.addLayer({ id: "facility", type: "symbol", source: "facility", layout: {
        "icon-image": ["coalesce", ["image", ["concat", "fac-", ["get", "type"]]], ["image", "fac-other"]], "icon-size": 1.3, "icon-allow-overlap": true,
        "text-field": ["get", "label"], "text-size": 11, "text-offset": [0, 1.2], "text-anchor": "top", "text-optional": true,
        "text-font": ["Open Sans Semibold", "Noto Sans Regular"] }, paint: { "text-color": labelColor, "text-halo-color": halo, "text-halo-width": 1.2 } });
      map.getContainer().dataset.ready = "1";
    });
    return () => map.remove();
  }, [facility, event, distanceM, theme]);
  return <div ref={el} className="fac-context-map" role="region" aria-label="Facility location map" data-testid="facility-map" />;
}
