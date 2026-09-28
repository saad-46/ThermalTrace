# Final repository inventory (2026-09-25)

This is the state of branch `production-consolidation` after the final cleanup: 178 tracked files. The classification made before anything was removed is in `PRE_CLEANUP_INVENTORY.md`.

## Required Runtime Files

| Path | Purpose |
|---|---|
| `backend/app/` (72 files) | FastAPI application. The modules are: `api/v1` routers, `core` (config, security, middleware, logging), `db`, `models`, `schemas`, `repositories`, `integrations` (FIRMS, Overpass, registries, Sentinel, weather, HTTP layer), `processing` (clustering, persistence, attribution, features, confidence, priority, evidence, pipeline), `ml` (rule cascade, LightGBM + SHAP, registry), `services`, `workers` (job queue, scheduler), `cli.py`, `main.py`. |
| `backend/alembic/`, `backend/alembic.ini` | Schema migrations 0001–0003. Nothing is created at application start. |
| `backend/requirements.txt` | Pinned runtime Python dependencies (Docker image, Vercel function). |
| `backend/requirements-dev.txt` | Runtime dependencies plus test and lint tools. |
| `frontend/src/` (38 files) | React application: desktop, tablet and mobile shells, pages, components, API client, hooks. |
| `frontend/index.html`, `frontend/public/{icon.svg,manifest.webmanifest,sw.js}` | App entry and PWA assets (service worker, manifest, icon). |
| `frontend/package.json`, `frontend/package-lock.json` | Node dependencies (lockfile kept for reproducible `npm ci`). |
| `frontend/vite.config.ts`, `frontend/tsconfig.json` | Build configuration (MapLibre worker bundling, `/api` dev proxy). |
| `data/datasets/README.md`, `data/datasets/cea_template.csv` | Where operators place GEM/CEA release files, and the CEA transcription template. |
| `data/demo/` | *Optional.* Labelled synthetic dataset, loadable only with `DEMO_MODE=true` and refused in production. |

## Required Development Files

| Path | Purpose |
|---|---|
| `.env.example`, `.env.development.example`, `.env.production.example`, `frontend/.env.example` | Environment templates. Placeholders only; blank values parse as empty (guarded by a test). |
| `backend/ruff.toml`, `backend/pytest.ini` | ruff and pytest configuration (kept out of `pyproject.toml` so Vercel installs from `requirements.txt`). |
| `backend/.python-version` | Python 3.12 for the Vercel build. |
| `backend/tests/` | 50 tests: unit, ML, PostGIS integration. |
| `frontend/vitest.config.ts`, `frontend/src/__tests__/` | 17 Vitest unit and component tests. |
| `frontend/playwright.config.ts`, `frontend/e2e/acceptance.spec.ts` | E2E acceptance tests (desktop, tablet, mobile). Credentials come from env. |
| `scripts/smoke_test.sh` | API smoke test against a running stack (12 checks). |
| `.gitignore`, `.gitattributes` | Ignore rules (env, runtime data, build output, test artefacts, IDE/OS files) and line endings. |

## Required Deployment Files

| Path | Purpose |
|---|---|
| `docker-compose.yml` | Full stack: PostGIS, one-shot migration, API, bulk worker + scheduler, interactive worker, web. |
| `backend/Dockerfile`, `backend/.dockerignore` | API/worker image (non-root). |
| `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore` | Static web image (nginx, SPA fallback, security headers). |
| `.github/workflows/ci.yml` | CI: ruff, pytest against a PostGIS service, typecheck, Vitest, build, `pip-audit`, `npm audit`, image builds. |

## Documentation

