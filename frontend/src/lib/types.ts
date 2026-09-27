/** Shared domain types — mirror backend/app/schemas/api.py. */

export type Role = "viewer" | "analyst" | "supervisor" | "admin";
export type SourceClass =
  | "flare" | "process_heat" | "coal_seam_fire" | "agricultural_burn" | "wildfire" | "industrial_fire" | "other" | "unknown";
export type PersistenceClass = "transient" | "recurring" | "persistent";
export type DisplayState =
  | "CONFIRMED" | "HIGH_CONFIDENCE" | "MODERATE_CONFIDENCE" | "LOW_CONFIDENCE" | "INSUFFICIENT_EVIDENCE"
  | "UNDER_REVIEW" | "ANALYST_CONFIRMED" | "ANALYST_REJECTED" | "ANALYST_REVIEWED";
/** thermal_events.review_status (backend processing/confidence.py REVIEW_STATUSES). */
export type ReviewStatus = "unreviewed" | "under_review" | "escalated" | "reviewed" | "analyst_confirmed" | "analyst_rejected" | "false_positive";
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
  review_status: ReviewStatus;
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
  facilities: { id: string; name: string | null; facility_type: string; operator: string | null; latitude: number; longitude: number; primary_source: string; match?: string; matched_value?: string | null }[];
  states?: { state: string; events: number; latitude: number; longitude: number }[];
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
/** What kind of knowledge a value is. `registry` is facility reference data (OSM, WRI, GEM, CEA), not an observation. */
export type Knowledge = "observed" | "derived" | "inferred" | "analyst" | "registry";
export interface TimelineItem {
  at: string;
  kind: "first_seen" | "observation" | "gap" | "clustered" | "facility" | "enrichment" | "satellite" | "weather" | "spectral"
    | "classification" | "review" | "note" | "alert" | "latest";
  label: string;
  detail: string | null;
  knowledge?: Knowledge;
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
  previous_status?: string | null;
  new_status?: string | null;
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
  /** ok · unavailable: no suitable data (reason says why) · failed: the provider could not be read */
  status: "ok" | "unavailable" | "failed";
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
  enrichment_state: Record<string, EnrichmentStep> | null;
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
  /** On-demand work for this event: latest job per kind and step set (last 7 days). */
  jobs?: EventJob[];
  /** Whether NDVI/NBR can be attempted from the stored scenes (same rule the API enforces). */
  imagery_readiness?: { ready: boolean; reason: string | null; max_cloud: number } | null;
  /** The 13 evidence stages and how many are available (availability, not confidence). */
  evidence_stages?: { stages: EvidenceStage[]; completeness: Completeness; freshness: EventFreshness } | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export type StageStatus = "available" | "pending" | "no_data" | "not_requested" | "failed" | "review";
export interface EvidenceStage {
  key: string;
  title: string;
  state: StageStatus;
  state_label: string;
  value: string;
  detail: string | null;
  reason: string | null;
  source: string;
  at: string | null;
  contributes: string;
  limitation: string;
  knowledge: Knowledge;
}
/** Distinct times, never conflated: heat last observed, evidence last refreshed, record last changed. */
export interface EventFreshness {
  latest_observation_at: string | null;
  latest_evidence_refresh_at: string | null;
  processed_at: string | null;
  record_updated_at: string | null;
}
export interface Completeness { available: number; total: number; by_state: Record<StageStatus, number>; note: string }

export interface KeyCount { key: string; n: number }
export interface ActivityCounts {
  this_week: number; previous_week: number; last_30_days: number; previous_30_days: number; total: number;
  first_activity: string | null; last_activity: string | null; detections: number; frp_max_mean: number | null;
  frp_max: number | null; weekly_average: number; history_weeks: number;
}
export interface Recurrence { radius_km: number; activity: ActivityCounts; classifications: KeyCount[]; persistence: KeyCount[];
  monthly: { month: string; events: number }[]; note: string }
export interface ClusterEvent {
  id: string; public_id: string; latitude: number; longitude: number; first_detected: string; last_detected: string;
  observation_count: number; frp_max: number | null; classification: SourceClass | null; persistence_class: PersistenceClass | null;
  confidence_state: DisplayState | null; review_status: string; priority_score: number | null; distance_m: number;
}
export interface Cluster {
  cluster_id: string; anchor: { public_id: string; latitude: number; longitude: number; first_detected: string; last_detected: string };
  radius_km: number; days: number;
  summary: { events: number; detections: number; first_detected: string | null; last_detected: string | null; frp_max: number | null;
    frp_mean: number | null; extent: GeoJSON.Geometry | null; max_distance_m: number | null; duration_hours: number };
  classifications: KeyCount[]; persistence: KeyCount[]; landcover: KeyCount[];
  facilities: { id: string; name: string | null; facility_type: string; latitude: number; longitude: number; events: number;
    min_distance_m: number; attributed: number }[];
  events: ClusterEvent[]; truncated: boolean; note: string;
}
export interface SimilarEvent extends EventSummary { fp_distance?: number | null; distance_m?: number | null; similarity_reasons?: string[] }
export interface CompareRecord {
  id: string; public_id: string; latitude: number; longitude: number; place: string | null; state: string | null;
  first_detected: string; last_detected: string; classification: SourceClass | null; confidence_state: string | null;
  confidence_score: number | null; display_state: DisplayState; priority_score: number | null; frp_max: number | null;
  frp_mean: number | null; brightness_max: number | null; observation_count: number; persistence_class: PersistenceClass | null;
  days_active: number;
  facility: { name: string | null; type: string; distance_m: number; rank: number; attribution_score: number } | null;
  landcover: { dominant: string; share: number | null } | null;
  weather: { condition: string | null; temperature_c: number | null; wind_speed_ms: number | null; wind_direction_deg: number | null; observed_at: string } | null;
  imagery: { scenes: number; spectral_status: string | null; finding: string | null; deltas: { ndvi: number; nbr: number } | null; reason: string | null };
  shap_top: { feature: string; value: number | null; contribution: number }[] | null;
  review_status: string;
  completeness: Completeness;
}
export interface Compare { a: CompareRecord; b: CompareRecord; distance_m: number; note: string }

export interface FacilityActivityProfile {
  within_m: number;
  counts: { within_2km: number; within_10km: number; attributed: number };
  activity: ActivityCounts;
  comparison: { current_week: number; previous_week: number; weekly_average: number; current_30_days: number; previous_30_days: number; note: string };
  distributions: { frp: { from: number; to: number | null; n: number }[]; brightness: { from: number; to: number | null; n: number }[];
    persistence: KeyCount[]; classifications: KeyCount[]; hour_of_day: { hour: number; daynight: string | null; n: number }[] };
  weekly: { week: string; events: number; detections: number }[];
  source_agreement: { sources: Record<string, { present: boolean; records: { source_id: string; external_id: string; name: string | null }[] }>;
    count: number; note: string };
  note: string;
}

export interface EvidenceCoverage {
  events: number; detection: number; clustering: number; persistence: number; facility_proximity: number; facility_attribution: number;
  landcover: number; weather: number; satellite: number; spectral: number; classification: number; explainability: number;
  review: number; final_status: number; mean_stages: number | null; stages_total: number; note: string;
}
export interface AnalyticsOverview {
  filters: { since: string; until: string; state: string | null; district: string | null; facility_id: string | null; classification: string[] };
  totals: { events: number; detections: number; active: number; active_investigations: number; needs_review: number; confirmed: number;
    rejected: number; reviewed: number; high_priority_queue: number; persistent: number };
  recurring_facilities: number;
  evidence_coverage: EvidenceCoverage;
  processing: { running: number; queued: number; last_failure: string | null };
  note: string;
}
export interface Recurring {
  days: number; min_events: number;
  facilities: { id: string; name: string | null; facility_type: string; latitude: number; longitude: number; state: string | null;
    current: number; previous: number; frp_max: number | null; last_activity: string }[];
  places: { latitude: number; longitude: number; place: string | null; state: string | null; current: number; previous: number;
    frp_max: number | null; classification: string | null }[];
  note: string;
}
export type LiveSourceStatus = "healthy" | "configured" | "optional" | "no_data" | "degraded" | "failed" | "not_configured";
export interface LiveStatus {
  sources: { id: string; name: string; kind: string; status: LiveSourceStatus; label: string; requires_credentials: boolean; optional: boolean;
    last_success_at: string | null; last_failure_at: string | null }[];
  sources_active: number; sources_total: number;
  jobs: { running: number; queued: number; failed_24h: number; running_jobs: { kind: string; status: string; started_at: string }[] };
  last_firms_update: string | null; last_weather_update: string | null; last_satellite_search: string | null;
  last_failed_source: { id: string; name: string; at: string; category: string | null } | null;
  worker_online: boolean;
}
export interface SourceDetail {
  id: string; name: string; kind: string; purpose: string | null; access: string; authentication: string; optional: boolean;
  optional_detail: string | null; status: LiveSourceStatus; label: string; reason: string; last_success_at: string | null;
  last_failure_at: string | null; last_error_category: string | null; records_total: number; requests_total: number;
  requests_failed: number; latency_ms: number | null; rate_limit: string; checks: Record<string, unknown> | null;
}
export interface AlertCondition { condition: string; label: string; threshold: string | number | null; observed: string | number | null;
  previous?: number | null; result: string }
export interface AlertExplanation { rule: string; rule_id?: string; rule_snapshot?: Record<string, unknown>; conditions: AlertCondition[]; summary: string; result: string; evaluated_at: string;
  event: string; facility: string | null; facility_distance_m: number | null;
  evidence: { classification: string | null; confidence_state: string | null; priority: number | null; evidence_stages: number | null; last_detected: string | null };
  note: string }

/** One enrichment step's recorded outcome: ok (provider answered), no_data (answered without an observation), failed. */
export interface EnrichmentStep {
  status: "ok" | "no_data" | "failed" | string;
  at: string;
  detail: string | null;
  category?: string;
  requested_at?: string;
  scenes?: number;
  before?: number;
  after?: number;
  window_start?: string;
  window_end?: string;
  max_cloud?: number;
}

export interface EventJob {
  kind: "enrich_event" | "imagery_analysis";
  steps: string[];
  status: "queued" | "running" | "succeeded" | "failed";
  attempts: number;
  max_attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_type: string | null;
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
  subtype?: string | null;
  registries?: { source: string; station?: string; coordinate_source?: string; [k: string]: unknown }[] | null;
}

/** GET /facilities/{id}/relationship?event=: how one event relates to the facility. */
export interface FacilityRelationship {
  event: { id: string; public_id: string; latitude: number; longitude: number; first_detected: string; last_detected: string;
    classification: SourceClass | null; confidence_state: DisplayState; confidence_score: number | null; frp_max: number | null };
  linked: boolean;
  distance_m: number;
  bearing_deg: number | null;
  rank: number | null;
  attribution_score: number | null;
  rule_radius_m: number;
  search_radius_m: number;
  evidence?: { statement: string; direction: string; strength: number; knowledge_type: string }[];
  temporal?: { around_event: number; total: number; first_activity: string | null; last_activity: string | null; note: string };
  note: string;
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
  increase_factor: number;
  increase_window_days: number;
  repeat_within_m: number | null;
  min_active_days: number | null;
  min_evidence_stages: number | null;
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
  /** raw provider message: administrators only (null for everyone else) */
  last_error: string | null;
  last_error_category: string | null;
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
  /** Backend-derived state (services/source_health.effective_state) and what an inactive source needs. */
  state?: PublicSourceState;
  state_reason?: string;
  requirement?: string | null;
  requirement_env?: string[] | null;
  requirement_how?: string | null;
  /** Recorded checks per capability (Copernicus: auth, preview) and station-registry figures (CEA). */
  health_detail?: Record<string, CapabilityCheck & { http_status?: number | null; consecutive_failures?: number }> | null;
  registry?: RegistrySummary | null;
}

/** GET /public/landing: safe public aggregates for the landing page (no identifiers or personal data). */
export type PublicSourceState = "active" | "degraded" | "unavailable" | "credentials_required" | "import_required" | "not_used" | "unverified";
/** One recorded check of a capability (e.g. Copernicus authentication or SWIR preview). */
export interface CapabilityCheck { ok: boolean; checked_at: string; latency_ms: number | null; error: string | null; last_success_at: string | null }
export interface RegistrySummary { stations: number; located: number; ambiguous: number; unmatched: number; facilities: number; imported_at: string; coordinate_sources: string[] }
export interface PublicLanding {
  counts: { detections: number; events: number; events_recent: number; facilities: number; events_outside_india: number };
  sources: { id: string; name: string; kind: string; state: PublicSourceState; reason: string; requirement: string | null; last_success_at: string | null }[];
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
