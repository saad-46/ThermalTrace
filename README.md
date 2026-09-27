# ThermalTrace

**Evidence-based detection, classification and monitoring of industrial fires and persistent thermal sources.**

ThermalTrace turns raw NASA FIRMS thermal anomalies into investigated events. For each event it shows:

- the nearby facilities;
- how persistent the heat source is;
- the weather and satellite context;
- a transparent classification with an honest confidence;
- an analyst workflow, alerts and reports.

Every figure it shows comes from a real, attributed source.

![Live map with an event under investigation](docs/screenshots/02-map-event-selected.png)

## Smart India Hackathon context

Built for **SIH26162** (NTRO): *AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources Using NASA FIRMS, OSM and Satellite Data.*

NASA FIRMS reports thousands of thermal anomalies a day over South Asia. A bare hot pixel does not tell an analyst what it is, whether it is new, or whether it matters. It could be:

- a refinery flare;
- a steel furnace;
- a coal seam that has burned for decades;
- a crop-residue fire;
- an industrial accident.

The problem statement asks for two things: classify industrial versus natural fires, and present them on a GIS map. The research behind the approach is in [docs/RESEARCH.md](docs/RESEARCH.md), and the pitch material is in [docs/SIH-SUBMISSION.md](docs/SIH-SUBMISSION.md).

## What it does

For every thermal event ThermalTrace answers **where, when, how long, what type, which facilities are nearby, what the satellite and weather data show, what the history is, what the model used, how confident the system is, what is missing, and what the analyst decided**. Every answer carries its provenance.

The processing chain:

```
FIRMS (MODIS + VIIRS, all satellites)
  → normalisation
  → spatio-temporal clustering
  → facility context (OSM · WRI · GEM · CEA)
  → persistence
  → weather
  → Sentinel-2 scenes
  → features
  → rule cascade (+ LightGBM/SHAP when trained)
  → confidence
  → evidence bundle
  → analyst review
  → alerts, watchlists, PDF reports
```

The system never presents uncertain output as fact:

- A classification reads, for example, *Industrial process heat — High confidence (0.73) — not independently verified*.
- `CONFIRMED` requires an imagery check.
- Weak evidence is shown as **Insufficient evidence — manual review required**.

## Architecture

```
FIRMS · Overpass · WRI/GEM/CEA · Sentinel-2 STAC · Open-Meteo · Nominatim
                 │ (retries, backoff, cache, health tracking)
     worker (bulk lane + scheduler) · worker (interactive lane)   ← Postgres SKIP LOCKED job queue
                 │
        PostgreSQL 16 + PostGIS 3.4 (Alembic, 43 tables, migrations 0001–0009)
                 │
      FastAPI /api/v1 (JWT, roles, audit, rate limits)
                 │
   React + MapLibre web app: desktop analyst workspace · tablet · mobile PWA
```

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, GeoAlchemy2, Alembic, psycopg 3, httpx |
| Data and ML | PostgreSQL 16 + PostGIS 3.4 + pg_trgm, LightGBM, SHAP, scikit-learn, ReportLab, matplotlib |
| Frontend | React 18, TypeScript, Vite 5, MapLibre GL 6, TanStack Query, React Router 7 |
| Testing | pytest (unit, ML, PostGIS integration), Vitest + Testing Library, Playwright (desktop, tablet, mobile) |
| Delivery | Docker, docker compose, GitHub Actions |

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Features

- **Live map.** Viewport-bounded loading, clustering, a facility layer, event footprint and pixels, attribution rings, potential dispersion direction, replay and a Sentinel-2 basemap.
- **Investigation.** Summary answers, evidence chain, evidence confidence matrix, confidence components, thermal fingerprint, distance-ranked facilities, raster land cover (ESA WorldCover), a per-day persistence strip, before/after satellite swipe, Sentinel-2 NDVI / NBR change, weather, model evidence (rule trace and SHAP) and full provenance.
- **Triage and search.** An explainable triage priority orders the review queue; it is not a risk score. Global search covers event IDs, districts, facilities, classifications and coordinates.
- **Analyst workflow.** Confirm, reclassify, reject, false positive or escalate, with notes, evidence links and assignment. Every decision feeds the training dataset (CSV/JSON export, audited).
- **Monitoring.** Alert rules on class, persistence, facility proximity, triage priority, repeated activity at a facility, or an increase in facility activity, with cooldowns (in-app, email and push delivery); watchlists for facilities, points, districts and polygons.
- **Reporting.** PDF investigation reports with source attribution.
- **Operations.** Data-source health, local facility-index coverage, ingestion runs, jobs, workers, model cards, audit log, and user and role administration.
- **Mobile.** An installable PWA with bottom navigation, a map bottom sheet, swipeable evidence cards, "near me", offline reads and Web Push.

