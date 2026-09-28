/** Compact facility card for a map click: the facts already in the map layer (no extra request), the relation to the
 *  selected event when there is one, and an explicit way into the facility's detail page (which loads the rest lazily). */
import { ArrowRight, X } from "lucide-react";
import { Link } from "react-router-dom";
import { fmtDistance, fmtNum } from "../lib/format";
import { FACILITY_COLORS, FACILITY_LABELS, SOURCE_NAMES } from "../lib/taxonomy";
import type { EventDetail } from "../lib/types";

/** Properties of a feature from GET /facilities/geojson (MapLibre may hand nulls back as "null"). */
export type FacilityProps = Record<string, unknown>;

const val = (x: unknown): string | null => (x === null || x === undefined || x === "null" || x === "" ? null : String(x));

export function haversineM(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const r = (d: number) => (d * Math.PI) / 180;
  const a = Math.sin(r(lat2 - lat1) / 2) ** 2 + Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(r(lon2 - lon1) / 2) ** 2;
  return 2 * 6_371_008.8 * Math.asin(Math.sqrt(a));
}

export function FacilityCard({ p, lngLat, focus, onClose, variant }: {
  p: FacilityProps; lngLat: [number, number]; focus: EventDetail | null; onClose: () => void; variant: "popup" | "sheet";
}) {
  const id = val(p.id)!;
  const type = val(p.type) ?? "other";
  const name = val(p.name) ?? "Unnamed facility";
  const subtype = val(p.subtype), status = val(p.status), operator = val(p.operator);
  const capacity = val(p.capacity), unit = val(p.capacity_unit) ?? "MW";
  const registry = val(p.registry), station = val(p.registry_station);
  const locSource = val(p.coordinate_source) ?? val(p.source);
  const sources = Number(val(p.sources) ?? 1);
  const confidence = val(p.confidence);
  const link = focus?.facilities.find((f) => f.id === id);
  const distance = focus ? (link?.distance_m ?? haversineM(focus.latitude, focus.longitude, lngLat[1], lngLat[0])) : null;
  const to = `/facilities/${id}${focus ? `?event=${encodeURIComponent(focus.public_id)}` : ""}`;
  return (
    <div className={`fac-card fac-card--${variant}`} role="dialog" aria-label={`Facility: ${name}`} data-testid="facility-card">
      <div className="fc-head">
        <span className="fc-swatch" style={{ background: FACILITY_COLORS[type] ?? "#868e96" }} aria-hidden />
        <b className="fc-name">{name}</b>
        <button className="btn ghost icon sm" onClick={onClose} aria-label="Close facility card"><X size={14} /></button>
      </div>
      <div className="fc-sub">
        {[FACILITY_LABELS[type] ?? type, subtype, status].filter(Boolean).join(" · ")}
      </div>
      <dl className="fc-kv">
        {operator && <><dt>Operator</dt><dd>{operator}</dd></>}
        {capacity && <><dt>Capacity</dt><dd className="num">{fmtNum(Number(capacity), 0)} {unit}</dd></>}
        {registry && <><dt>Registry</dt><dd>{registry.toUpperCase()}{station ? ` (${station})` : ""}</dd></>}
        <dt>Location</dt>
        <dd>{SOURCE_NAMES[locSource ?? ""] ?? locSource ?? "—"} · {sources} source{sources === 1 ? "" : "s"}{confidence ? ` · confidence ${Number(confidence).toFixed(2)}` : ""}</dd>
        {focus && distance != null && (
          <>
            <dt>From {focus.public_id}</dt>
            <dd className="num">{fmtDistance(distance)}{link ? ` · attribution candidate #${link.rank}, score ${link.attribution_score.toFixed(2)}` : " · not attributed"}</dd>
          </>
        )}
      </dl>
      <div className="fc-note">Sources agreeing on a location is not certainty about activity; attribution is supporting evidence, not proof.</div>
      <div className="fc-actions">
        <Link className="btn sm primary fc-open" to={to} data-testid="facility-open">View facility details <ArrowRight size={13} /></Link>
        <Link className="btn sm fc-open" to={`${to}${to.includes("?") ? "&" : "?"}view=satellite`} data-testid="facility-satellite">Satellite view</Link>
      </div>
    </div>
  );
}
