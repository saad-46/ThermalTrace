# Master feature matrix

**Legend.** Prod = production before this phase. Proto = ThermalTrace Prototype. Demo = thermal-trace-demo-1. Status is the state **after** consolidation.

| Feature | Production | Prototype | Demo | Best implementation | Status | Priority |
|---|---|---|---|---|---|---|
| FIRMS NRT ingestion (MODIS, S-NPP, NOAA-20, NOAA-21) | Real, keyless files, idempotent | Mock | MAP_KEY only, silent demo fallback | Production | EXISTS | P0 |
| FIRMS historical / Area / Country API | Client implemented | — | Area API only | Production | NEEDS CREDENTIAL (`FIRMS_MAP_KEY`) | P0 |
| Ingestion runs, errors, checkpoints, dedupe | Yes | — | Runs only | Production | EXISTS | P0 |
| Event clustering | Yes | — (pre-built anomalies) | No (per detection) | Production | EXISTS | P0 |
| Persistence engine with metrics | Yes | 7-period demo strip | Dataset-wide proxy | Production + Proto visual | IMPLEMENTED (per-day strip added) | P0 |
| Industrial vs natural classification | Rule cascade (8 classes) | Hand-weighted demo labels | Cascade v0.1 | Production | EXISTS | P0 |
| Insufficient-evidence state | Yes | "Unclassified" | Yes | Production | EXISTS | P0 |
| Confidence engine (8 components) | Yes | Sum of contributions | Band only | Production | EXISTS | P0 |
| Qualitative confidence decomposition (Strong / Weak / Unavailable) | Numeric only | — | — | New | IMPLEMENTED | P1 |
| Data-quality grade | Yes | — | — | Production | EXISTS | P1 |
| Facility attribution (distance-ranked) | Yes | Single nearest (mock) | Nearest within 5 km | Production | EXISTS | P0 |
| Local facility index (scheduled tile sync) | Per-cell Overpass | — | Whole-India query (timed out) | New | IMPLEMENTED | P0 |
| OSM Overpass integration | Yes (UA, bounded) | Stub | Broken (no UA) | Production | EXISTS | P0 |
| WRI GPPD import | Imported (1,589) | — | — | Production | EXISTS | P1 |
| GEM tracker import | Importer | — | — | Production | NEEDS REAL DATA (manual download) | P1 |
| CEA import | Template importer | — | — | Production | NEEDS REAL DATA (transcription) | P1 |
| Multi-source facility consolidation | Yes | — | — | Production | EXISTS | P1 |
| Facility thermal-activity profile | Event list + weekly | — | — | New | IMPLEMENTED | P1 |
| Sentinel-2 scene search + previews | Earth Search | Placeholder card | — | Production | EXISTS | P1 |
| Before/after swipe comparison | Yes | — | — | Production | EXISTS | P1 |
| SWIR render (CDSE) | Implemented | — | — | Production | NEEDS CREDENTIAL (`COPERNICUS_CLIENT_ID/SECRET`) | P1 |
| Weather + potential dispersion | Yes | — | — | Production | EXISTS | P1 |
| Weather in the evidence timeline | No | — | — | New | IMPLEMENTED | P2 |
| Admin geocoding | Nominatim | Region label (mock) | — | Production | EXISTS (health tracking fixed) | P1 |
| Evidence bundle with knowledge types | Yes | — | Supporting/counter | Production | EXISTS | P0 |
| Evidence chain view | — | Yes (mock) | — | Proto concept on real data | IMPLEMENTED | P1 |
| Evidence confidence matrix | Yes | — | — | Production | EXISTS | P1 |
| Triage priority + "why prioritised" | — | Yes (mock) | — | Proto concept, real evidence | IMPLEMENTED | P1 |
| Rule trace + SHAP explanation | Yes | Feature contributions (mock) | — | Production | EXISTS | P1 |
| LightGBM training pipeline | Yes (tested) | — | — | Production | EXISTS; not trained on live labels | P1 |
| Training feedback dataset export | Stored, not exportable | — | — | New | IMPLEMENTED | P0 |
| Analyst review (confirm / reclassify / reject / FP / escalate) | Yes | Local status + notes | — | Production | EXISTS | P0 |
| Notes / evidence links / assignment | Yes | Local notes | — | Production | EXISTS | P1 |
| Global search | Events page only | Client-side | — | New server-side | IMPLEMENTED | P1 |
| Advanced filters (class, persistence, state, sensor, FRP, facility type, priority) | Yes | Yes (mock) | Class / band | Production | EXISTS (+ priority) | P1 |
| Land-cover filter | — | Yes (mock) | — | — | DEFERRED (OSM land context too sparse to filter honestly) | P2 |
| Map ↔ list filter sync | Separate state | Shared store | — | — | DEFERRED | P2 |
| Viewport loading, clustering, heatmap | Yes | Full array | Full load | Production | EXISTS | P0 |
| Attribution radius rings | — | 8 km buffer (mock) | — | Proto concept | IMPLEMENTED | P2 |
| Replay | Yes | — | — | Production | EXISTS | P2 |
| Similar events | Yes | — | — | Production | EXISTS | P2 |
| Alert rules + deliveries | Yes | Status tabs over mock | — | Production | EXISTS | P0 |
| Alert cooldown / delivery suppression | — | — | — | New | IMPLEMENTED | P0 |
| Alert deduplication | (rule, event) unique | — | — | Production | EXISTS | P0 |
| Email / push | Implemented | — | — | Production | NEEDS CREDENTIAL (SMTP / VAPID) | P1 |
| Watchlists (facility / point / district / polygon) | Yes | — | — | Production | EXISTS | P1 |
| PDF reports | Yes | Browser print | — | Production | EXISTS | P1 |
| Analytics (trends, hotspots, sensors, feedback) | Yes | Recharts over mock | — | Production | EXISTS | P1 |
| Data sources + ingestion health | Yes | Static page | Banner | Production | EXISTS (+ facility index panel) | P1 |
| Admin: users, roles, models, audit, workers | Yes | — | — | Production | EXISTS | P1 |
| Demo mode isolation | `DEMO_MODE`, banner | Always demo | Silent fallback | Production | EXISTS | P0 |
| Guided demo walkthrough | — | Yes | — | — | REJECTED (demo-only) | P3 |
| "Why ThermalTrace" marketing card | — | Yes | — | — | REJECTED | P3 |
| Prototype hand-weighted classifier | — | Yes | — | — | REJECTED (not probabilities) | — |
| Mobile PWA (bottom nav, sheet, cards, GPS) | Yes | Responsive only | — | Production | EXISTS (+ search, priority queue) | P1 |
| Tablet layout | Cramped | — | — | New icon rail | IMPLEMENTED | P1 |
| Frontend component tests | None | None | None | New (Vitest) | IMPLEMENTED | P1 |
| E2E desktop / tablet / mobile | Desktop + mobile | — | Shell smoke | Production | EXISTS (+ tablet, guards) | P0 |
| Per-token rate limiting | Per IP | — | — | New | IMPLEMENTED | P1 |
| Table accessibility semantics | Missing | — | — | Fixed | IMPLEMENTED | P1 |
| Native mobile app | — | — | — | — | DEFERRED (no native code exists in any source; PWA retained) | P2 |
