/** The two guided tours. Wording is kept technically defensible: see docs/ML.md, docs/DATA_SOURCES.md and
 *  docs/GIS.md for the behaviour each step describes. Steps target `data-tour-id` attributes in the real UI.
 *  Each step says what it is (body), why it matters (why), how it is produced (how) and what it cannot do (limits). */
import { demoSearch } from "./events";
import type { Tour, TourContext } from "./types";

const ev = (ctx: TourContext) => ctx.featured?.public_id ?? null;
const eventRoute = (ctx: TourContext) => (ev(ctx) ? `/events/${ev(ctx)}` : null);
const mapRoute = (ctx: TourContext) => (ev(ctx) ? `/map?event=${ev(ctx)}` : "/map");
/** The featured event's nearest facility, opened in its satellite view (null when the event has no mapped facility). */
const satelliteRoute = (ctx: TourContext) => (ev(ctx) && ctx.featured?.nearest_facility_id
  ? `/facilities/${ctx.featured.nearest_facility_id}?event=${ev(ctx)}&view=satellite` : null);
const NO_EVENT = "No thermal events have been ingested on this installation yet, so there is no real event to show here. Once FIRMS data arrives, this step points at one.";

const list = (items: string[]) => (items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`);

export const ANALYST_TOUR: Tour = {
  id: "analyst",
  label: "Analyst",
  summary: {
    lead: "You just followed the ThermalTrace investigation workflow on a real event.",
    flow: ["Satellite detection", "Event", "Context", "Evidence", "Classification", "Confidence", "Human review", "Action"],
  },
  steps: [
    {
      id: "welcome", title: "Welcome to ThermalTrace", target: "overview-metrics", route: "/overview",
      body: "ThermalTrace turns satellite-detected thermal anomalies into explainable, geospatial evidence. For each hotspot it helps an analyst judge whether it is more consistent with industrial process heat, a gas flare, a coal-seam fire, agricultural burning, a vegetation fire or something else, or whether there is not yet enough evidence to say.",
      learnMore: "Everything in this tour is the live application with its real data. Demo mode only makes it read-only.",
    },
    {
      id: "problem", title: "A satellite sees heat, not causes", target: "overview-trends", route: "/overview",
      mobile: { target: "overview-metrics" },
      body: "A thermal detection says that a pixel was unusually hot when the satellite passed. The same signal can come from a steel furnace, a refinery flare, burning crop residue, an underground coal fire or a forest fire. ThermalTrace combines independent evidence to narrow that down, and says so when it cannot.",
      why: "Acting on the wrong interpretation is costly both ways: treating process heat as a wildfire wastes response effort; dismissing an industrial fire as routine misses it.",
      terms: ["firms"],
    },
    {
      id: "data", title: "Where the evidence comes from", target: "overview-sources", route: "/overview",
      body: "Thermal detections come from NASA FIRMS (MODIS and VIIRS). Context comes from OpenStreetMap, the WRI power-plant database, Global Energy Monitor, ESA WorldCover land cover, Sentinel-2 imagery and Open-Meteo weather. The value is in correlating them in space and time.",
      why: "Each source's health is tracked. When a source fails, the affected evidence is marked unavailable; nothing is filled in with guesses.",
      limits: "Coverage depends on these sources: an unmapped facility or a cloudy week is a gap in the evidence, not evidence against a cause.",
    },
    {
      id: "queue", title: "Events, not thousands of raw pixels", target: "events-table", route: "/events",
      mobile: { target: "events-list" },
      body: "Detections close in space and time are grouped into events, and the queue is ordered by triage priority: how much an event deserves attention first, from intensity, persistence, nearby industry, confidence and satellite agreement.",
      how: "Detections within a clustering distance and time gap join the same event; each event keeps every source pixel. Priority is a weighted sum of five components shown on the event page under “Why is this prioritised?”.",
      limits: "Triage priority is not a fire-risk or danger score. It only orders the review queue.",
      terms: ["event", "priority", "frp"],
    },
    {
      id: "search", title: "Search across the platform", target: "global-search",
      body: (ctx) => ctx.featured
        ? `Search matches event IDs, places, districts, facilities and classifications, and accepts coordinates. Here it is searching for a real event, ${ctx.featured.public_id}.`
        : "Search matches event IDs, places, districts, facilities and classifications, and accepts coordinates such as 23.79, 86.43.",
      action: (ctx) => { if (ctx.featured) demoSearch(ctx.featured.public_id); },
      cleanup: () => demoSearch(""),
    },
    {
      id: "featured", title: "The event in this walkthrough", target: "event-header", route: eventRoute,
      body: (ctx) => ctx.featured
        ? `${ctx.featured.public_id} was chosen automatically from the live data because it carries the most evidence: ${list(ctx.featured.selection_reasons ?? []) || "it is at the top of the triage queue"}.` +
          (ctx.featured.unavailable_evidence?.length ? ` Not available for it: ${list(ctx.featured.unavailable_evidence)}.` : "")
        : NO_EVENT,
      why: "A walkthrough is only honest on a real event. Nothing here is staged or hard-coded; a different event may be chosen tomorrow.",
      limits: "Evidence that is not available for this event is shown as unavailable on the event page, never invented.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "map", title: "Geography is the investigation", target: "map-canvas", route: mapRoute,
      body: "The map shows events in context: thermal events are circles coloured by classification, facilities are squares, and the selected event has a halo, its satellite pixels and its footprint. Numbered circles group nearby events and split apart as you zoom in.",
      how: "Events are fetched for the visible area only and clustered on the map; the selected event's pixels come from its own FIRMS detections.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "layers", title: "Map layers and legend", target: "map-legend", route: mapRoute,
      mobile: { target: null },
      body: "The Layers menu adds context progressively: activity density, industrial areas, quarries, roads, rivers, district and state boundaries, OpenStreetMap land cover and a satellite basemap. The legend changes with the layers that are on. The default map stays clean.",
      limits: "Activity density shows where heat was observed, not fire risk. Roads, districts and land use come from OpenStreetMap and are as complete as its mapping.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "facility", title: "Facility attribution", target: "map-event-panel", route: mapRoute,
      mobile: { route: eventRoute, target: "card-facilities" },
      body: "Each event is compared with mapped facilities within 10 km. Support for a link falls off with distance; the nearest facility, its type, distance, bearing and sources are shown. Clicking a facility square opens its card, and View facility details opens its intelligence profile: identity, registry agreement, observed activity week by week and its thermal profile.",
      how: "PostGIS distance queries against a facility index merged from OpenStreetMap, WRI and Global Energy Monitor; agreement between independent sources raises a facility's confidence.",
      limits: "Proximity is supporting evidence for attribution. It does not prove that a facility caused the heat.",
      terms: ["distanceDecay"],
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "rings", title: "The 2 km and 10 km rings", target: "map-canvas", route: mapRoute,
      body: "Around the selected event, the inner dashed ring is 2 km, the distance the rules treat as “near” industry; the outer ring is 10 km, the facility search radius.",
      learnMore: "Both radii are configuration, documented in docs/GIS.md; they are not tuned per event.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "satellite", title: "Satellite context", target: "facility-satellite", route: satelliteRoute,
      body: "On a facility's page, Satellite swaps the street map for real imagery centred on the facility's registered coordinates, with the same 2 km and 10 km rings, the selected event and the other events linked to it. Clicking an event opens it. The card names the source and the imagery date.",
      how: "Sentinel-2 cloudless annual mosaics by EOX (contains modified Copernicus Sentinel data), loaded as map tiles only when Satellite is chosen. A mosaic blends many cloud-free scenes from its year, so it has no single acquisition date; the year selector lists only the mosaics that exist.",
      why: "Seeing the ground (a plant's footprint, stockyards, fields or forest around the event) helps judge whether the facility or something else nearby is the likelier heat source.",
      limits: "The imagery is geographic context. It is not dated to the event, does not show fire or burn scars and does not prove the facility caused the anomaly; the before/after spectral analysis is separate evidence.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "persistence", title: "Persistence over time", target: "persistence-panel", route: eventRoute,
      mobile: { target: "card-persistence" },
      body: "The activity chart switches between FRP, brightness, detections and persistence (hover for time, value and sensor). The strip shows each day of the event: a filled cell when it was detected, an empty one when it was not. Repeated detections over days or weeks are evidence of sustained activity.",
      how: "Computed from the event's daily FIRMS observations: active days, span, gaps and recurrence give a class (transient, recurring or persistent).",
      limits: "Satellites pass a few times a day and clouds hide fires, so a gap can mean “not observed” rather than “not burning”.",
      terms: ["persistence"],
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "chain", title: "How ThermalTrace thinks", target: "evidence-chain", route: eventRoute,
      mobile: { target: "card-evidence-chain" },
      body: "Evidence accumulates in 13 stages, from the thermal detection to the final status. Each stage says whether it is Available, Pending, No data, Not requested, Failed or Requires analyst review, and expands to show its source, time, what it contributes and its limitation.",
      why: "No single signal decides the outcome, and a missing stage is shown as missing with its reason, never as negative evidence.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "completeness", title: "Evidence availability", target: "evidence-completeness", route: eventRoute,
      mobile: { target: "card-evidence-availability" },
      body: "The bar counts how many of the 13 stages have evidence for this event, for example 9 / 13.",
      limits: "This is evidence availability, not a confidence score: it says how much has been collected, not which interpretation is right.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "timeline", title: "The event timeline", target: "event-timeline", route: eventRoute,
      mobile: { target: "card-timeline" },
      body: "Every stored timestamp in order: first detection, repeated detections, clustering, facility proximity, weather, scenes, classification changes and analyst actions. Play steps through it; gaps between detection days are shown explicitly.",
      limits: "Only recorded times appear. Nothing is interpolated, so a gap means no detection was stored, not that nothing happened.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "landcover", title: "Land cover around the event", target: "landcover-panel", route: eventRoute,
      mobile: { target: "card-landcover" },
      body: "ESA WorldCover gives the land-cover mix in a 1.5 km square around the event. Mostly cropland supports an agricultural-burning reading; built-up or bare ground supports an industrial one; a mixed picture adds little.",
      how: "A windowed read of the 10 m WorldCover 2021 map (cloud-optimised GeoTIFF) around the event.",
      limits: "Land cover is context, never a verdict. The map is from 2021 and a 1.5 km window can mix uses, so a classification relying on it is capped at 0.60.",
      terms: ["worldcover"],
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "spectral", title: "Imagery: before and after", target: "spectral-panel", route: eventRoute,
      mobile: { target: "card-spectral" },
      body: "Sentinel-2 scenes before and after the event can be compared with two indices, NDVI and NBR, with clouds and shadows masked. A drop in both is consistent with burning, not proof of burning.",
      how: "Clear L2A scenes are chosen either side of the event and the mean change of each index over clear pixels in a 1 km window is compared with fixed thresholds.",
      limits: "Not real-time: Sentinel-2 revisits about every 5 days and clouds often block it. When imagery is unavailable the panel says why instead of reporting “no change”.",
      terms: ["ndvi", "nbr"],
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "classification", title: "Classification and confidence", target: "classification-explained", route: eventRoute,
      mobile: { target: "card-classification" },
      body: "The explainable classification shows the current interpretation, its confidence wording, the evidence that supports it (and any against it), the values it rests on and what is missing. When evidence is weak the state is INSUFFICIENT EVIDENCE rather than a forced guess.",
      why: "Confidence reflects the available evidence supporting this classification. It is not the probability of a fire.",
      limits: "The confidence score is a weighted evidence score, not a calibrated probability. “Confirmed” needs an imagery check or an analyst; the model alone never sets it.",
      terms: ["rules"],
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "shap", title: "Why the system decided", target: "model-panel", route: eventRoute,
      mobile: { target: "card-model" },
      body: "The model evidence shows which rules fired and how each input pushed the result. When a trained model is active, SHAP values show each feature's contribution to its output.",
      how: "The rule cascade records a trace of every rule it evaluated; a trained LightGBM model records SHAP contributions per prediction.",
      limits: "SHAP explains contribution; it does not prove causation. It describes the model's behaviour, not the real world.",
      terms: ["shap"],
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "recurring", title: "Recurring activity and clusters", target: "recurring-activity", route: eventRoute,
      mobile: { target: "card-recurring" },
      body: "How often heat has been observed around this location: this week, the previous week, the last 30 days and the historical weekly average. View cluster (top of the page) lists the nearby events in space and time with their facilities and classifications.",
      limits: "This is observed activity, not risk. A cluster groups nearby activity for review; it does not mean the events share a source or cause.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "similar", title: "Similar events and comparison", target: "similar-events", route: eventRoute,
      mobile: { target: "card-similar" },
      body: "Events with the closest thermal fingerprint, each with the reasons it is considered similar. Compare opens two events side by side: location, classification, FRP, persistence, facility, land cover, weather, imagery, SHAP, review state and evidence availability.",
      limits: "Similarity describes the observed pattern; it does not mean the events have the same cause. The comparison has no ranking or winner.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "review", title: "Human review", target: "review-panel", route: eventRoute,
      mobile: { target: "event-tabs" },
      body: "Analysts confirm, reclassify, reject, mark a false positive, escalate, mark reviewed or request more evidence; supervisors assign a reviewer. The review history shows each decision with the reviewer, date, previous and new status and the reason. Every decision is audited.",
      why: "Automation assists the analyst; it does not replace judgement. In demo mode the buttons are visible but saving is disabled.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "alerts", title: "From investigation to alerts", target: "alerts-rules", route: "/alerts",
      mobile: { target: "alerts-list" },
      body: "Alert rules turn investigation criteria into notifications: classes, persistence, a minimum triage priority, evidence availability, repeated activity at a facility or a rise against the previous period. Each alert has a Why was I alerted? view with every condition, its threshold and the observed value.",
      why: "A cooldown stops repeated observations from flooding inboxes; suppressed notifications are recorded, never silently dropped.",
      limits: "By default only events detected in the last 72 hours can alert, so loading historical data never sends notifications.",
    },
    {
      id: "reports", title: "Reports", target: "event-actions", route: eventRoute,
      body: "An investigation exports as a PDF report (executive summary, thermal, spatial and environmental evidence, explainability, evidence limitations, audit history) and opens as a read-only Shareable view for presentation or screen sharing.",
      limits: "The report states that confidence is supporting evidence, not proof, and that confirmation needs imagery or an analyst.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "summary", title: "Investigation summary", target: "investigation-summary", route: eventRoute,
      mobile: { target: "event-tabs" },
      body: "The summary answers the analyst's questions in one place: where, when, how long, what type, which facility, what the imagery and weather show, the confidence, what is missing and what an analyst decided.",
      why: "This is the hand-off: an investigation should be understandable without re-running the analysis.",
      needsEvent: true, fallback: NO_EVENT,
    },
  ],
};

export const ADMIN_TOUR: Tour = {
  id: "admin",
  label: "Admin",
  summary: {
    lead: "You just explored how ThermalTrace operates behind the investigation workflow.",
    flow: ["Data", "Processing", "Evidence", "Classification", "Governance", "Operations"],
  },
  steps: [
    {
      id: "admin-overview", title: "Behind the investigation", target: "system-metrics", route: "/system",
      body: "The admin view shows the machinery that produces the evidence: database, background workers, job queue, model versions and the audit trail. This is a running system, not a static dashboard.",
      how: "A FastAPI service over PostgreSQL/PostGIS, two background worker lanes and a React client. Everything shown is read live from them.",
      learnMore: "Demo mode is read-only: controls are visible so you can see what exists, but the server refuses every change.",
      terms: ["postgis"],
    },
    {
      id: "sources", title: "Data-source health", target: "sources-table", route: "/sources",
      body: "Every provider is tracked: state, last success, last failure, latest record and error rate. Details opens a provider: its purpose, whether it needs a key (most need none), health, freshness, the last error category and whether it is optional.",
      why: "Analysts need to know whether the picture is current. A failing source is shown as failing, never masked with substitute data.",
      limits: "Some sources need credentials (FIRMS map key, Copernicus). Without them the source shows as not configured and its evidence is unavailable.",
    },
    {
      id: "live-status", title: "Live system status", target: "live-status", route: "/sources",
      mobile: { target: null },
      body: "The status button in the header opens the live panel: healthy sources out of the total, the last FIRMS, weather and satellite updates, running and queued jobs and the last failing source. Healthy, Configured, Optional, No data, Degraded, Failed and Not configured are distinct states.",
      limits: "A provider that needs no credentials is never shown as inactive for lacking them; Healthy means a recent request actually succeeded.",
    },
    {
      id: "freshness", title: "Evidence freshness", target: "evidence-chain", route: eventRoute,
      mobile: { target: "card-evidence-chain" },
      body: "Every evidence stage shows when it was updated or last checked, or that it was not requested. The times come from the database and provider records.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "ingestion", title: "FIRMS ingestion", target: "ingestion-runs", route: "/sources",
      body: "Thermal detections are polled from NASA FIRMS on a schedule, normalised, de-duplicated by a natural key (dataset, position and acquisition time) and stored with their raw values. Each run is recorded with fetched, inserted, duplicate and rejected counts.",
      how: "The scheduler enqueues polling jobs per FIRMS product; historical backfills run in bounded date windows so they can resume after a failure.",
      limits: "FIRMS near-real-time data typically arrives a few hours after the satellite pass; this is not an instant feed.",
    },
    {
      id: "processing", title: "From detections to evidence", target: "evidence-chain", route: eventRoute,
      mobile: { target: "card-evidence-chain" },
      body: "After ingestion, detections are clustered into events, enriched (places, land use, facilities, land cover, weather, imagery search) and turned into typed evidence: observed, derived, external context and model output. This event's progression is the pipeline's real output.",
      how: "Each enrichment step records its own status and time on the event, so a failed lookup is retried and shown as unavailable rather than as absence.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "facilities", title: "Facility data and provenance", target: "facility-index", route: "/sources",
      body: "Facilities are assembled from OpenStreetMap, the WRI power-plant database, Global Energy Monitor trackers and CEA files where available. Each record keeps its source, version and retrieval date; matching records from independent sources are merged.",
      why: "The system never claims two sources agree unless both list the facility near the same place.",
      limits: "Registries are incomplete and sometimes out of date, so “no facility nearby” can mean “none mapped”.",
    },
    {
      id: "satellite-provider", title: "Satellite imagery provider", target: "facility-satellite", route: satelliteRoute,
      body: "The facility satellite view uses EOX Sentinel-2 cloudless annual mosaics, fetched by the browser as public map tiles. No credentials are involved and nothing passes through the API, so it works in read-only demo sessions too.",
      how: "Configuration is one optional web setting: VITE_SATELLITE_IMAGERY=off hides the imagery (the view then says it is not configured). The Copernicus credentials used for event imagery analysis are server-side and are not used for this basemap.",
      why: "If the provider is slow, rate-limits or fails, the view says so with a Retry button and never substitutes other imagery; the street map remains available.",
      limits: "EOX cloudless tiles are licensed CC BY-NC-SA 4.0 (non-commercial). A commercial deployment should turn them off or license another provider.",
      needsEvent: true, fallback: NO_EVENT,
    },
    {
      id: "workers", title: "Background workers", target: "system-workers", route: "/system",
      body: "Slow work runs asynchronously in two lanes: bulk (FIRMS polling, enrichment, land-cover backfill, facility sync) and interactive (reports, on-demand imagery analysis). The web app stays responsive while this runs.",
      why: "External providers are slow and rate-limited. Queuing, retries and back-off keep one failing provider from stalling everything.",
    },
    {
      id: "rule-cascade", title: "The classification pipeline", target: "model-versions", route: "/system",
      body: "The classifier of record is the rule cascade (rule-cascade-v1.1): ordered, documented rules over thermal intensity, persistence, facility proximity, land use and land cover, each leaving a trace. Confidence is then scored from named evidence components.",
      why: "Until analysts have adjudicated enough events, most training labels would come from the rules themselves, so a trained model would largely reproduce the rules and its scores would look better than they are.",
      limits: "Confidence scores are weighted evidence scores, not calibrated probabilities, and there is no imagery-based classifier: Sentinel-2 is used for NDVI/NBR change and visual comparison only.",
      terms: ["rules"],
    },
    {
      id: "models", title: "Training and the geographic hold-out", target: "model-versions", route: "/system",
      body: "A LightGBM model can be trained from the labelled events. Evaluation holds out whole geographic areas, so the model is tested on places it has not seen, and a model card records data, metrics and limits.",
      how: "Neighbouring events are nearly identical; a random split would leak them between training and test and overstate accuracy. Spatial blocks prevent that.",
      limits: "A newly trained model is stored inactive. The model list shows which version is in charge; no trained model is presented as active unless an admin activated it.",
      terms: ["holdout"],
    },
    {
      id: "activation", title: "Activation is a governed decision", target: "model-versions", route: "/system",
      body: "Admins can activate or deactivate a trained model. Both actions are audited and trigger re-analysis; deactivation puts the rule cascade back in charge. In demo mode these controls are shown but the server refuses them.",
    },
    {
      id: "alert-admin", title: "Alert rules", target: "alerts-rules", route: "/alerts",
      mobile: { target: "alerts-list" },
      body: "Rules combine class, persistence (class or active days), facility type and distance, minimum triage priority, evidence availability, repeated activity at a facility and a rise against the previous period. Each alert stores the exact calculation, and each delivery its status, including cooldown suppression.",
      limits: "Events older than 72 hours (configurable) never alert, and e-mail is never sent to reserved or local addresses.",
    },
    {
      id: "audit", title: "Audit trail", target: "audit-log", route: "/system",
      body: "Logins, reviews (with the previous and new state), alert-rule changes, watchlist changes, imagery requests, exports and model activation are all recorded with who and when.",
      why: "Being able to show who changed what, and why, is as important as the result itself. Personal data is masked in demo mode.",
    },
    {
      id: "analytics", title: "Analytics from the database", target: "analytics-coverage", route: "/analytics",
      body: "Analytics are aggregate queries with server-side filters for time range, state, district, facility and classification: activity over time, classification, persistence and FRP distributions, facility activity, geography and evidence coverage.",
      limits: "Evidence coverage counts how many events have each evidence stage; it is not a confidence measure. Counts are FIRMS-derived events, not verified incidents.",
    },
    {
      id: "training", title: "Training data from analyst decisions", target: "feedback-loop", route: "/analytics",
      body: "Every analyst decision is stored with the system's label at the time, so disagreements become training signal. Supervisors can export the dataset.",
      why: "No accuracy figure is claimed until there are enough adjudicated labels to measure it honestly.",
      terms: ["holdout"],
    },
    {
      id: "security", title: "Access and security", target: "users-roles", route: "/settings",
      body: "Access requires an account; roles run viewer, analyst, supervisor and admin, and only admins assign roles. Sessions are revocable. Provider keys stay on the server and are never shown in the UI. Demo sessions are read-only, short-lived and audited.",
    },
    {
      id: "health", title: "Integration status", target: "system-config", route: "/system",
      body: "Which integrations are configured, and the state of the database, workers and queue. An evidence platform is only as reliable as the data and services behind it.",
      limits: "“Configured” means credentials are present; source health above shows whether the provider is actually answering.",
    },
  ],
};

export const TOURS = { analyst: ANALYST_TOUR, admin: ADMIN_TOUR } as const;
