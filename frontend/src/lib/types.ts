/** Shared domain types — mirror backend/app/schemas/api.py. */

export type Role = "viewer" | "analyst" | "supervisor" | "admin";
export type SourceClass =
  | "flare" | "process_heat" | "coal_seam_fire" | "agricultural_burn" | "wildfire" | "industrial_fire" | "other" | "unknown";
export type PersistenceClass = "transient" | "recurring" | "persistent";
export type DisplayState =
  | "CONFIRMED" | "HIGH_CONFIDENCE" | "MODERATE_CONFIDENCE" | "LOW_CONFIDENCE" | "INSUFFICIENT_EVIDENCE"
  | "UNDER_REVIEW" | "ANALYST_CONFIRMED" | "ANALYST_REJECTED";
export type DataMode = "live" | "historical" | "demo";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  /** Read-only guided exploration session ("Explore as Analyst / Admin"). */
  is_demo?: boolean;
  created_at: string;
  last_login_at: string | null;
}

export type DemoRole = "analyst" | "admin";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface EventSummary {
  id: string;
  public_id: string;
  latitude: number;
  longitude: number;
  data_mode: DataMode;
  first_detected: string;
  last_detected: string;
  observation_count: number;
  sensor_count: number;
  sensors: string[];
  days_active: number;
  duration_hours: number;
  frp_max: number | null;
  frp_mean: number | null;
  night_fraction: number | null;
  status: "active" | "dormant" | "closed";
  review_status: string;
  persistence_class: PersistenceClass | null;
  persistence_score: number | null;
  classification: SourceClass | null;
  classification_probability: number | null;
  confidence_score: number | null;
  confidence_state: DisplayState | null;
  display_state: DisplayState;
  data_quality: "excellent" | "good" | "limited" | "poor" | null;
  nearest_facility_distance_m: number | null;
  nearest_facility_name: string | null;
  nearest_facility_type: string | null;
  admin_state: string | null;
  admin_district: string | null;
  country: string | null;
  place_name?: string | null;
  place_admin1?: string | null;
  place_country?: string | null;
  place_distance_m?: number | null;
  assigned_to: string | null;
  priority_score: number | null;
}

export interface PriorityComponent {
  name: "thermal_intensity" | "persistence" | "industrial_proximity" | "classification_confidence" | "sensor_corroboration";
  points: number;
  max: number;
  detail: string;
}
export interface PriorityBreakdown {
  score: number;
  tier: "high" | "elevated" | "routine" | "low";
  components: PriorityComponent[];
  note: string;
}

export interface SearchResults {
  query: string;
  coordinates: { latitude: number; longitude: number } | null;
  events: { id: string; public_id: string; classification: SourceClass | null; confidence_state: DisplayState | null; review_status: string; admin_district: string | null; admin_state: string | null; distance_m: number | null }[];
  places: { admin_district: string | null; admin_state: string | null; events: number; latitude: number; longitude: number }[];
  facilities: { id: string; name: string | null; facility_type: string; operator: string | null; latitude: number; longitude: number; primary_source: string }[];
  classifications: { key: SourceClass; label: string }[];
}

export interface FacilityProfile {
  events: number;
  persistent: number;
  active: number;
  analyst_confirmed: number;
  detections: number;
  frp_max: number | null;
  first_activity: string | null;
  last_activity: string | null;
  classifications: { classification: string; n: number }[];
  note: string;
}

