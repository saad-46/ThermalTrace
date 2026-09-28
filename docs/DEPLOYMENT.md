# Deployment

## Local (Docker Compose)

```bash
cp .env.development.example .env          # set POSTGRES_PASSWORD etc.
docker compose up -d --build              # db → migrate → api, worker (bulk + scheduler), worker-interactive, web
docker compose exec api python -m app.cli create-user --email you@org --name "You" --role admin   # prompts for password
```

The web app is at http://localhost:5173 and the API docs at http://localhost:8000/api/docs.

- The scheduler polls FIRMS every 30 minutes.
- Processing and alert evaluation run after each ingest.
- Enrichment runs continuously in batches of 40 events.

Optional one-off job:

```bash
docker compose exec api python -m app.cli import-registry --source wri_gppd   # adds ~1,600 Indian power plants
```

Every backend container reads the whole `.env` (`env_file`); the compose `environment` block only pins values that must differ inside the stack, such as the database host. The web image receives `VITE_API_BASE_URL`, `VITE_MAP_STYLE_LIGHT`, `VITE_MAP_STYLE_DARK` and `VITE_CARTO_API_KEY` as build arguments.

## Local without Docker for the app (Docker only for PostGIS)

```bash
docker compose up -d db
cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # (bin/ on Linux/macOS)
alembic upgrade head
python -m app.cli create-user --email admin@org --name Admin --role admin
uvicorn app.main:app --reload --reload-dir app
python -m app.workers.run --scheduler --lane bulk        # terminal 2
python -m app.workers.run --lane interactive             # terminal 3
cd ../frontend && npm install && npm run dev             # terminal 4 (proxies /api to :8000)
```

## Production topology

| Component | Suggested hosting | Notes |
|---|---|---|
| PostgreSQL + PostGIS | Supabase / managed Postgres with the PostGIS extension | `DATABASE_URL` accepts `postgres://…`. Run `alembic upgrade head` as a release step. |
| API | Cloud Run / Render / Railway / Fly (container `backend/Dockerfile`) | Stateless. Scale horizontally. Set `ENVIRONMENT=production`, `SECRET_KEY`, `CORS_ORIGINS`, `LOG_JSON=true`. |
| Worker (bulk + scheduler) | 1 always-on container: `python -m app.workers.run --scheduler --lane bulk` | Exactly one scheduler. Queue dedupe makes a duplicate harmless. |
| Worker (interactive) | 1..n containers: `python -m app.workers.run --lane interactive` | Reports and on-demand enrichment. |
| Report storage | A volume mounted at `/app/var` shared by the API and workers | Or swap `REPORT_STORAGE_DIR` for object storage (roadmap). |
| Web | Vercel / Netlify / any static host, or `frontend/Dockerfile` (nginx) | Build with `VITE_API_BASE_URL=https://api.example.org`. SPA fallback to `index.html`. |

## Vercel (Services)

`vercel.json` deploys two services on one domain: `frontend` (Vite static build, with an `index.html` fallback for
client-side routes) and `backend` (FastAPI, entrypoint `app.main:app` relative to `backend/`). Top-level rewrites send
`/api/*` to the backend with the original path (so `/api/v1/...`, `/api/docs`, `/api/openapi.json`) and everything else
to the frontend. The browser calls the API same-origin, so no CORS setup is needed.

- Python dependencies come from `backend/requirements.txt` and Python 3.12 from `backend/.python-version`. Do not add a
  `backend/pyproject.toml`: Vercel would treat it as the dependency manifest and ignore `requirements.txt`. Tool
  settings live in `ruff.toml` and `pytest.ini`; test tools in `requirements-dev.txt`.
- Dependency footprint: `requirements.txt` installs ~477 MB (scipy, rasterio/GDAL, scikit-learn, lightgbm,
  matplotlib, numpy, ...), under Vercel's 500 MB Python limit, so the build works whether or not large functions are
  enabled for the project. Vercel packs ~225 MB into the function and installs the remaining pinned packages into
  `/tmp` on a cold start (about a minute; later requests on a warm instance are unaffected). Two choices keep it
  there: SHAP values come from LightGBM's own TreeSHAP instead of the `shap` package (identical values), and
  uvicorn's server extras (uvloop, httptools, watchfiles, websockets) live in `requirements-server.txt`, which the
  Docker image and local development install; on Vercel the platform runs the ASGI app itself. Adding a large
  dependency to `requirements.txt` can push the build over 500 MB again: check the build log's "Bundle size" line.
