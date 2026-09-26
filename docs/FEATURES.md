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
| CEA import | NEEDS REAL DATA (transcription) | P1 |
| Multi-source facility consolidation | EXISTS | P1 |
| Facility thermal-activity profile | IMPLEMENTED | P1 |
| Sentinel-2 scene search + previews | EXISTS | P1 |
| Sentinel-2 NDVI / NBR change (before vs after, cloud-masked) | IMPLEMENTED (on demand; honest "unavailable") | P1 |
| Raster land cover (ESA WorldCover 10 m) per event | IMPLEMENTED (enrichment step + backfill) | P1 |
| Before/after swipe comparison | EXISTS | P1 |
| SWIR render (CDSE) | NEEDS CREDENTIAL (`COPERNICUS_CLIENT_ID/SECRET`) | P1 |
| Weather + potential dispersion | EXISTS | P1 |
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
| CEA | Importer implemented; needs a station-level publication. The monthly Installed Capacity report has only capacity totals, so it cannot be imported | same |
| WRI power plants | Implemented, live | same |
| Sentinel-2 | Scene search, previews and NDVI / NBR change implemented; SWIR render needs Copernicus credentials | `integrations/sentinel.py`, `services/imagery.py` |
| Land cover | Implemented (ESA WorldCover 10 m, 2021) | `services/landcover.py` |
| NDVI | Implemented (with NBR) as before/after change, on demand | `services/imagery.py` |
| PostGIS | Implemented (geography columns, GiST indexes, `ST_DWithin`) | migrations 0001–0004 |
| FRP, brightness | Implemented as features and evidence | `processing/features.py` |
| Persistence | Implemented (per-day strip, gaps, recurrence) | `processing/persistence.py` |
| LightGBM + SHAP | Implemented and tested; no model active (no adjudicated labels yet) | `ml/gbm.py` |
| XGBoost | **Not implemented.** LightGBM is the gradient-boosting model used | — |
| Probability calibration, model drift monitoring | **Not implemented** (see docs/ML.md) | — |
| FastAPI, React, MapLibre | Implemented | `backend/`, `frontend/` |
| Automated alerts (in-app, email, Web Push) | Implemented; email needs SMTP, push needs VAPID keys | `services/alerts.py` |
