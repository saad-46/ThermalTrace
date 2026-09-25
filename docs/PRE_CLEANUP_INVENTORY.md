# Pre-cleanup inventory (2026-09-25)

Taken on branch `production-consolidation` at `eb12380` before anything was changed or deleted. Nothing was removed without first being classified here and checked against the code.

**Classes:** KEEP · REMOVE · REVIEW · GENERATED · LOCAL ONLY · OPTIONAL · DEPLOYMENT REQUIRED

## Method

- **Tracked files:** `git ls-files` (186 files), grouped by directory. Every doc and screenshot was checked for inbound references (`git grep`).
- **Untracked and ignored files:** `git status --ignored`, with sizes from `du`.
- **Secrets:** pattern scan of the working tree and of every blob in history (`git rev-list --all` + `git grep`) for:
  - private keys, AWS/GitHub/Slack/Google tokens;
  - JWTs;
  - `password=`, `secret=`, `api_key=` assignments;
  - FIRMS map keys, connection strings with inline passwords;
  - `.env` files and service-account JSON.
- **Dead code:** `vulture --min-confidence 60` over `backend/app`. Each hit was confirmed by `git grep`, and framework-registered handlers were excluded. The frontend export graph was checked by hand.
- **Dependencies:** every entry in `backend/requirements.txt` and `frontend/package.json` was mapped to its imports.
- **Duplicates:** content hashes over tracked files. Backup-style names were searched for (`*.bak`, `*.old`, `* copy*`, `*~`, `*.orig`).

## Tracked files

| Path | Class | Notes |
|---|---|---|
| `backend/app/**` (72) | KEEP | Application code. |
| `backend/app/db/session.py` → `session_scope()` | REMOVE | Never referenced (vulture + grep). |
| `backend/app/services/ingestion.py` → `latest_detection_time()` | REMOVE | Never referenced. |
| FIRMS `has_key`, `get_detections_by_country`, `get_available_datasets`; `sentinel.search_cdse`; `gis.geo.bearing_deg` | KEEP | Flagged by vulture, but they are the documented provider surface (API integration matrix), not dead code. |
| `backend/alembic/**`, `alembic.ini` | KEEP | Migrations 0001–0003. |
| `backend/tests/**` | KEEP | 49 tests. |
| `backend/requirements.txt` | KEEP, edit | `shapely` and `python-multipart` have no importer: no `Form`, `UploadFile` or `File` parameters, and no `to_shape`/`from_shape`. REMOVE both. `pandas` has no direct importer, but it is a pinned transitive dependency of `shap`. KEEP it, and add a comment saying so. |
| `backend/pyproject.toml` | KEEP | ruff and pytest config. |
| `backend/Dockerfile`, `backend/.dockerignore` | DEPLOYMENT REQUIRED | |
| `frontend/src/**` (38) | KEEP | No truly unused exports (the flagged ones are used within their own modules). |
| `frontend/e2e/acceptance.spec.ts`, `playwright.config.ts`, `vitest.config.ts` | KEEP | Tests. Credentials come from env (`E2E_EMAIL` / `E2E_PASSWORD`), never a file. |
| `frontend/package.json`, `package-lock.json` | KEEP | Every dependency is imported. Lockfile kept. |
| `frontend/public/{icon.svg,manifest.webmanifest,sw.js}` | KEEP | PWA runtime assets. |
| `frontend/Dockerfile`, `nginx.conf`, `.dockerignore` | DEPLOYMENT REQUIRED | |
| `frontend/.env.example`, `.env.example`, `.env.development.example`, `.env.production.example` | KEEP | Placeholders only. |
| `docker-compose.yml` | DEPLOYMENT REQUIRED | |
| `.github/workflows/ci.yml` | DEPLOYMENT REQUIRED | CI. |
| `.gitignore`, `.gitattributes` | KEEP, edit | Add IDE, OS, coverage and local-env patterns. |
| `scripts/smoke_test.sh` | KEEP | Post-deploy smoke test. |
| `data/demo/*` | OPTIONAL | Needed only for `DEMO_MODE=true`. Synthetic, labelled as such, and refused when `DEMO_MODE=false`. |
| `data/datasets/README.md`, `cea_template.csv` | KEEP | Operator import instructions and template. |
| `README.md` | KEEP, rewrite | Needs the setup steps, ML status and security notes. |

### Documentation (23 files + archive + screenshots)

