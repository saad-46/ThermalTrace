# Repository Audit — ThermalTrace consolidation

**Date:** 2026-09-25 · **Auditor:** platform build team
**Repos audited:**

| # | Repository | HEAD | Commits |
|---|---|---|---|
| R1 | `rayyanafroz/sih-fire-backend` | `f10639d` | 6 |
| R2 | `saad-46/thermal-trace-demo-1` | `4bc32a6` | 2 |

Every "bug" below was confirmed by reading the code. Where it was also confirmed at runtime, that is stated.

---

## R1 — `sih-fire-backend`

### Structure
```
app/main.py            FastAPI app, startup DDL (create_all + raw CREATE TABLE), WebSocket KNN endpoint
app/config.py          pydantic-settings
app/database.py        async SQLAlchemy engine (asyncpg)
app/models.py          User, FireEvent (ORM)
app/schemas.py         Pydantic v2 I/O models
app/oauth2.py          JWT (python-jose) + role guard
app/utils.py           passlib bcrypt
app/ai_service.py      heuristic "classifier", toxicology matrix, spread-prediction model, Gemini call
app/worker.py          FIRMS fetch + classify + insert
app/routers/{auth,users,fires}.py
docker-compose.yml / Dockerfile   + duplicate copies docker-compose.txt, docker_file.txt, woker.txt
```

### Framework & architecture
FastAPI with async SQLAlchemy 2.0 and asyncpg. There are no service or repository layers: routers call ORM and raw SQL directly. Every module uses `sys.path.insert` hacks to import siblings as top-level modules (`import models`), so the package only works with `PYTHONPATH=/app:/app/app`.

### APIs
`POST /login`, `POST /users/`, `POST /fires/trigger-fetch`, `DELETE /fires/purge-emulated`, `GET /fires/sensitive`, `GET /fires/public`, `GET /fires/predict-spread/{id}`, `WS /ws/v1/live-cursor-tracking`. There is no versioned prefix (except on the WebSocket), no pagination, no filters, and no health checks.

### Database
`users` and `fire_events` come from `create_all`. `india_boundary`, `osm_industrial_polygons`, `osm_vegetation_polygons` and `osm_critical_infrastructure` come from raw DDL at startup. There are no migrations. `fire_events` stores lat and lon as floats with **no acquisition date or time**, only `created_at`. GeoAlchemy2 is a dependency but is never used.

### GIS
- The India geofence is a hand-drawn polygon of about 35 vertices, with a bbox fallback if the query fails.
- Nothing ever populates the OSM tables.
- `worker.fetch_spatial_context` queries `planet_osm_polygon`, an osm2pgsql table this project never creates. The query always errors, then falls back to the empty tables.

### ML
There is no model. `AIModelLoader` loads `models/fire_hazard_ensemble.joblib`, which is not in the repo. The fallback is threshold rules that return hard-coded "confidence" values (0.90, 0.89, 0.78, 0.95, 0.94).

### Deployment
There is a Dockerfile and a compose file with a PostGIS service.

### Strengths (worth carrying forward)
- JWT and bcrypt auth structure, with a role enum (`user` / `official` / `admin`) and a `require_official_clearance` dependency pattern.
- `get_live_weather()` uses Open-Meteo with no key. It raises `LiveDataUnavailableError` instead of fabricating weather. That is the right contract.
- It uses `ST_Project` along the wind azimuth, which is reusable for a *potential dispersion direction* vector.
- The KNN nearest-event query (`<->`) is a reasonable idea for map hover.
- The FastAPI and Pydantic v2 foundation is sound.

### Critical security issues
| ID | Severity | Location | Issue |
|---|---|---|---|
| S1 | **Critical** | `routers/auth.py:20`, `oauth2.py:33` | **Hard-coded backdoor account.** The email `rayyan@gmail.com` with password `verystrongpass` always gets an `official` token, and any JWT with `user_id=99999` is accepted without a DB lookup. The credentials are in public git history, so treat them as compromised. |
| S2 | **Critical** | `schemas.UserCreate.role` | **Self-assigned privilege escalation.** Public `POST /users/` accepts `role: "admin"`. |
| S3 | High | `config.py`, `docker-compose.yml` | The default `SECRET_KEY` is committed. If the env var is unset, anyone can forge tokens. |
| S4 | High | `main.py` CORS | `allow_origins=["*"]` combined with `allow_credentials=True`. |
| S5 | Medium | `ai_service.query_llm_incident_synthesis` | The Gemini API key is placed in the URL query string, where it ends up in proxy and access logs. |
| S6 | Medium | `routers/fires.py` | Raw exception strings are returned to clients (`detail=f"...{str(err)}"`). |
| S7 | Low | compose | The FIRMS key placeholder string is treated as a real value, and the Postgres password is committed. |

### Functional bugs
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

### Technical debt / dead code
`docker-compose.txt`, `docker_file.txt` and `woker.txt` duplicate other files. There is also the `purge-emulated` endpoint, `sys.path` hacks throughout, `print` used as logging, unused GeoAlchemy2, a partially unused LLM-key trio (Groq and Anthropic are never called), and a Python 3.11 base image with no pinned dependencies.

---

## R2 — `thermal-trace-demo-1`