export interface Contribution {
  feature: string;
  value: number | null;
  contribution: number;
}
export interface Prediction {
  model_version_id: string;
  prediction: SourceClass;
  probability: number;
  probabilities: Record<string, number>;
  features_used: Record<string, number | null>;
  explanation: { kind: "shap" | "rule_trace"; contributions: Contribution[]; trace: string[]; notes: string[] } | null;
  created_at: string;
}
export interface Evidence {
  category: string;
  knowledge_type: "observed" | "derived" | "external" | "model";
  direction: "supports" | "contradicts" | "neutral" | "missing";
  strength: number;
  statement: string;
  value: Record<string, unknown> | null;
  provenance: Record<string, unknown> | null;
}
export interface ConfidenceComponent {
  name: string;
  value: number;
  weight: number;
  explanation: string;
}
export interface FacilityLink {
  id: string;
  name: string | null;
  facility_type: string;
  operator: string | null;
  status: string | null;
  capacity_value: number | null;
  capacity_unit: string | null;
  confidence: number;
  primary_source: string;
  source_count: number;
  latitude: number;
  longitude: number;
  distance_m: number;
  bearing_deg: number | null;
  rank: number;
  attribution_score: number;
  sources: { source: string; external_id: string; url: string | null; dataset_version: string | null; published_at: string | null; retrieved_at: string }[] | null;
}
export interface Detection {
  id: string;
  latitude: number;
  longitude: number;
  acq_datetime: string;
  sensor: string;
  satellite: string;
  dataset: string;
  confidence_raw: string | null;
  confidence_pct: number | null;
  frp: number | null;
  brightness: number | null;
  brightness_2: number | null;
  scan: number | null;
  track: number | null;
  daynight: string | null;
  version: string | null;
  data_mode: DataMode;
  source_ref: string;
  retrieved_at: string;
}
export interface Observation {
  obs_date: string;
  detection_count: number;
  frp_max: number | null;
  frp_sum: number | null;
  sensors: string[];
  night_count: number;
  first_at: string;
  last_at: string;
  spread_m: number | null;
}
export interface Weather {
  kind: string;
  source_id: string;
  dataset: string;
  observed_at: string;
  retrieved_at: string;
  temperature_c: number | null;
  humidity_pct: number | null;
  wind_speed_ms: number | null;
  wind_direction_deg: number | null;
  precipitation_mm: number | null;
  pressure_hpa: number | null;
  weather_code: number | null;
  condition: string | null;
}
export interface Scene {
  id: string;
  provider: string;
  source_id: string;
  collection: string;
  item_id: string;
  platform: string | null;
  acquired_at: string;
  cloud_cover: number | null;
  processing_level: string | null;
  relation: "before" | "during" | "after" | "latest";
  thumbnail_url: string | null;
  item_url: string | null;
  bbox: number[] | null;
  retrieved_at: string;
}
export interface TimelineItem {
  at: string;
  kind: "first_seen" | "observation" | "satellite" | "weather" | "classification" | "review" | "alert" | "latest";
  label: string;
  detail: string | null;
}
export interface MatrixRow {
  type: string;
  availability: string;
  strength: number;
  detail: string;
}
export interface PersistenceMetrics {
  active_days: number;
  span_days: number;
  observation_frequency: number;
  longest_gap_days: number;
  frp_cv: number | null;
  sensor_agreement: number;
  recurrence_count: number;
  history_window_days: number;
  recurrence_pattern: string;
  score: number;
  persistence_class: PersistenceClass;
  rationale: string;
}
export interface Review {
  id: string;
  decision: string;
  source_class: string | null;
  persistence_class: string | null;
  false_positive_reason: string | null;
  notes: string | null;
  system_source_class: string | null;
  system_confidence_score: number | null;
  created_at: string;
  reviewer: string | null;
}
export interface Note {
  id: string;
  kind: string;
  body: string;
  url: string | null;
  created_at: string;
  author: string | null;
}

export interface LandCover {
  product: string;
  window_m: number;
  fractions: Record<string, number>;
  dominant: string | null;
  valid_fraction: number;
  source_ref: string | null;
  retrieved_at: string;
}
export interface SpectralScene {
  item_id: string;
  acquired_at: string;
  cloud_cover: number | null;
  ndvi: number | null;
  nbr: number | null;
  valid_fraction: number;
}
export interface ImageryAnalysis {
  status: "ok" | "unavailable";
  reason: string | null;
  finding: "vegetation_loss_consistent" | "partial_change" | "no_change_detected" | null;
  window_m: number;
  before_scene: SpectralScene | null;
  after_scene: SpectralScene | null;
  deltas: { ndvi: number; nbr: number } | null;
  method: { thresholds?: { dndvi: number; dnbr: number } } & Record<string, unknown>;
  retrieved_at: string;
}
/** GET /events/featured: the real event carrying the most evidence, and what it has / lacks. */
export interface FeaturedEvent extends EventSummary {
  selection_reasons: string[];
  unavailable_evidence: string[];
}

export interface EventDetail extends EventSummary {
  persistence_metrics: PersistenceMetrics | null;
  confidence_components: { score: number; state: string; components: ConfidenceComponent[]; missing: string[] } | null;
  data_quality_detail: { grade: string; score: number; factors: { factor: string; score: number; detail: string }[] } | null;
  fingerprint: Record<string, number | string | string[] | null> | null;
  priority_components: PriorityBreakdown | null;
  enrichment_state: Record<string, { status: string; at: string; detail: string | null }> | null;
  datasets: string[];
  footprint: GeoJSON.Polygon | null;
  processed_at: string | null;
  processing_version: string | null;
  detections: Detection[];
  observations: Observation[];
  facilities: FacilityLink[];
  land: { category: string; name: string | null; distance_m: number; osm_type: string; osm_id: number; retrieved_at: string }[];
  landcover?: LandCover | null;
  imagery_analysis?: ImageryAnalysis | null;
  weather: Weather[];
  satellite: Scene[];
  classification_current: { primary_model_id: string; supporting_model_ids: string[]; pipeline_version: string; created_at: string } | null;
  classification_history: { source_class: string; persistence_class: string; confidence_score: number; confidence_state: string; primary_model_id: string; created_at: string }[];
  predictions: Prediction[];
  evidence: Evidence[];
  reviews: Review[];
  notes: Note[];
  alerts: { id: string; title: string; severity: string; triggered_at: string; status: string; rule_name: string }[];
  investigation: { id: string; status: string; priority: string; assignee: string | null; assigned_to: string | null } | null;
  timeline: TimelineItem[];
  evidence_matrix: MatrixRow[];
}