| Path | Content |
|---|---|
| `README.md` | Overview, SIH context, architecture, features, data sources, setup (steps 1–9), env vars, commands, testing, Docker, ML status, limitations, security. |
| `docs/PRODUCT.md`, `ARCHITECTURE.md`, `API.md`, `DATABASE.md`, `DATA_SOURCES.md`, `ML.md`, `GIS.md` | Product and technical reference. The database audit is merged into `DATABASE.md` and the API integration matrix into `DATA_SOURCES.md`. |
| `docs/DEPLOYMENT.md`, `SECURITY.md`, `TESTING.md` | Operations. Credentials are merged into `DEPLOYMENT.md`, the security audit into `SECURITY.md`. |
| `docs/FEATURES.md`, `FINAL_STATUS.md`, `FEATURE_ROADMAP.md`, `BUG_FIXES.md` | Feature status, current state, roadmap, and defect log (#1–24). |
| `docs/PROJECT_HISTORY.md` | Provenance: source repositories, their defects (IDs used by `BUG_FIXES.md`), the consolidation decision, and rejected features. |
| `docs/RESEARCH.md`, `SIH-SUBMISSION.md` | Problem research and SIH pitch material. |
| `docs/PRE_CLEANUP_INVENTORY.md`, `FINAL_REPOSITORY_INVENTORY.md` | Cleanup record. |
| `docs/screenshots/` (5 PNGs) | Screenshots referenced by the README. |

## Files Removed

| Removed | Reason |
|---|---|
| `docs/REPOSITORY_AUDIT.md`, `MASTER_CODEBASE_AUDIT.md`, `FEATURE_INTEGRATION_LOG.md` | Condensed into `PROJECT_HISTORY.md`. |
| `docs/MASTER_FEATURE_MATRIX.md` | Rewritten as `FEATURES.md`, without the columns for the temporary source folders. |
| `docs/DATABASE_AUDIT.md`, `SECURITY_AUDIT.md`, `API_INTEGRATION_MATRIX.md`, `REQUIRED_CREDENTIALS.md` | Merged into `DATABASE.md`, `SECURITY.md`, `DATA_SOURCES.md` and `DEPLOYMENT.md`. |
| `docs/archive/00-audit-and-verification.md`, `docs/archive/PRD-v0.md` | Obsolete. They were a pre-build snapshot and the first PRD (superseded by `PRODUCT.md`). |
| `docs/screenshots/01-live-map.png`, `m01-map.png` | Unreferenced. |
| `docs/01-research.md` | Renamed to `RESEARCH.md`. |
| `backend/app/db/session.py::session_scope`, `backend/app/services/ingestion.py::latest_detection_time` | Dead code (never referenced). |
| `shapely`, `python-multipart` (requirements) | No importer: no form or upload endpoints, no shapely conversions. |
| Local workspace (never tracked): `backend/.venv`, `frontend/node_modules`, `frontend/dist`, `tsconfig.tsbuildinfo`, caches, `__pycache__`, `frontend/test-results`, `frontend/e2e/screenshots`, `backend/var/` (logs, 27 generated PDFs, the inactive model artifact) | Generated. Regenerated by install, build, test, report generation or `python -m app.cli train`. |

## Files Intentionally Excluded

These files are ignored by `.gitignore` and must never be committed:

- `.env` and `.env.*` (except the `*.example` templates).
- `backend/var/`: logs, generated reports, trained model artifacts.
- Local credential notes. The development accounts file was moved out of the repository to `%USERPROFILE%\.thermaltrace\`.
- `data/datasets/*` (except the README and template). These are third-party release files with their own terms.
- Build output, dependency folders, caches and test artefacts.
- Keys and certificates (`*.pem`, `*.key`) and service-account JSON.

## External Data Required

| Data | Required? | How to obtain |
|---|---|---|
| NASA FIRMS NRT files | Yes (automatic) | Downloaded by the scheduler. No key needed. |
| OpenStreetMap (Overpass) | Yes (automatic) | Queried and indexed by tile. Public endpoints, or self-host for national backfills. |
| WRI Global Power Plant Database | Recommended | `python -m app.cli import-registry --source wri_gppd` (downloads the public CSV). |
| Global Energy Monitor tracker releases | Optional | Manual download from globalenergymonitor.org (terms acceptance) → `data/datasets/`. |
| CEA station list | Optional | Transcribe a named CEA publication into `data/datasets/cea_template.csv`. |
| Sentinel-2, Open-Meteo, Nominatim, basemaps | Automatic | Keyless public APIs. |

## External Credentials Required

| Credential | Required? | Unlocks |
|---|---|---|
| `DATABASE_URL` / `POSTGRES_PASSWORD` | **Required** | Database |
| `SECRET_KEY` (≥ 32 random chars) | **Required** outside development | JWT signing. Staging and production refuse to start without it. |
| `FIRMS_MAP_KEY` | Optional | FIRMS history/archive (Area and Country API) |
| `COPERNICUS_CLIENT_ID`, `COPERNICUS_CLIENT_SECRET` | Optional | SWIR renders around events |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | Optional | Email alerts |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Optional | Web Push |
| `SENTRY_DSN` | Optional | Error tracking |

None of these values are in the repository or its history. Without an optional credential, the integration reports `not_configured` or `skipped`. It never falls back to fake data.
