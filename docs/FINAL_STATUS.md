# Final status — 2026-09-25

Branch `production-platform` of `saad-46/thermal-trace-demo-1`. The branch has not been pushed.

## Live state at hand-off (real data only, `DEMO_MODE=false`)

- **Detections**: 4,737 FIRMS detections from 7 days of NRT data across 5 platforms (Terra, Aqua, S-NPP, NOAA-20, NOAA-21), clustered into 1,351 thermal events.
- **Facilities**: 2,751. Sources are OSM (via enrichment) and the WRI Global Power Plant Database (1,589 Indian plants). 35 facilities are corroborated by two sources.
- **Validated examples**: the Hazira steel/LNG complex (process heat, persistent, 5 platforms, 566 m from AM/NS steel). Jharia/Dhanbad and Angul/Talcher coal fields (coal-seam fire, persistent/recurring, 300–800 m from mapped coal mines).
- **Enrichment**: OSM, weather, Sentinel-2 and geocoding run continuously in the background. Public Overpass takes ≈ 30 s per query, so full enrichment of all events takes hours. It is prioritised by observation count, and analysts can run it on demand for any event ("Enrich").

## COMPLETED

- Repository audit (`REPOSITORY_AUDIT.md`) and architecture (`ARCHITECTURE.md`).
- **Backend**: FastAPI with `/api/v1`, 72 operations, OpenAPI, structured errors, request-id logging, health/ready/metrics, rate limiting, audit log.
- **Database**: PostgreSQL + PostGIS, 40 tables, Alembic migrations (up/down tested), GiST and B-tree indexes, seeded roles and sources.
- **Auth**: JWT with revocable sessions, bcrypt, role hierarchy, admin-only user management. Backdoor and self-escalation removed.
- **NASA FIRMS**:
  - all sensors, keyless NRT polling every 30 min;
  - keyed Area/Country/historical client;
  - retries and backoff, idempotent upserts, runs/errors/checkpoints.
- **OSM Overpass**: bounded, cached, mirror-rotating queries; corrected taxonomy; land context.
- **Facility registries**: WRI GPPD (imported), GEM (tracker auto-detect importer), CEA (template importer). Multi-source consolidation with confidence.
- **Processing**: event clustering, persistence engine, distance-decay attribution, 26-feature traceable pipeline, rule cascade, LightGBM + SHAP (pipeline tested), transparent confidence engine, data-quality grades, evidence bundle with knowledge types, thermal fingerprint, similar events.
- **Enrichment**:
  - Open-Meteo weather at detection time, with the potential dispersion direction;
  - Sentinel-2 L2A scene search with before/during/after/latest and previews;
  - CDSE SWIR render (needs credentials);
  - Nominatim admin geocoding.
- **Background jobs**: Postgres SKIP LOCKED queue, scheduler, interactive/bulk lanes, heartbeats, stale-job recovery.
- **Analyst workflow**: confirm, reclassify, reject, false positive (with reason), escalate, notes and links, assignment, investigation status, training feedback dataset.
- **Alerts**: rule engine (location/radius, watchlist, class, persistence, facility type and distance, confidence, FRP, duration). In-app, email and push channels, with per-delivery status.
- **Watchlists**: facility, point + radius, district and custom polygon targets, with change-since-viewed counts.
- **Reports**: PDF with evidence, confidence components, SHAP, facilities, weather, satellite, timeline, schematic map, analyst assessment and source attribution.
- **Web (desktop)**: all 12 screens.
- **Mobile**: dedicated PWA shell (bottom nav, bottom sheet, swipeable evidence cards, GPS, offline reads, Web Push).
- **Tests**: 40 pytest (27 unit, 2 ML, 11 PostGIS integration) and 2 Playwright acceptance flows (desktop and mobile). Typecheck, lint and production build are clean.
- **Deployment**: backend (non-root) and web (nginx) Dockerfiles, compose stack, CI workflow, env templates for dev and prod.
- **Docs**: ARCHITECTURE, API, DATABASE, DATA_SOURCES, ML, GIS, DEPLOYMENT, SECURITY, TESTING, PRODUCT, REPOSITORY_AUDIT, BUG_FIXES, REQUIRED_CREDENTIALS, README.

