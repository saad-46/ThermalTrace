# Features

Status of every capability on `main`. Statuses: **EXISTS** (built and tested), **IMPLEMENTED** (added in the consolidation phase), **NEEDS CREDENTIAL / NEEDS REAL DATA** (implemented; activates when configured), **DEFERRED**, **REJECTED**.

| Feature | Status | Priority |
|---|---|---|
| FIRMS NRT ingestion (MODIS, S-NPP, NOAA-20, NOAA-21) | EXISTS | P0 |
| FIRMS historical / Area / Country API | NEEDS CREDENTIAL (`FIRMS_MAP_KEY`) | P0 |
| Ingestion runs, errors, checkpoints, dedupe | EXISTS | P0 |
| Event clustering | EXISTS | P0 |
| Persistence engine with metrics | IMPLEMENTED (per-day strip added) | P0 |
| Industrial vs natural classification | EXISTS | P0 |
| Insufficient-evidence state | EXISTS | P0 |
| Confidence engine (8 components) | EXISTS | P0 |
| Qualitative confidence decomposition (Strong / Weak / Unavailable) | IMPLEMENTED | P1 |
| Data-quality grade | EXISTS | P1 |
| Facility attribution (distance-ranked) | EXISTS | P0 |
| Local facility index (scheduled tile sync) | IMPLEMENTED | P0 |
| OSM Overpass integration | EXISTS | P0 |
| WRI GPPD import | EXISTS | P1 |
| GEM tracker import | NEEDS REAL DATA (manual download) | P1 |
| CEA import (official List of Power Stations PDF) | IMPLEMENTED (see CEA_REGISTRY.md) | P1 |
| Multi-source facility consolidation | EXISTS | P1 |
| Facility thermal-activity profile | IMPLEMENTED | P1 |
| Facility card on map click → facility details (relationship to the event, provenance, registry ids, map with 2 / 10 km rings, timeline, paginated history) | IMPLEMENTED (desktop popup, phone bottom sheet) | P1 |
| Sentinel-2 scene search + previews | EXISTS; automatic for top-priority events (context backfill) and on demand (*Search Sentinel-2 imagery*); before/after windows fixed 27 Sep 2026 | P1 |
| Sentinel-2 NDVI / NBR change (before vs after, cloud-masked) | IMPLEMENTED (on demand, offered only when a clear scene exists on both sides; dNBR sign fixed and dark-surface guard added 27 Sep 2026) | P1 |
| Raster land cover (ESA WorldCover 10 m) per event | IMPLEMENTED (enrichment step + backfill) | P1 |
| Before/after swipe comparison | EXISTS | P1 |
| SWIR render (CDSE) | NEEDS CREDENTIAL (`COPERNICUS_CLIENT_ID/SECRET`) | P1 |
| Weather + potential dispersion | EXISTS; automatic for top-priority events and on demand (*Retrieve weather*); no data vs provider failure distinguished | P1 |
| Weather in the evidence timeline | IMPLEMENTED | P2 |
| Admin geocoding | EXISTS (health tracking fixed) | P1 |
| Offline place names for every event ("Near Dhanbad, Jharkhand · 1 km" beside the coordinates), searchable | IMPLEMENTED | P1 |
| Evidence bundle with knowledge types | EXISTS | P0 |
| Evidence chain view | IMPLEMENTED | P1 |
| Evidence confidence matrix | EXISTS | P1 |
| Triage priority + "why prioritised" | IMPLEMENTED | P1 |
| Rule trace + SHAP explanation | EXISTS | P1 |
| LightGBM training pipeline | EXISTS; not trained on live labels | P1 |
| Model lifecycle: train inactive → admin activates / deactivates (audited) | IMPLEMENTED | P1 |
| Rule cascade raster land-cover fallback (`rule-cascade-v1.1`, capped) | IMPLEMENTED | P1 |
| Training feedback dataset export | IMPLEMENTED | P0 |
| Analyst review (confirm / reclassify / reject / FP / escalate) | EXISTS | P0 |
| Notes / evidence links / assignment | EXISTS | P1 |
| Global search | IMPLEMENTED | P1 |
| Advanced filters (class, persistence, state, sensor, FRP, facility type, priority) | EXISTS (+ priority) | P1 |
| Land-cover filter | DEFERRED (OSM land context too sparse to filter honestly) | P2 |
| Map ↔ list filter sync | DEFERRED | P2 |
| Viewport loading, clustering, heatmap | EXISTS | P0 |
| Attribution radius rings | IMPLEMENTED | P2 |
| Investigation workspace: status strip, 13 evidence stages (Available / Pending / No data / Not requested / Failed / Requires analyst review) with source, time, contribution and limitation | IMPLEMENTED (advanced phase; final test pass pending) | P0 |
| Evidence availability (x / 13 stages; not confidence) on the event, in alerts and in analytics | IMPLEMENTED (advanced phase) | P1 |
| Event timeline with playback (stored timestamps only, explicit gaps) | IMPLEMENTED (advanced phase) | P1 |
| Activity chart: FRP / brightness / detections / persistence with hover | IMPLEMENTED (advanced phase) | P1 |
| Explainable classification (interpretation, why, evidence values, limitations, SHAP caveat) | IMPLEMENTED (advanced phase) | P1 |
| Activity cluster around an event (radius and window, extent, facilities, distributions) | IMPLEMENTED (advanced phase) | P1 |
| Recurring activity (location, facility, global list; observed activity, not risk) | IMPLEMENTED (advanced phase) | P1 |
| Similar events with similarity reasons; side-by-side event comparison (no ranking) | IMPLEMENTED (advanced phase) | P1 |
| Facility intelligence profile (activity summary, week / month comparison, thermal profile, source agreement, event relationship with temporal context and evidence) | IMPLEMENTED (advanced phase) | P1 |
| Alert conditions: persistence days, evidence stages, repeated activity within a distance, configurable increase factor and window; per-alert "Why was I alerted?" | IMPLEMENTED (advanced phase) | P1 |
| Dashboard and analytics with server-side filters (24 h / 7 / 30 / 90 days / custom, state, district, facility, classification) | IMPLEMENTED (advanced phase) | P1 |
| Live system status panel and data-source detail drawer | IMPLEMENTED (advanced phase) | P1 |
| Review workflow: mark reviewed, request more evidence, reviewer assignment, review history with previous / new status | IMPLEMENTED (advanced phase) | P1 |
| Investigation report sections (summary, thermal, spatial, environmental, explainability, limitations, audit, disclaimer) and read-only shareable view | IMPLEMENTED (advanced phase) | P1 |
| Map layer groups (density, industrial, quarries, roads, rivers, districts, states, OSM land cover) and dynamic legend | IMPLEMENTED (advanced phase) | P2 |
| Unified search with registry ids and states | IMPLEMENTED (advanced phase) | P2 |
| India-wide basemap hierarchy (roads, districts, industrial areas and labels by zoom, from the basemap's own tiles) | IMPLEMENTED | P2 |
| Replay | EXISTS | P2 |
| Similar events | EXISTS | P2 |
| Alert rules + deliveries | EXISTS | P0 |
| Alert conditions: triage priority, repeated facility activity, facility activity increase | IMPLEMENTED | P1 |
| Audit trail with previous / new state (reviews, alert-rule edits, watchlists, model activation) | IMPLEMENTED | P1 |
| Alert cooldown / delivery suppression | IMPLEMENTED | P0 |
| Alert deduplication | EXISTS | P0 |
| Email / push | NEEDS CREDENTIAL (SMTP / VAPID) | P1 |
| Watchlists (facility / point / district / polygon) | EXISTS | P1 |
| PDF reports | EXISTS | P1 |
| Analytics (trends, hotspots, sensors, feedback) | EXISTS | P1 |
| Data sources + ingestion health | EXISTS (+ facility index panel) | P1 |
| Admin: users, roles, models, audit, workers | EXISTS | P1 |
| Demo mode isolation | EXISTS | P0 |
| Mobile PWA (bottom nav, sheet, cards, GPS) | EXISTS (+ search, priority queue) | P1 |
| Tablet layout | IMPLEMENTED | P1 |
| Guided exploration: Explore as Analyst / Admin, read-only demo sessions with guided tours (desktop, tablet, phone) | IMPLEMENTED | P1 |
| Landing page with sign-in, live public aggregates (figures, source states, 30-day activity grid), honest fallbacks | IMPLEMENTED | P1 |
| Frontend component tests | IMPLEMENTED | P1 |
| E2E desktop / tablet / mobile | EXISTS (+ tablet, guards) | P0 |
| Per-token rate limiting | IMPLEMENTED | P1 |
| Table accessibility semantics | IMPLEMENTED | P1 |
| Native mobile app | DEFERRED (no native code exists in any source; PWA retained) | P2 |

Rejected during consolidation (demo-only or not evidence-based): a hand-weighted classifier whose outputs were not probabilities, a guided walkthrough over synthetic data, and a marketing card. See `PROJECT_HISTORY.md`.


## Presentation claims versus implementation

Checked against the code on 2026-09-26.

| Claim | Status | Where |
|---|---|---|
| NASA FIRMS (MODIS, VIIRS S-NPP / NOAA-20 / NOAA-21) | Implemented, live | `integrations/firms.py` |
| FIRMS history / backfill | Implemented; needs `FIRMS_MAP_KEY` | `ingest-historical`, `firms_historical` job |
| OpenStreetMap facilities and land use | Implemented, live | `integrations/overpass.py`, `services/facility_sync.py` |
| Global Energy Monitor | Implemented; Global Coal Plant Tracker (July 2026, CC BY 4.0) imported locally: 662 Indian plant locations, 245 corroborated by WRI or OSM. Other trackers need their files | `services/registries_import.py` |
| CEA | Implemented: the official *List of Power Stations* PDF is parsed and stations matched to located facilities (docs/CEA_REGISTRY.md) | `services/cea_registry.py` |
| WRI power plants | Implemented, live | same |
| Sentinel-2 | Scene search, previews and NDVI / NBR change implemented and live (keyless Earth Search); SWIR render needs Copernicus credentials | `integrations/sentinel.py`, `services/imagery.py` |
| Weather | Implemented and live (Open-Meteo, keyless) | `integrations/weather.py` |
| Land cover | Implemented (ESA WorldCover 10 m, 2021) | `services/landcover.py` |
| NDVI | Implemented (with NBR) as before/after change, on demand; no finding over dark surfaces | `services/imagery.py` |
| PostGIS | Implemented (geography columns, GiST indexes, `ST_DWithin`) | migrations 0001–0004 |
| FRP, brightness | Implemented as features and evidence | `processing/features.py` |
| Persistence | Implemented (per-day strip, gaps, recurrence) | `processing/persistence.py` |
| LightGBM + SHAP | Implemented and tested; no model active (no adjudicated labels yet) | `ml/gbm.py` |
| XGBoost | **Not implemented.** LightGBM is the gradient-boosting model used | — |
| Probability calibration, model drift monitoring | **Not implemented** (see docs/ML.md) | — |
| FastAPI, React, MapLibre | Implemented | `backend/`, `frontend/` |
| Automated alerts (in-app, email, Web Push) | Implemented; email needs SMTP, push needs VAPID keys | `services/alerts.py` |
