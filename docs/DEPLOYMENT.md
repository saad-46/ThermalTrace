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

## Local without Docker for the app (Docker only for PostGIS)

```bash
docker compose up -d db
cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # (bin/ on Linux/macOS)
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

## Checklist

1. **Secrets**: `SECRET_KEY` must be at least 32 random characters. Set a DB password. Optionally set `FIRMS_MAP_KEY`, Copernicus, SMTP, VAPID and Sentry. See [Credentials](#credentials) below.
2. **Migrate**: run `alembic upgrade head`.
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