| Path | Class | Action |
|---|---|---|
| `ARCHITECTURE.md`, `API.md`, `GIS.md`, `ML.md`, `TESTING.md`, `BUG_FIXES.md`, `PRODUCT.md`, `SIH-SUBMISSION.md`, `FEATURE_ROADMAP.md`, `FINAL_STATUS.md` | KEEP | Update cross-links. Remove absolute local paths. |
| `01-research.md` | KEEP | Renamed to `RESEARCH.md`. |
| `DATABASE.md` + `DATABASE_AUDIT.md` | REVIEW → merge | Into `DATABASE.md`. |
| `SECURITY.md` + `SECURITY_AUDIT.md` | REVIEW → merge | Into `SECURITY.md`. **Redact the donor's hard-coded credential.** |
| `DATA_SOURCES.md` + `API_INTEGRATION_MATRIX.md` | REVIEW → merge | Into `DATA_SOURCES.md`. |
| `DEPLOYMENT.md` + `REQUIRED_CREDENTIALS.md` | REVIEW → merge | Into `DEPLOYMENT.md`. |
| `MASTER_FEATURE_MATRIX.md` | REVIEW → rewrite | Becomes `FEATURES.md` (feature, status, priority), without the columns for the temporary source folders. |
| `REPOSITORY_AUDIT.md`, `MASTER_CODEBASE_AUDIT.md`, `FEATURE_INTEGRATION_LOG.md` | REVIEW → merge | Condensed into `PROJECT_HISTORY.md` (provenance, integrated and rejected features, donor security findings). **Redact the donor credential** (`REPOSITORY_AUDIT.md:62`). |
| `archive/00-audit-and-verification.md` | REMOVE | A pre-build snapshot ("no application code exists yet"). Obsolete. Two references are reworded. |
| `archive/PRD-v0.md` | REMOVE | Superseded by `PRODUCT.md`. No inbound references. |
| `screenshots/02-map-event-selected.png`, `04-event-page.png`, `06-analytics.png`, `06-data-sources.png`, `m02-event.png` | KEEP | Referenced by the README. |
| `screenshots/01-live-map.png`, `m01-map.png` | REMOVE | Unreferenced. |

## Untracked and ignored (local workspace)

| Path | Size | Class | Action |
|---|---|---|---|
| `backend/.venv` | 707 MB | GENERATED | Delete. Recreated by `pip install -r requirements.txt`. |
| `frontend/node_modules` | 202 MB | GENERATED | Delete. Recreated by `npm ci`. |
| `frontend/dist` | 7 MB | GENERATED | Delete. Build output. |
| `frontend/tsconfig.tsbuildinfo` | — | GENERATED | Delete. |
| `backend/.pytest_cache`, `backend/.ruff_cache`, 17 × `__pycache__` | small | GENERATED | Delete. |
| `frontend/e2e/screenshots` | 3.5 MB | GENERATED | Delete. E2E run output. |
| `frontend/test-results` | — | GENERATED | Delete. Playwright output. |
| `backend/var/*.log` (5) | 520 KB | GENERATED | Delete. Service logs. |
| `backend/var/reports/*.pdf` (27) | 1.6 MB | GENERATED | Delete. Report downloads return 404 when the file is gone (`monitoring.py`, `path.exists()` check). They are regenerated on request. |
| `backend/var/models/lgbm-20260925115351.{joblib,json}` | 1.2 MB | GENERATED | Delete. The model is **inactive**: its rule-derived labels make F1 = 1.0 meaningless. `registry.active_gbm()` returns `None` when no model is active or the artifact is missing. Regenerate with `python -m app.cli train`. |
| `backend/var/dev-credentials.txt` | 1 KB | LOCAL ONLY | **Move outside the repository** (`%USERPROFILE%\.thermaltrace\dev-credentials.txt`). No code reads it; E2E and smoke tests take credentials from env. It is never committed. |
| Local PostGIS volume (Docker) | — | LOCAL ONLY | Not in the repository. Kept for local development. |

No `.bak`, `.old`, `* copy*`, `~` or `.orig` files exist. No duplicate files exist, apart from intentionally empty `__init__.py`.

## Secret scan findings

| Finding | Where | Class | Action |
|---|---|---|---|
| The donor repository's hard-coded backdoor login (email + password), quoted in audit docs | `docs/REPOSITORY_AUDIT.md:62`, `docs/SECURITY.md:7`, and therefore in pushed history on `origin/main` (`876f229`) | REVIEW | **Redact from current files.** It is not a ThermalTrace credential. It was never used by this codebase, and it is already public in the donor repository `rayyanafroz/sih-fire-backend`. History is **not** rewritten (per the brief). It is reported so the owner can rotate it anywhere it was reused. |
| Anything else (keys, tokens, JWTs, private keys, real `.env`) | working tree + all history | — | None found. |

## Independence

Runtime or config references to the temporary folders: **none**. Provenance comments naming them exist in `backend/app/ml/rule_cascade.py`, `backend/app/processing/priority.py` and `frontend/src/components/triage.tsx`. Absolute local paths appear in `FINAL_STATUS.md`, `MASTER_CODEBASE_AUDIT.md`, `SECURITY_AUDIT.md`, `TESTING.md` and `archive/00-audit…`. All of these are rewritten to neutral wording.