### Structure
```
backend/app/api/          FastAPI app (single main.py), schemas
backend/app/core/         settings, psycopg2 cursor helper
backend/app/ingestion/    FIRMS client, Overpass client, orchestrator CLI
backend/app/processing/   spatial join, persistence, rule classifier, orchestrator CLI
backend/tests/            classifier unit tests
frontend/                 React 18 + Vite + TS + MapLibre GL (single page)
infra/postgres/init.sql   schema (docker-entrypoint)
data/demo/                labelled synthetic detections + facilities
docs/                     research, PRD, architecture, roadmap, SIH submission
```

### Framework & architecture
FastAPI with synchronous psycopg2 and raw, parameterized SQL. The layers are clean (ingestion, processing, API), and ingestion and processing run as CLI scripts. There is no scheduler, auth or migrations.

### APIs
`/health`, `/ready`, `/api/v1/events`, `/api/v1/events/{id}`, `/api/v1/facilities`, `/api/v1/map`, `/api/v1/ingestion/runs`, `/api/v1/data-status`.

### Database
`ingestion_runs`, `thermal_detections` (geography points, GIST index, unique natural key), `industrial_facilities` and `event_classifications` (versioned by `classifier_version`). The schema only exists through `docker-entrypoint-initdb.d`, so it is never applied to an existing volume and there is no migration path.

### GIS
PostGIS `geography` is used correctly (distances in metres), with `ST_DWithin` and GIST indexes. Facilities are stored as points only (the Overpass `out center` centroid).

### ML
`rule-cascade-v0.1` is a deterministic cascade with supporting and counter evidence, a versioned classifier, and an explicit `insufficient_evidence` state. There is no trained model and no SHAP.

### Strengths (keep)
- **Honest data-mode handling.** `data_mode` is recorded at ingest and a `source_note` is kept on every row. The UI banner is driven by the database, not guessed.
- The evidence bundle with supporting and counter evidence, plus versioned classifications, is exactly the product principle.
- `normalize_confidence` for MODIS (numeric) versus VIIRS (l/n/h).
- The classifier cascade encodes real domain reasoning (flare night-fraction, multi-month mining recurrence, the agricultural belt plus season).
- The research docs (`01-research.md`) are strong and self-critical.
- A MapLibre map with a data-driven style, and an evidence panel.

### Bugs
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

### Technical debt
- `import json as _json` sits inside a loop.
- `settings.persistence_grid_deg` is unused.
- The frontend is a single page with no router and no loading or error states per panel.

---

## Consolidation decision

**Base:** R2 (architecture, honesty model, evidence design, frontend). R1 is a *donor* for auth, roles and the weather contract.

### KEEP
- R2: evidence structure (supporting/counter/values), `data_mode` and provenance, the classifier cascade *logic* (becomes `RuleCascadeClassifier`, one explicit model), `normalize_confidence`, `geography` + GIST, MapLibre, research docs, synthetic demo dataset (behind `DEMO_MODE`).
- R1: role model, JWT pattern, Open-Meteo client and its no-fabrication error contract, the `ST_Project`-along-wind idea.

### MODIFY
- FIRMS client: all sensors, keyless public NRT CSVs plus the MAP_KEY Area API, retries with backoff, checkpoints, idempotent upsert, full field set (fixes D5, B1–B4).
- OSM client: User-Agent, tiled per-AOI queries around detections, cache, configurable endpoints, correct tag taxonomy (fixes D1, D2, D6).
- Persistence: computed per *event* in set-based SQL, not per detection (D8).
- API: layered routers, a pooled SQLAlchemy engine, bbox and time filters, pagination (D9).

### REWRITE
- Database layer: SQLAlchemy 2.0 + GeoAlchemy2 models with **Alembic** migrations (D11, B11).
- Auth: fresh implementation. There is no backdoor. Roles are server-assigned, the secret key is required outside dev, and passwords are hashed with bcrypt directly (passlib is unmaintained) (S1–S4).
- Processing: event clustering, a persistence engine, facility attribution, a feature pipeline, classifiers (rule + gradient boosting + SHAP), a confidence engine, and an evidence builder.
- Frontend: routed application with a desktop analyst workspace and a mobile shell.

### DELETE
- R1: `FACILITY_TOXIC_MATRIX`, `generate_predictive_spread_report`, the Gemini "incident report", the backdoor login, `purge-emulated`, `planet_osm_*` queries, the `.txt` duplicate files, and the hand-drawn India polygon.
- R2: the silent live-to-demo fallback in both clients. It is replaced by the explicit `DEMO_MODE`. A live failure now produces "source unavailable", not synthetic data.

### MERGE
- Auth, users and roles from R1 are merged into R2's API as `/api/v1/auth/*`.
- R1's weather contract and R2's evidence bundle combine into a `weather` evidence section with "potential dispersion direction".
- R1's WebSocket KNN idea becomes `GET /api/v1/events/nearest` (plain HTTP; the demand does not justify a socket).

---

## Environment verified this session (2026-09-25)
| Check | Result |
|---|---|
| FIRMS keyless regional NRT CSV (`/data/active_fire/noaa-21-viirs-c2/csv/J2_VIIRS_C2_South_Asia_24h.csv`) | **200, real rows** (N21, acq 2026-09-24) |
| Overpass with no User-Agent | **406** (root cause of D1) |
| Overpass with a User-Agent | 200 |
| Copernicus Data Space STAC (`stac.dataspace.copernicus.eu/v1`) | 200 |
| Element84 Earth Search STAC | 200 |
| Open-Meteo | Reachable; returned `"service is overloaded"` on one call, so the weather client must handle provider errors |
| Docker | Installed; daemon not running at session start |