- Project environment variables: leave `VITE_API_BASE_URL` empty (same-origin `/api`). `VITE_*` values are compiled
  into the public bundle: only public values (map styles, the domain-restricted CARTO key, `VITE_SATELLITE_IMAGERY`).
  The backend needs `ENVIRONMENT=production`, a random `SECRET_KEY` (32+ characters), `DATABASE_URL` for a reachable
  PostgreSQL + PostGIS database migrated with `alembic upgrade head`, and `CORS_ORIGINS` set to the site's origin.
  `POSTGRES_*` are only used by Docker Compose.
- **Database.** The function needs a PostgreSQL 15+ database with PostGIS, `pg_trgm`, `cube` and `btree_gist`, reachable
  from the internet over TLS (for example Neon or Supabase; both provide these extensions). `localhost` in
  `DATABASE_URL` points at the function's own container, so a copied local `.env` makes every database endpoint fail
  (`/api/v1/ready` 503 "database unavailable or not migrated", `/api/v1/public/landing` and `POST /api/v1/auth/demo`
  500) while `/api/v1/health` still answers.
  1. Create the database and copy two connection strings: the **pooled** one (Neon host with `-pooler`, Supabase
     Supavisor on port 6543) for Vercel, and the **direct** one for migrations and workers. Keep `sslmode=require`.
  2. From a machine with this repository, against the direct URL (additive only: pending migrations, a per-database
     `jit = off`, then a readiness report):
     `cd backend && DATABASE_URL=<direct url> python -m app.cli prepare-database`
  3. Load data into it with the same commands as a local install (README, step 9) and `DATABASE_URL=<direct url>`:
     `ingest --window 7d`, `process`, optionally `import-registry --source wri_gppd` and `import-places`; the workers
     (below) keep it current.
  4. In Vercel set `DATABASE_URL` to the pooled URL, `DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=3` (each function instance
     has its own pool). A transaction pooler is detected from the URL (`:6543`, `-pooler.` hosts,
     `*.pooler.supabase.com`); `DB_TRANSACTION_POOLER=true|false` overrides the detection. Through a pooler the app
     disables server-side prepared statements and does not send startup options.
- **Production settings.** Set `ENVIRONMENT=production` (a copied development `.env` leaves it `development`). The API
  then refuses to start unless `SECRET_KEY` is random and 32+ characters, `DATABASE_URL` is not the development one and
  `CORS_ORIGINS` lists the public origin, e.g. `https://thermal-trace-blue.vercel.app` (comma-separate several; the
  same-origin `/api` calls do not need CORS, other origins do). `EXPLORE_MODE_ENABLED=true` enables the read-only demo.
  Redeploy after changing variables: Vercel applies them to new deployments only.
- The function serves the API only. Vercel does not run the background workers or the scheduler (FIRMS polling,
  enrichment, reports, imagery analysis): run `python -m app.workers.run --scheduler --lane bulk` and
  `--lane interactive` on a host with access to the same database, as in Docker Compose. Migrations are run from there
  too, never at build time.
- Importing the app does not connect to the database; `/api/v1/health` answers without it and `/api/v1/ready`
  returns 503 until the database is reachable and migrated.

## Fail-closed defaults

The API image sets `ENVIRONMENT=production`. Outside development the API refuses to start unless:

- `SECRET_KEY` is set, is not the development value, and has at least 32 characters;
- `DATABASE_URL` does not use the development password;
- `CORS_ORIGINS` lists at least one non-localhost origin;
- `DEMO_MODE` is off (production only).

docker-compose sets `ENVIRONMENT=development` explicitly for local use. Independently of `ENVIRONMENT`, the development
`SECRET_KEY` is refused as soon as `CORS_ORIGINS` names a public origin.

## Configuration classes

The three root templates (`.env.example`, `.env.development.example`, `.env.production.example`) list every setting of
`backend/app/core/config.py`; `frontend/.env.example` lists the web build variables. Each line is tagged:

