# Project history

How the current codebase came to be. The source repositories are no longer needed to build, run or test ThermalTrace. This document records what was taken from each, what was fixed, and what was rejected, so that nothing depends on them.

## Timeline

| Date | Phase | Outcome |
|---|---|---|
| 2026-09-05 | Research | Problem statement (SIH26162) verified, data sources and method chosen (`RESEARCH.md`, `SIH-SUBMISSION.md`). |
| 2026-09-25 | Platform build | The platform was rebuilt from two public repositories (below): FastAPI + PostGIS + Alembic backend, job workers, React/MapLibre web app and PWA. First push to `saad-46/ThermalTrace` (`876f229`). |
| 2026-09-25 | Consolidation | A local UI prototype and a copy of the demo repository were audited feature by feature. Valuable ideas were rebuilt on real data (triage priority, global search, evidence chain, persistence strip, attribution rings); the rest was rejected with a reason (below). Branch `production-consolidation`. |
| 2026-09-25 | Final cleanup | Repository sanitised and consolidated (`PRE_CLEANUP_INVENTORY.md`, `FINAL_REPOSITORY_INVENTORY.md`). |

## Source repositories

| ID | Repository | HEAD audited | Role |
|---|---|---|---|
| R1 | `rayyanafroz/sih-fire-backend` | `f10639d` | Donor: role model, JWT pattern, the Open-Meteo "no fabrication" contract, the wind-projection idea. |
| R2 | `saad-46/thermal-trace-demo-1` | `4bc32a6` | Base: honest `data_mode`, evidence supporting/counter model, rule-cascade logic (now `rule-cascade-v1.0`), MapLibre map, research docs, labelled synthetic dataset (`data/demo/`). |

The IDs below (`R1-S1`, `R1-B5`, `R2-D1` …) are the ones used in `BUG_FIXES.md`.

## R1 — security issues (none migrated)

