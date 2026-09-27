/** Where an event is, as text. Precedence: the geocoded district/state (a real administrative lookup), then the
 *  nearest populated place ("Near Dhanbad, Jharkhand · 1 km": a distance-qualified label, not a boundary), then
 *  nothing. Coordinates are shown alongside by `coordsLabel`. */
export interface Locatable {
  latitude?: number;
  longitude?: number;
  admin_district?: string | null;
  admin_state?: string | null;
  place_name?: string | null;
  place_admin1?: string | null;
  place_country?: string | null;
  place_distance_m?: number | null;
}

export function locationLabel(e: Locatable): string {
  const admin = [e.admin_district, e.admin_state].filter(Boolean).join(", ");
  if (admin) return admin;
  if (!e.place_name) return "";
  const where = [e.place_name, e.place_admin1].filter(Boolean).join(", ");
  const abroad = e.place_country && e.place_country !== "IN" ? ` (${e.place_country})` : "";
  const km = e.place_distance_m == null ? "" : e.place_distance_m < 1000 ? " · < 1 km" : ` · ${Math.round(e.place_distance_m / 1000)} km`;
  return `Near ${where}${abroad}${km}`;
}

export function coordsLabel(e: { latitude?: number; longitude?: number }, digits = 3): string {
  return e.latitude == null || e.longitude == null ? "" : `${e.latitude.toFixed(digits)}, ${e.longitude.toFixed(digits)}`;
}

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

export function relTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const d = now - new Date(iso).getTime();
  const abs = Math.abs(d);
  const suffix = d >= 0 ? "ago" : "from now";
  if (abs < MIN) return "just now";
  if (abs < HOUR) return `${Math.round(abs / MIN)} min ${suffix}`;
  if (abs < DAY) return `${Math.round(abs / HOUR)} h ${suffix}`;
  if (abs < 30 * DAY) return `${Math.round(abs / DAY)} d ${suffix}`;
  return fmtDate(iso);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" })} ${d.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  })} UTC`;
}

export function fmtDistance(m: number | null | undefined): string {
  if (m == null) return "—";
  return m >= 1000 ? `${(m / 1000).toFixed(m >= 10_000 ? 0 : 1)} km` : `${Math.round(m)} m`;
}

export function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function fmtPct(v: number | null | undefined, digits = 0): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function fmtCoord(lat: number, lon: number): string {
  return `${Math.abs(lat).toFixed(4)}°${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(4)}°${lon >= 0 ? "E" : "W"}`;
}

export function fmtDuration(hours: number): string {
  if (hours < 1) return "< 1 h";
  if (hours < 48) return `${Math.round(hours)} h`;
  return `${Math.round(hours / 24)} d`;
}

const POINTS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
export function compass(deg: number | null | undefined): string {
  if (deg == null) return "—";
  return POINTS[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  return n > 1_048_576 ? `${(n / 1_048_576).toFixed(1)} MB` : `${Math.ceil(n / 1024)} KB`;
}

/** A share as a percentage that never hides a small non-zero count as 0% or an incomplete one as 100%. */
export function sharePct(share: number): string {
  const r = Math.round(share * 100);
  if (share > 0 && r === 0) return "<1%";
  if (share < 1 && r === 100) return ">99%";
  return `${r}%`;
}