export interface Facility {
  id: string;
  name: string | null;
  facility_type: string;
  operator: string | null;
  status: string | null;
  capacity_value: number | null;
  capacity_unit: string | null;
  state: string | null;
  district: string | null;
  latitude: number;
  longitude: number;
  confidence: number;
  primary_source: string;
  source_count: number;
  event_count?: number | null;
  sources?: { source: string; external_id: string; name: string | null; source_type: string | null; url: string | null; dataset_version: string | null; published_at: string | null; retrieved_at: string }[] | null;
}

export interface AlertRule {
  id: string;
  name: string;
  is_active: boolean;
  latitude: number | null;
  longitude: number | null;
  radius_m: number | null;
  watchlist_id: string | null;
  source_classes: SourceClass[];
  persistence_classes: PersistenceClass[];
  facility_types: string[];
  facility_within_m: number | null;
  min_confidence: number | null;
  min_frp: number | null;
  min_duration_hours: number | null;
  channels: ("in_app" | "email" | "push")[];
  cooldown_minutes: number;
  min_priority: number | null;
  min_repeat_events: number | null;
  repeat_days: number;
  activity_increase: boolean;
  last_notified_at: string | null;
  created_at: string;
  last_triggered_at: string | null;
  alert_count: number;
}
export interface Alert {
  id: string;
  rule_id: string;
  rule_name: string;
  event_id: string;
  event_public_id: string;
  triggered_at: string;
  severity: "info" | "warning" | "critical";
  title: string;
  reason: Record<string, unknown>;
  status: "new" | "acknowledged" | "resolved";
  acknowledged_at: string | null;
  deliveries: { channel: string; status: string; error: string | null; attempted_at: string }[];
}
export interface Watchlist {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  items: { id: string; kind: string; label: string; facility_id: string | null; event_id: string | null; radius_m: number | null; admin_district: string | null; geometry: GeoJSON.Geometry | null; facility_name: string | null; facility_type: string | null }[];
  summary: { events: number; new_since_viewed: number; persistent: number; active: number; changed_since_viewed: number; latest: string | null; since: string };
}
export interface Report {
  id: string;
  event_id: string;
  title: string;
  status: "pending" | "ready" | "failed";
  format: string;
  size_bytes: number | null;
  sha256: string | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}
export interface Job {
  id: string;
  kind: string;
  status: string;
  payload: Record<string, unknown>;
  attempts: number;
  max_attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
}
export interface SystemStatus {
  firms_sync: string | null;
  latest_detection: string | null;
  registry_sync: string | null;
  osm_sync: string | null;
  satellite_update: string | null;
  latest_scene: string | null;
  demo_detections: number;
  active_events: number;
  worker_seen: string | null;
  worker_online: boolean;
  demo_mode: boolean;
  environment: string;
  server_time: string;
}
export interface DataSource {
  id: string;
  name: string;
  kind: string;
  homepage: string;
  license: string;
  access: string;
  cadence: string;
  status: string;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
  last_record_at: string | null;
  records_total: number;
  requests_total: number;
  requests_failed: number;
  latency_ms_ewma: number | null;
  dataset_version: string | null;
  dataset_published_at: string | null;
  error_rate: number | null;
  configuration: { configured?: boolean; note?: string | null; mode?: string };
  last_run: { status: string; started_at: string; completed_at: string | null; records_inserted: number; error_detail: string | null } | null;
}

/** GET /public/landing: safe public aggregates for the landing page (no identifiers or personal data). */
export type PublicSourceState = "active" | "degraded" | "unavailable" | "not_configured" | "standby";
export interface PublicLanding {
  counts: { detections: number; events: number; events_recent: number; facilities: number };
  sources: { id: string; name: string; kind: string; state: PublicSourceState; last_success_at: string | null }[];
  sources_active: number;
  sources_total: number;
  latest_detection: string | null;
  firms_last_sync: string | null;
  workers_online: boolean;
  classifier: string;
  activity: { window_days: number; cell_deg: number; cells: [number, number, number][] };
  generated_at: string;
  cache_seconds: number;
}