| ID | Severity | Location | Issue |
|---|---|---|---|
| S1 | **Critical** | `routers/auth.py:20`, `oauth2.py:33` | **Hard-coded backdoor account.** A fixed email and password (redacted here; public in that repository's history) always get an `official` token, and any JWT with `user_id=99999` is accepted without a DB lookup. The credentials are in public git history, so treat them as compromised. |
| S2 | **Critical** | `schemas.UserCreate.role` | **Self-assigned privilege escalation.** Public `POST /users/` accepts `role: "admin"`. |
| S3 | High | `config.py`, `docker-compose.yml` | The default `SECRET_KEY` is committed. If the env var is unset, anyone can forge tokens. |
| S4 | High | `main.py` CORS | `allow_origins=["*"]` combined with `allow_credentials=True`. |
| S5 | Medium | `ai_service.query_llm_incident_synthesis` | The Gemini API key is placed in the URL query string, where it ends up in proxy and access logs. |
| S6 | Medium | `routers/fires.py` | Raw exception strings are returned to clients (`detail=f"...{str(err)}"`). |
| S7 | Low | compose | The FIRMS key placeholder string is treated as a real value, and the Postgres password is committed. |

The R1 credential is public in that repository's history. It was never used by ThermalTrace. Rotate it anywhere it was reused.

## R1 — functional bugs

| ID | Location | Bug | Impact |
|---|---|---|---|
| B1 | `worker.py:10,122` | The FIRMS URLs are malformed: `"https://nasa.gov{KEY}/VIIRS_NOAA20_NRT/..."` and `NASA_FIRMS_OPEN_LIVE_FEED = "https://nasa.gov"`. | **Ingestion can never retrieve FIRMS data.** The HTML response fails the `"latitude" in text` check, so the worker returns silently. The pipeline has never produced a real record in this state. |
| B2 | `worker.py` | Only VIIRS NOAA-20 is used, and a hard cap of 150 rows is applied. | MODIS, NOAA-21 and S-NPP are ignored, and data is truncated arbitrarily. |
| B3 | `models.FireEvent` | No `acq_date`, `acq_time`, scan, track or daynight columns. | Temporal persistence is impossible. |
| B4 | `worker.py` | No deduplication. Every trigger re-inserts the same detections. | Duplicates inflate every count. |
| B5 | `worker.fetch_spatial_context` | Queries the nonexistent `planet_osm_polygon`, and the fallback tables are empty. | Spatial context is always `none`. |
| B6 | `ai_service.calculate_spatial_features` | On any exception it returns **fabricated** distances (5000 m and 1200 m). When the tables are empty it silently returns a 50 km sentinel. | Features are fake, and so is the danger level. |
| B7 | `ai_service.classify_and_assess_hazard` | `is_persistent_anomaly` is derived from industrial proximity, not time. | Persistence is mislabeled. |
| B8 | `ai_service` | Constant "inference_confidence" values are presented as model confidence. | False certainty. |
| B9 | `ai_service.FACILITY_TOXIC_MATRIX` | Specific chemical releases and health impacts (for example "Benzene, H2S… acute pulmonary edema") are asserted from a substring match on OSM tags. | **Unsupported claims presented as fact.** This has to be removed. |
| B10 | `ai_service.generate_predictive_spread_report` | An invented spread formula (`0.06 + frp*0.0035`, `exp(0.042*wind)`) produces a "24-hour projected firehead" and a "toxic plume radius". | Pseudo-scientific output with no validation. It is also meaningless for industrial flares. Remove it. |
| B11 | `main.lifespan` | Startup DDL exceptions are swallowed by `print`. | The app boots with a broken schema. |
| B12 | `database.run_background_pipeline` | Exceptions are printed and discarded, and no run record is written. | Failed ingestions are invisible. |

## R2 — bugs

| ID | Location | Bug | Impact |
|---|---|---|---|
| D1 | `osm_client.fetch_live` | **No `User-Agent` header.** overpass-api.de returns **HTTP 406**. *Verified live 2026-09-25.* | `fetch_live` returns None, so it **silently falls back to synthetic demo facilities even when FIRMS is live**. That is the exact live/demo mixing the module docstring says it prevents. |
| D2 | `osm_client._build_query` | One Overpass query for every `landuse=industrial` way in all of India, with `timeout:60`. | Times out or is rejected by the server, and also leads to the D1 fallback. |
| D3 | `run_ingestion.ingest_facilities` | No uniqueness on `(source, osm_id)`. | Every run re-inserts every facility, so nearest-facility results become duplicated. |
| D4 | `run_ingestion` | A run is marked `success` even when every row is rejected, and fetch failures never create a `failed` run. | Ingestion health is misreported. |
| D5 | `firms_client` | Requires a MAP_KEY and ignores the keyless public regional NRT CSVs. It has no retry, no backoff, and no scan/track/brightness/version/bright_t31. | Live data needs signup it doesn't strictly require, and the stored record is incomplete. |
| D6 | `_TAG_TO_TYPE` | `man_made=works` is mapped to `refinery`. | Any factory becomes a "refinery", which then drives the flare branch. **This is a misclassification.** |
| D7 | Processing | Every detection is classified independently. There is no event clustering. | The map shows raw pixels as "events", and the same fire is classified N times. |
| D8 | `persistence.compute_persistence` | Four spatial queries per detection, so the total is O(N·queries). The opportunity-days proxy is dataset-wide. | Unusable at live volume (thousands of detections per day in the India season). |
| D9 | `api.main` | A new psycopg2 connection is opened per request (no pool). `/map` returns up to 5,000 features with no bbox or time filter. | Latency and payload size. |
| D10 | `api.main` | No auth. CORS uses `allow_methods=*`. | Acceptable for a demo only. |
| D11 | `init.sql` | Schema is applied only on a fresh volume. | Schema drift on existing deployments. |

## Consolidation decision

**Base:** R2 (architecture, honesty model, evidence design, frontend). R1 is a *donor* for auth, roles and the weather contract.

#### KEEP
- R2: evidence structure (supporting/counter/values), `data_mode` and provenance, the classifier cascade *logic* (becomes `RuleCascadeClassifier`, one explicit model), `normalize_confidence`, `geography` + GIST, MapLibre, research docs, synthetic demo dataset (behind `DEMO_MODE`).
- R1: role model, JWT pattern, Open-Meteo client and its no-fabrication error contract, the `ST_Project`-along-wind idea.

#### MODIFY
- FIRMS client: all sensors, keyless public NRT CSVs plus the MAP_KEY Area API, retries with backoff, checkpoints, idempotent upsert, full field set (fixes D5, B1–B4).
- OSM client: User-Agent, tiled per-AOI queries around detections, cache, configurable endpoints, correct tag taxonomy (fixes D1, D2, D6).
- Persistence: computed per *event* in set-based SQL, not per detection (D8).
- API: layered routers, a pooled SQLAlchemy engine, bbox and time filters, pagination (D9).

#### REWRITE
- Database layer: SQLAlchemy 2.0 + GeoAlchemy2 models with **Alembic** migrations (D11, B11).
- Auth: fresh implementation. There is no backdoor. Roles are server-assigned, the secret key is required outside dev, and passwords are hashed with bcrypt directly (passlib is unmaintained) (S1–S4).
- Processing: event clustering, a persistence engine, facility attribution, a feature pipeline, classifiers (rule + gradient boosting + SHAP), a confidence engine, and an evidence builder.
- Frontend: routed application with a desktop analyst workspace and a mobile shell.

#### DELETE
- R1: `FACILITY_TOXIC_MATRIX`, `generate_predictive_spread_report`, the Gemini "incident report", the backdoor login, `purge-emulated`, `planet_osm_*` queries, the `.txt` duplicate files, and the hand-drawn India polygon.
- R2: the silent live-to-demo fallback in both clients. It is replaced by the explicit `DEMO_MODE`. A live failure now produces "source unavailable", not synthetic data.

#### MERGE
- Auth, users and roles from R1 are merged into R2's API as `/api/v1/auth/*`.
- R1's weather contract and R2's evidence bundle combine into a `weather` evidence section with "potential dispersion direction".
- R1's WebSocket KNN idea becomes `GET /api/v1/events/nearest` (plain HTTP; the demand does not justify a socket).

## Considered and not migrated (consolidation phase)

| Feature | Source | Reason |
|---|---|---|
| Hand-weighted classification engine | UI prototype | Its outputs are not probabilities. Production's cascade and confidence engine are stricter and evidence-based. |
| Guided demo walkthrough | UI prototype | Meaningful only over synthetic data. |
| "Why ThermalTrace" card | UI prototype | Marketing, not functionality. |
| `localStorage` analyst state | UI prototype | Production persists this server-side with an audit trail. |
| Next.js / Zustand / Recharts / Tailwind | UI prototype | These would duplicate production's stack. No capability gap. |
| Land-cover filter | UI prototype | OSM land context covers too few events. It returns with a land-cover raster (roadmap). |
| Demo vertical slice code | R2 | Superseded. It was the base of the production rebuild. |