| Class | Variables |
|---|---|
| Required in production | `ENVIRONMENT`, `DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS`, `VITE_API_BASE_URL`, `POSTGRES_*` (compose) |
| Optional, provider credentials (features degrade to *not configured*, never to fake data) | `FIRMS_MAP_KEY`, `COPERNICUS_CLIENT_ID` / `_SECRET`, `SMTP_*`, `VAPID_*` |
| Optional, operations | `LOG_LEVEL`, `LOG_JSON`, `SENTRY_DSN` (API and workers; startup never depends on it), rate limits, `FIRMS_POLL_MINUTES`, `ALERT_MAX_EVENT_AGE_HOURS`, advanced tuning block (pool sizes, clustering radius / gap, attribution radius, provider endpoints, storage directories) |
| Public browser configuration (compiled into the bundle; never a secret) | `VITE_API_BASE_URL`, `VITE_MAP_STYLE_LIGHT` / `_DARK`, `VITE_CARTO_API_KEY` (restrict it to your origins in CARTO) |
| Development only | `VITE_DEV_API_PROXY`; `DEMO_MODE` (synthetic data, refused in production) |
| Demo only | `EXPLORE_MODE_ENABLED`, `EXPLORE_SESSION_MINUTES` (read-only guided sessions; keep off unless a public demo is intended) |
| Public landing | `PUBLIC_LANDING_ENABLED` (aggregates only) |

## Checklist

1. **Secrets**: `SECRET_KEY` must be at least 32 random characters. Set a DB password. Optionally set `FIRMS_MAP_KEY`, Copernicus, SMTP, VAPID and Sentry. See [Credentials](#credentials) below.
2. **Migrate**: run `alembic upgrade head` when no processing pass is running (0013 adds a unique index on
   `classifications` that briefly blocks writes to it).
3. **First admin**: `python -m app.cli create-user --role admin`.
4. **Health checks**:
   - `GET /health` (liveness)
   - `GET /api/v1/ready` (DB and migration)
   - `GET /metrics` (Prometheus text)
5. **Workers**: *System health* should show both workers heartbeating.
6. **Overpass**: public Overpass is slow (≈ 30 s per query) and rate-limited. For national backfills, self-host Overpass and set `OVERPASS_URLS`.
7. **Basemap**: the optional EOX Sentinel-2 cloudless layer is CC BY-NC-SA. Disable it or license an alternative for commercial use.

## Credentials

None of these values exist in the repository. Every integration below is implemented, configured and error-handled; with no credential it reports `not_configured` or `skipped`, and never falls back to fake data.

| Credential | Required? | Enables | Without it | How to obtain |
|---|---|---|---|---|
| `SECRET_KEY` | **Required** outside development | JWT signing | API refuses to start in staging/production | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `DATABASE_URL` / `POSTGRES_PASSWORD` | **Required** | Database | — | Your PostGIS instance |
| `FIRMS_MAP_KEY` | Optional | Historical/Area/Country FIRMS API, standard-processing archive, `firms_historical` jobs | Live NRT polling still works (public files); history limited to what has been polled | Free, instant: https://firms.modaps.eosdis.nasa.gov/api/map_key/ (needs your email) |
| `COPERNICUS_CLIENT_ID` / `COPERNICUS_CLIENT_SECRET` | Optional | SWIR (B12/B8A/B4) render around events; prerequisite for `CONFIRMED` via imagery analysis | Scene search and previews still work (Earth Search, keyless); SWIR button shows "not configured" | Free Copernicus Data Space account → OAuth client: https://shapps.dataspace.copernicus.eu/dashboard/ |
| `SMTP_HOST` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM` | Optional | Email alert delivery | Deliveries recorded as `skipped: SMTP not configured`; in-app alerts unaffected | Any SMTP provider |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` | Optional | Web Push to installed PWAs | Push deliveries `skipped`; enable button explains | `npx web-push generate-vapid-keys` |
| `SENTRY_DSN` | Optional | Error tracking | Logs only | sentry.io |
| GEM tracker release files | Optional (data, not a key) | Global Energy Monitor facilities | GEM source shows 0 records | Download from globalenergymonitor.org (terms acceptance required, cannot be automated) → `data/datasets/` |
| CEA publication CSV | Optional (data) | Official CEA station list | CEA source shows 0 records | Transcribe a named CEA report into `data/datasets/cea_template.csv` |

Not needed: Overpass, Open-Meteo, Nominatim, Earth Search, WRI GPPD and the basemaps are keyless. Supabase keys are unnecessary because the platform uses plain Postgres; `DATABASE_URL` can point at a Supabase Postgres.