## PARTIALLY COMPLETED

- **Trained LightGBM on live data.**
  - The pipeline works end to end in tests (train → save → load → predict → SHAP). There is a UI and CLI trigger, and model cards.
  - It is not yet trained on the live database: training needs ≥ 40 confidently labelled events across ≥ 2 classes, and most events are still waiting for OSM context.
  - Until then, the rule cascade is the classifier of record and the UI says "rules only".
  - Run `python -m app.cli train` once enrichment has progressed or analysts have adjudicated events.
- **Mobile app.** It is an installable PWA sharing the web codebase, not a native Expo/React Native app. Native push on iOS needs the PWA to be installed (iOS 16.4+).
- **Admin boundaries layer.** Admin names come from geocoding. There is no boundary polygon layer on the map (the basemap shows boundaries).
- **Satellite "confirmation".** Automated spectral confirmation (SWIR hot-pixel test) is not implemented. Imagery is available for analyst comparison, and `CONFIRMED` stays unreachable until an imagery check is recorded, by design.

## BLOCKED BY CREDENTIALS

See `REQUIRED_CREDENTIALS.md`.

- `FIRMS_MAP_KEY`: historical backfill (beyond the 7-day NRT window) and the SP archive.
- Copernicus OAuth: SWIR renders.
- SMTP: email alert delivery. Deliveries are currently recorded as `skipped`.
- VAPID: Web Push.
- GEM tracker files: need manual terms acceptance and download.
- CEA data: needs transcription from a named publication.

## BLOCKED BY EXTERNAL API

- **Public Overpass**: ≈ 30 s per query, intermittent 504s and timeouts (15 % error rate observed). This throttles enrichment. Self-hosted Overpass removes the limit.
- **Open-Meteo** returned "service is overloaded" once during the audit. The failure is handled and recorded.

## KNOWN LIMITATIONS

- Only 8 days of FIRMS history are loaded, so "persistent" means persistent within the loaded window (stated in every rationale). Without a MAP_KEY, history accumulates only by polling from now on.
- OSM industrial mapping in India is uneven. Absence of a mapped facility is reported as "not mapped", never as "no facility".
- Land context uses OSM polygons with bounding-box distance, not a land-cover raster (e.g. ESA WorldCover).
- Tenughat-type merges can fail when OSM and registry centroids are more than 1.5 km apart.
- The region of interest is a bounding box, so it includes parts of neighbouring countries. Country comes from geocoding.
- The rate limiter runs inside each API process. Tokens are kept in localStorage (see SECURITY.md).
- The EOX Sentinel-2 cloudless basemap is non-commercial (CC BY-NC-SA).

## NEXT PRIORITIES

1. Add a FIRMS MAP_KEY and backfill 12 months of history, so persistence reflects seasons and years rather than one week.
2. Self-host Overpass (or pre-load an India OSM extract into PostGIS) so every event gets context within minutes.
3. Add a land-cover raster (ESA WorldCover 10 m) as a feature, replacing the OSM polygon heuristic for crop/forest.
4. Implement a SWIR hot-pixel test on Sentinel-2 L2A (CDSE) to enable the `CONFIRMED` state from imagery evidence.
5. Collect analyst adjudications, then train and activate LightGBM, and monitor rule-versus-model agreement and calibration.
6. Add VIIRS Nightfire (after licence review) for flare-specific evidence, and GEM plus CEA imports.
7. Move report storage to object storage, move rate limiting to a shared limiter, and add SSO/MFA.
8. Build a native (Expo) mobile client reusing `src/lib` (API client, types, taxonomy).
