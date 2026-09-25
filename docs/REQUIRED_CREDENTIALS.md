# Credentials

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