| | |
|---|---|
| ![Event investigation](docs/screenshots/04-event-page.png) | ![Mobile](docs/screenshots/m02-event.png) |
| ![Data sources](docs/screenshots/06-data-sources.png) | ![Analytics](docs/screenshots/06-analytics.png) |

Full status of each feature: [docs/FEATURES.md](docs/FEATURES.md).

## Data sources

| Source | Used for | Credential |
|---|---|---|
| NASA FIRMS (MODIS, VIIRS S-NPP / NOAA-20 / NOAA-21) | Thermal detections | None for the NRT files. `FIRMS_MAP_KEY` for history/archive. |
| GeoNames (cities500) | Offline place names for events ("Near Dhanbad, Jharkhand") | None |
| OpenStreetMap (Overpass) | Facilities and land use; a local facility index is built in 1° tiles | None (User-Agent required) |
| WRI Global Power Plant Database | Power plants | None |
| Global Energy Monitor, CEA | Additional facility registries | None, but the data files must be downloaded manually |
| Sentinel-2 L2A (Earth Search STAC, Copernicus Data Space) | Scene search, previews, NDVI / NBR change, SWIR renders | None for search and NDVI / NBR. `COPERNICUS_CLIENT_ID/SECRET` for SWIR. |
| ESA WorldCover 10 m (2021) | Land-cover shares around each event | None |
| Open-Meteo | Weather at detection time | None |
| OSM Nominatim | State and district | None |

When a source fails, ThermalTrace records the failure and says "unavailable". It never substitutes other data. Details: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Setup

Prerequisites:

- Docker (for PostGIS, or for the whole stack)
- Python 3.12
- Node 22
- git

**1. Clone**

```bash
git clone https://github.com/saad-46/ThermalTrace.git
cd ThermalTrace
```

**2. Configure the environment.** Development values work as-is. Never commit `.env`.

```bash
cp .env.development.example .env
```

**3. Start PostGIS**

```bash
docker compose up -d db
```

**4. Install the backend**

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Linux/macOS: .venv/bin/pip
```

**5. Run the migrations** (creates all 43 tables and seeds roles and sources; no users are seeded)

```bash
alembic upgrade head
```

**6. Create the first admin.** The password is read from `THERMALTRACE_PASSWORD` or prompted for.

```bash
python -m app.cli create-user --email you@example.org --name "Your Name" --role admin
```

**7. Start the API and workers** (one terminal each)

```bash
uvicorn app.main:app --reload --reload-dir app
python -m app.workers.run --scheduler --lane bulk
python -m app.workers.run --lane interactive
```

**8. Start the web app**

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173, proxies /api to :8000
```

**9. Load real data.** The scheduler polls FIRMS every 30 minutes by itself. To load data now:

```bash
python -m app.cli ingest --window 7d                # FIRMS NRT, all sensors, no key needed
python -m app.cli process                           # cluster, classify, alerts
python -m app.cli import-registry --source wri_gppd # optional: ~1,600 Indian power plants
python -m app.cli import-places                     # optional: GeoNames place names, so events read "Near Dhanbad, Jharkhand"
```

The API docs are at http://localhost:8000/api/docs.

### Everything in Docker

```bash
cp .env.development.example .env
docker compose up -d --build        # db → migrate → api, worker (bulk + scheduler), worker-interactive, web
docker compose exec api python -m app.cli create-user --email you@example.org --name "Your Name" --role admin
```

## India-only view and facility registries

