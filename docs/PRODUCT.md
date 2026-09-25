# Product

**ThermalTrace** is an evidence-based geospatial intelligence platform for detecting, classifying, investigating and monitoring thermal anomalies: industrial fires and persistent thermal sources (SIH26162).

## The question set it answers for every event

| Question | Where in the product |
|---|---|
| Where? | Map, admin geocode, coordinates |
| When, and for how long? | First/last seen, active days, span, event evolution chart, replay |
| What type? | Source class and persistence class, each with a probability |
| Which facilities are nearby? | Distance-ranked attribution, multiple sources per facility |
| What satellite data supports it? | Sentinel-2 before/during/after scenes, swipe comparison, optional SWIR |
| What were the weather conditions? | Conditions at detection time, potential dispersion direction |
| What is the historical pattern? | Persistence metrics, repeat-site count, similar events |
| What did the model use? | Rule trace, SHAP contributions, feature values |
| How confident is the system? | Confidence state plus eight weighted components, data-quality grade |
| What information is missing? | "Missing" line, evidence matrix, `missing` evidence rows |
| What did the analyst decide? | Review history, displayed-state override, audit log |

## Principles

1. **No uncertain prediction is shown as fact.**
   - States run from `INSUFFICIENT_EVIDENCE` up to `HIGH_CONFIDENCE`.
   - `CONFIRMED` requires an independent imagery check.
   - Analyst states are displayed separately from system states.
2. **Every item says what kind of knowledge it is**: *observed* (FIRMS), *derived* (ThermalTrace), *external* (OSM, registries, weather, imagery catalogue) or *model*.
3. **Provenance everywhere.** Source, dataset/version, observed time and retrieved time are shown per item, in the Provenance tab and in reports.
4. **No fake data.**
   - Demo data only exists with `DEMO_MODE=true`, and a banner shows while it is loaded.
   - A provider failure shows "source unavailable" and is recorded. It is never substituted.

## Users and workflow

- **Primary users**: geospatial, environmental and industrial-safety analysts.
- **Secondary users**: supervisors, admins, field teams and researchers.

The analyst loop is: detect → investigate (map + evidence) → review (confirm / reclassify / reject / false positive / escalate, plus notes and links) → act (alert rule, watchlist, PDF report) → feed back (adjudicated labels retrain the model; false-positive reasons are aggregated).

## Screens

**Desktop:**

- Overview
- Live map (primary workspace: map + evidence panel)
- Events (queues: all, needs review, persistent, industrial)
- Event investigation
- Facilities and facility history
- Alerts (inbox + rules)
- Watchlists
- Reports
- Analytics (trends, persistent sources, district and facility-type hotspots, sensor distribution and multi-sensor agreement, night share, feedback loop)
- Data sources (health, runs, jobs)
- System health (workers, queue, models + feature pipeline, audit)
- Settings (account, theme, push, users and roles)

**Mobile (PWA):**

- Bottom navigation: Map · Events · Alerts · Watchlist · More.
- Full-screen map with a draggable bottom sheet.
- Swipeable evidence cards.
- "Near me" GPS.
- Analyst review.
- Offline reads of recent events and alerts.
- Web Push.

## Differentiating features built

| Feature | Status |
|---|---|
| Thermal fingerprint | ✅ intensity, persistence, sensor agreement, facility proximity, recurrence, night share + context |
| Persistent source watch | ✅ Map side panel, Overview, Analytics ("ranked by evidence, not a threat ranking") |
| Event evolution | ✅ daily detections and peak FRP chart, classification history |
| Multi-sensor agreement | ✅ evidence item + confidence component + analytics |
| Satellite confirmation score | ✅ satellite component (clear/cloudy/none/unsearched); CONFIRMED gated on imagery check |
| Analyst feedback loop / training dataset | ✅ `analyst_reviews` + 3× weight in training |
| False-positive intelligence | ✅ reasons captured and aggregated |
| Similar events | ✅ fingerprint-distance search |
| Investigation replay | ✅ time slider over the event's detections on the map |
| Evidence confidence matrix | ✅ |
