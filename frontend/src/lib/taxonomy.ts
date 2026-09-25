/** Product language shared by desktop and mobile: labels, colours, descriptions. */
import type { DisplayState, PersistenceClass, SourceClass } from "./types";

export const CLASS_META: Record<SourceClass, { label: string; short: string; color: string; hint: string }> = {
  flare: { label: "Gas flare", short: "Flare", color: "#f76707", hint: "Persistent combustion at oil & gas infrastructure" },
  process_heat: { label: "Industrial process heat", short: "Process heat", color: "#9c36b5", hint: "Furnaces, kilns, stacks at an industrial site" },
  coal_seam_fire: { label: "Coal-seam / mine fire", short: "Coal fire", color: "#8d5524", hint: "Recurring fire at mining areas" },
  agricultural_burn: { label: "Agricultural burn", short: "Agri burn", color: "#e0a100", hint: "Crop-residue burning on cropland" },
  wildfire: { label: "Wildfire / vegetation", short: "Wildfire", color: "#c92a2a", hint: "Fire in forest or scrub" },
  industrial_fire: { label: "Industrial fire (possible)", short: "Ind. fire", color: "#e64980", hint: "Transient intense heat at a facility — review" },
  other: { label: "Other thermal source", short: "Other", color: "#5c6470", hint: "Discriminating context absent" },
  unknown: { label: "Unknown", short: "Unknown", color: "#9aa1ab", hint: "Insufficient signal to classify" },
};
export const CLASS_ORDER = Object.keys(CLASS_META) as SourceClass[];

export const PERSISTENCE_META: Record<PersistenceClass, { label: string; hint: string }> = {
  transient: { label: "Transient", hint: "Single-day or short-lived" },
  recurring: { label: "Recurring", hint: "Repeated on several days or at a repeat site" },
  persistent: { label: "Persistent", hint: "Active on most days across the observed span" },
};

export type Tone = "confirmed" | "high" | "moderate" | "low" | "insufficient" | "review" | "rejected";
export const STATE_META: Record<DisplayState, { label: string; tone: Tone; hint: string }> = {
  CONFIRMED: { label: "Confirmed", tone: "confirmed", hint: "Multi-source corroboration incl. imagery analysis" },
  HIGH_CONFIDENCE: { label: "High confidence", tone: "high", hint: "Strong, consistent evidence — not independently verified" },
  MODERATE_CONFIDENCE: { label: "Moderate confidence", tone: "moderate", hint: "Evidence supports the label with gaps" },
  LOW_CONFIDENCE: { label: "Low confidence", tone: "low", hint: "Weak or conflicting evidence" },
  INSUFFICIENT_EVIDENCE: { label: "Insufficient evidence", tone: "insufficient", hint: "Manual review required" },
  UNDER_REVIEW: { label: "Under review", tone: "review", hint: "An analyst is investigating" },
  ANALYST_CONFIRMED: { label: "Analyst confirmed", tone: "confirmed", hint: "Confirmed by an analyst" },
  ANALYST_REJECTED: { label: "Analyst rejected", tone: "rejected", hint: "Rejected or marked false positive" },
};

export const FACILITY_LABELS: Record<string, string> = {
  refinery: "Refinery", oil_gas: "Oil & gas", flare_site: "Flare stack", power_plant_coal: "Coal power plant",
  power_plant_gas: "Gas/oil power plant", power_plant_other: "Power plant (other/unknown fuel)", steel_plant: "Steel plant",
  cement_plant: "Cement plant", chemical_plant: "Chemical plant", mine: "Mine / quarry", coal_mine: "Coal mine",
  landfill: "Landfill", factory: "Factory", industrial_area: "Industrial area", rail: "Rail", other: "Other",
};
export const FACILITY_COLORS: Record<string, string> = {
  refinery: "#d9480f", oil_gas: "#d9480f", flare_site: "#d9480f", power_plant_coal: "#343a40", power_plant_gas: "#495057",
  power_plant_other: "#868e96", steel_plant: "#1c7ed6", cement_plant: "#1971c2", chemical_plant: "#1864ab",
  mine: "#795548", coal_mine: "#5d4037", landfill: "#66a80f", factory: "#4263eb", industrial_area: "#748ffc",
};

export const SOURCE_NAMES: Record<string, string> = {
  firms: "NASA FIRMS", osm: "OpenStreetMap", gem: "Global Energy Monitor", cea: "CEA (India)",
  wri_gppd: "WRI Global Power Plant DB", earth_search: "Sentinel-2 (Earth Search)", cdse: "Copernicus Data Space",
  open_meteo: "Open-Meteo", nominatim: "OSM Nominatim", demo: "Synthetic demo data",
};

export const FEATURE_LABELS: Record<string, string> = {
  frp_max_log: "Peak FRP", frp_mean_log: "Mean FRP", frp_cv: "FRP variability", brightness_mean: "Brightness temp.",
  brightness_delta: "MIR−TIR contrast", confidence_mean: "Detection confidence", night_fraction: "Night share",
  pixel_area_km2: "Pixel footprint", observation_count_log: "Detections", active_days: "Active days", span_days: "Span (days)",
  observation_frequency: "Observation frequency", sensor_count: "Platforms", persistence_score: "Persistence score",
  recurrence_count: "Repeat-site count", spatial_spread_km: "Spatial spread", dist_oil_gas_km: "Dist. to oil/gas",
  dist_heavy_industry_km: "Dist. to heavy industry", dist_mine_km: "Dist. to mine", facility_count_5km: "Facilities ≤5 km",
  land_cropland: "Cropland nearby", land_forest: "Forest/scrub nearby", land_residential: "Residential nearby",
  wind_speed_ms: "Wind speed", month_sin: "Season (sin)", month_cos: "Season (cos)",
};

export const FP_REASONS: Record<string, string> = {
  industrial_process_heat: "Known industrial process heat", agricultural_burn: "Agricultural burn", sensor_artifact: "Sensor artefact",
  construction: "Construction activity", known_static_source: "Known static source", sun_glint_or_reflection: "Sun glint / reflection",
  other: "Other",
};

export const KNOWLEDGE_LABELS: Record<string, string> = {
  observed: "Observed", derived: "Derived", external: "External context", model: "Model output",
};