The dashboard is India-focused: events are tested against India's boundary (Natural Earth, India point of view, with
Lakshadweep and the Andaman & Nicobar Islands) and events outside it are excluded; the map shows only India. The
facility layer combines OpenStreetMap, WRI GPPD, Global Energy Monitor and the official CEA power-station list, whose
stations are matched to located facilities with the coordinate source recorded. See [docs/CEA_REGISTRY.md](docs/CEA_REGISTRY.md)
and [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Landing page

Signed-out visitors see a landing page with the sign-in form at the top, and below it live figures (detections, events,
facilities, active sources), a 30-day activity map aggregated to a 1° grid, the workflow, capabilities, data sources and
technology. Every figure comes from `GET /api/v1/public/landing`, a public, cached, rate-limited endpoint that exposes
aggregates only (no identifiers or personal data); when it is unavailable the page says so rather than showing numbers.
Disable it with `PUBLIC_LANDING_ENABLED=false`.

## Guided exploration

With `EXPLORE_MODE_ENABLED=true`, the landing page offers **Explore as Analyst** and **Explore as Admin**: a read-only
demo session on the real application with a guided tour of the investigation workflow or of the platform behind it.
No credentials are involved; the server refuses every change from a demo session and masks personal data. See
[docs/GUIDED_TOURS.md](docs/GUIDED_TOURS.md).

## Environment variables

Every variable is documented and tagged REQUIRED / OPTIONAL / PROVIDER in [.env.example](.env.example). Separate templates exist for development ([.env.development.example](.env.development.example)) and production ([.env.production.example](.env.production.example)).

| Group | Variables | Required? |
|---|---|---|
| Runtime | `ENVIRONMENT`, `LOG_LEVEL`, `LOG_JSON`, `DEMO_MODE` | Defaults are provided |
| Database | `DATABASE_URL` (or `POSTGRES_USER/PASSWORD/DB` for compose) | **Required** |
| Auth | `SECRET_KEY` (≥ 32 random characters), `ACCESS_TOKEN_TTL_MINUTES` | **Required** outside development |
| API | `CORS_ORIGINS`, `RATE_LIMIT_PER_MINUTE`, `LOGIN_RATE_LIMIT_PER_MINUTE`, `ALERT_MAX_EVENT_AGE_HOURS` | Defaults are provided |
| Guided exploration | `EXPLORE_MODE_ENABLED`, `EXPLORE_SESSION_MINUTES` | Optional (off by default) |
| Landing page | `PUBLIC_LANDING_ENABLED` | Optional (on by default) |
| FIRMS | `FIRMS_MAP_KEY`, `FIRMS_REGION_NAME`, `REGION_BBOX`, `FIRMS_POLL_MINUTES` | Optional (the key unlocks history) |
| OSM | `OVERPASS_URLS`, `HTTP_USER_AGENT` | Defaults are provided |
| Copernicus | `COPERNICUS_CLIENT_ID`, `COPERNICUS_CLIENT_SECRET`, `SATELLITE_MAX_CLOUD` | Optional (SWIR renders) |
| Registries | `DATASETS_DIR` | Optional |
| Delivery | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Optional (email and push) |
| Observability | `SENTRY_DSN` | Optional |
| Web (build time) | `VITE_API_BASE_URL`, `VITE_MAP_STYLE_LIGHT`, `VITE_MAP_STYLE_DARK`, `VITE_CARTO_API_KEY` (CARTO basemaps key; public by design) | Optional |

Without optional credentials, the integration reports `not_configured` or `skipped`. It never falls back to fake data. See [docs/DEPLOYMENT.md#credentials](docs/DEPLOYMENT.md#credentials).

## Development commands

```bash
# backend (from backend/)
python -m app.cli ingest --window 7d          # FIRMS NRT, all sensors
python -m app.cli process [--all]             # cluster + classify + alerts
python -m app.cli enrich --limit 40           # OSM, weather, imagery, geocoding
python -m app.cli sync-facilities --tiles 4   # local OSM facility index (busiest tiles first)
python -m app.cli import-registry --source gem --path tracker.xlsx --version 2026-H1 --published 2026-07-01
python -m app.cli train                       # train LightGBM (stored inactive; activate it from System health)
ruff check app tests
alembic check                                 # models ↔ migrations drift

# frontend (from frontend/)
npm run dev | npm run build | npm run preview | npm run typecheck
```

## Testing

```bash
# backend: unit + ML always; PostGIS integration when TEST_DATABASE_URL points to a disposable database
docker compose exec db createdb -U thermaltrace thermaltrace_test
cd backend
TEST_DATABASE_URL=postgresql+psycopg://thermaltrace:thermaltrace_dev_only@localhost:5432/thermaltrace_test pytest

# frontend
cd frontend
npm run typecheck
npm test
npm run build

# end to end: needs the API, a worker and the web app running, and an analyst account
E2E_EMAIL=analyst@example.org E2E_PASSWORD=… npm run test:e2e
```

Current results: backend **108 passed**, Vitest **53 passed**, Playwright **3 passed** acceptance (desktop, tablet, mobile), **7 passed** guided exploration and **11 passed** landing page. `pip-audit` and `npm audit --omit=dev` are clean (remaining dev-tool advisories: [docs/SECURITY.md](docs/SECURITY.md)). CI (`.github/workflows/ci.yml`) runs lint, the backend tests against PostGIS, typecheck, the frontend tests, the build, both audits and the image builds. Details: [docs/TESTING.md](docs/TESTING.md).

## Docker and deployment

- `docker-compose.yml` runs the full stack: PostGIS, a one-shot migration, the API, two workers and nginx serving the web build.
- Images: `backend/Dockerfile` (non-root) and `frontend/Dockerfile` (nginx, SPA fallback).
- For production, set `ENVIRONMENT=production`, a strong `SECRET_KEY` and explicit `CORS_ORIGINS`. The API refuses to start without them. Run exactly one scheduler worker.
- Health endpoints: `GET /health`, `GET /api/v1/ready`, `GET /metrics`.

Topology, checklist and credentials: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## ML status

- **The classifier of record is the rule cascade** (`rule-cascade-v1.1`). It is deterministic, cites published domain knowledge, and records a rule trace for every decision.
- **A LightGBM + SHAP pipeline is implemented and tested, but no model ships and none is active.** Labels today are mostly rule-derived, so a trained model would only reproduce the rules and its scores would be meaningless.
- `python -m app.cli train` (or *System health → Train*) trains a model and stores it **inactive**. An admin activates it after reviewing the model card, and can deactivate it at any time (both audited). It refuses to train with fewer than 40 labels or fewer than 2 classes with 5+ rows each. Run it only once analysts have adjudicated a meaningful number of events, then review the model card under *System health*.
- Confidence comes from eight explicit components, with data-quality grades. An event is never `CONFIRMED` without an imagery check.

Details: [docs/ML.md](docs/ML.md).

## Limitations

- Persistence is only as deep as the loaded FIRMS history: about 8 days without `FIRMS_MAP_KEY`.
- OSM industrial coverage in India is uneven. A missing facility is reported as "not mapped", never as "no facility".
- Public Overpass is slow, so the local facility index fills gradually. Self-host Overpass for national backfills.
- Imagery is analysed only as NDVI / NBR change on request, and only when clear scenes bracket the event. There is no automated imagery classifier, and scene previews show the whole tile.
- The region of interest is a bounding box, so it includes parts of neighbouring countries.
- The EOX Sentinel-2 cloudless basemap is non-commercial (CC BY-NC-SA).

Current state and next priorities: [docs/FINAL_STATUS.md](docs/FINAL_STATUS.md) and [docs/FEATURE_ROADMAP.md](docs/FEATURE_ROADMAP.md).

## Security

- Credentials stay server-side. The FIRMS key never reaches the browser, and it is redacted from logs and from stored `source_ref` values.
- No credentials are in the repository. `.env*` files are ignored, and only `*.example` templates are tracked.
- No users are seeded and there is no public signup. Only admins assign roles.
- Auth uses bcrypt, HS256 JWTs and server-side sessions, so logout and deactivation revoke access immediately. Role checks run on every route.
- All SQL is parameterised. File access is confined to configured directories. CORS uses explicit origins.
- Rate limiting is per session token, and per IP on login.
- Every login, review, role change, export and model activation is recorded in the audit log.

Details, audit findings and known gaps: [docs/SECURITY.md](docs/SECURITY.md).

## Documentation

| Topic | Document |
|---|---|
| Product and users | [PRODUCT.md](docs/PRODUCT.md) |
| Architecture | [ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| API (77 operations) | [API.md](docs/API.md) |
| Database and migrations | [DATABASE.md](docs/DATABASE.md) |
| Data sources and integration matrix | [DATA_SOURCES.md](docs/DATA_SOURCES.md) |
| ML, confidence and explainability | [ML.md](docs/ML.md) |
| GIS methods | [GIS.md](docs/GIS.md) |
| Deployment and credentials | [DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Security | [SECURITY.md](docs/SECURITY.md) |
| Testing | [TESTING.md](docs/TESTING.md) |
| Feature status | [FEATURES.md](docs/FEATURES.md) |
| Bug fixes | [BUG_FIXES.md](docs/BUG_FIXES.md) |
| Status and roadmap | [FINAL_STATUS.md](docs/FINAL_STATUS.md) · [FEATURE_ROADMAP.md](docs/FEATURE_ROADMAP.md) |
| Project history | [PROJECT_HISTORY.md](docs/PROJECT_HISTORY.md) |
| Guided exploration (demo modes) | [GUIDED_TOURS.md](docs/GUIDED_TOURS.md) |
| Research and SIH | [RESEARCH.md](docs/RESEARCH.md) · [SIH-SUBMISSION.md](docs/SIH-SUBMISSION.md) |
| Repository inventory | [FINAL_REPOSITORY_INVENTORY.md](docs/FINAL_REPOSITORY_INVENTORY.md) |

## Attribution

NASA FIRMS · GeoNames (CC BY 4.0) · © OpenStreetMap contributors (ODbL) · WRI Global Power Plant Database (CC BY 4.0) · Copernicus Sentinel-2 data via Element84 Earth Search and Copernicus Data Space · Open-Meteo (CC BY 4.0) · Basemaps © CARTO · Sentinel-2 cloudless by EOX (CC BY-NC-SA 4.0).
