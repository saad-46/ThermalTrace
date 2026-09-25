/** Test fixture shaped like a real /events/{ref} bundle (values from TT-2026-001323, abbreviated). */
import type { EventDetail } from "../lib/types";

export function event(over: Partial<EventDetail> = {}): EventDetail {
  const base: EventDetail = {
    id: "00000000-0000-0000-0000-000000000001", public_id: "TT-2026-001323", latitude: 21.1055, longitude: 72.641,
    data_mode: "live", first_detected: "2026-09-18T21:08:00Z", last_detected: "2026-09-24T21:50:00Z",
    observation_count: 159, sensor_count: 5, sensors: ["Aqua", "NOAA-20", "NOAA-21", "S-NPP", "Terra"], days_active: 7,
    duration_hours: 144.7, frp_max: 37.2, frp_mean: 6.2, night_fraction: 0.74, status: "active", review_status: "unreviewed",
    persistence_class: "persistent", persistence_score: 0.54, classification: "process_heat", classification_probability: 0.75,
    confidence_score: 0.73, confidence_state: "HIGH_CONFIDENCE", display_state: "HIGH_CONFIDENCE", data_quality: "good",
    nearest_facility_distance_m: 566, nearest_facility_name: "ArcelorMittal Nippon Steel India", nearest_facility_type: "steel_plant",
    admin_state: "Gujarat", admin_district: "Surat", country: "India", assigned_to: null, priority_score: 69,
    persistence_metrics: { active_days: 7, span_days: 7, observation_frequency: 1, longest_gap_days: 0, frp_cv: 0.3, sensor_agreement: 1,
      recurrence_count: 0, history_window_days: 8, recurrence_pattern: "continuous", score: 0.54, persistence_class: "persistent",
      rationale: "active on 7 of 7 days" },
    confidence_components: { score: 0.73, state: "HIGH_CONFIDENCE", missing: ["trained model", "satellite imagery"], components: [] },
    data_quality_detail: null, fingerprint: null,
    priority_components: { score: 69, tier: "elevated", note: "Orders the review queue; not a risk or threat assessment.", components: [
      { name: "thermal_intensity", points: 12.8, max: 20, detail: "peak FRP 37.2 MW" }] },
    enrichment_state: { osm: { status: "ok", at: "2026-09-25T06:00:00Z", detail: null } }, datasets: ["VIIRS_NOAA21_NRT"], footprint: null,
    processed_at: null, processing_version: "pipeline-1.0", detections: [],
    observations: [{ obs_date: "2026-09-18", detection_count: 12, frp_max: 20, frp_sum: 80, sensors: ["NOAA-20"], night_count: 8,
      first_at: "2026-09-18T21:08:00Z", last_at: "2026-09-18T22:00:00Z", spread_m: 900 },
      { obs_date: "2026-09-20", detection_count: 3, frp_max: 30, frp_sum: 60, sensors: ["Terra"], night_count: 1,
        first_at: "2026-09-20T05:00:00Z", last_at: "2026-09-20T05:10:00Z", spread_m: 400 }],
    facilities: [{ id: "f1", name: "ArcelorMittal Nippon Steel India", facility_type: "steel_plant", operator: null, status: null,
      capacity_value: null, capacity_unit: null, confidence: 0.5, primary_source: "osm", source_count: 1, latitude: 21.11, longitude: 72.64,
      distance_m: 566, bearing_deg: 20, rank: 1, attribution_score: 0.31, sources: [] }],
    land: [], weather: [], satellite: [],
    classification_current: { primary_model_id: "rule-cascade-v1.0", supporting_model_ids: [], pipeline_version: "pipeline-1.0", created_at: "2026-09-25T06:00:00Z" },
    classification_history: [], predictions: [], evidence: [], reviews: [], notes: [], alerts: [], investigation: null, timeline: [], evidence_matrix: [],
  };
  return { ...base, ...over };
}
