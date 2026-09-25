# External API integration matrix

All providers are behind clean adapters in `backend/app/integrations/`, each using the shared resilient HTTP layer (`integrations/http.py`). That layer provides:
- timeouts
- bounded retries with exponential backoff and jitter
- `Retry-After` handling
- a typed error taxonomy: timeout, rate_limited, auth, not_found, server, network, malformed
- secret redaction in logs

Health is tracked per source (`data_sources`) and shown on *Data sources*.

| Provider | Adapter | Used for | Credential (env) | Timeout / retries | Failure behaviour (user-facing) | Cache | Status |
|---|---|---|---|---|---|---|---|
| NASA FIRMS NRT files | `firms.FIRMSClient.get_recent_detections` | Live detections, all sensors | none | 60 s / 4 | Run marked `failed`, source `degraded`/`down`; no data substituted | Idempotent upsert | **Live** |
| NASA FIRMS Area/Country API | `get_detections_by_bbox`, `get_historical_detections`, `get_detections_by_country`, `get_available_datasets` | History and archive | `FIRMS_MAP_KEY` | 90 s / 4 (401/403 fail fast) | `provider_not_configured` when the key is missing | — | **Needs credential** |
| OSM Overpass (tiles) | `overpass.query_facility_tile` | Local facility index | none (User-Agent required) | 150 s / 1 per mirror, rotated | Tile `failed`, retried after 6 h; enrichment falls back to a per-cell query | Stored in `facilities` | **Live** |
| OSM Overpass (land / cell) | `query_land`, `query_around` | Land use, facilities for tiles not yet synced | none | 75 s / 1 per mirror | Event `osm` step `failed` (shown as pending/failed evidence) | `api_cache`, 7 days | **Live** |
| WRI GPPD | `registries.WRIGPPDClient` | Power plants (CEA-derived for India) | none | 120 s / 3 | Import run `failed` | Stored | **Imported (1,589)** |
| Global Energy Monitor | `registries.GlobalEnergyMonitorClient` | Coal/gas plants, steel, cement, mines | none (terms-gated download) | file | Clear validation errors | Stored | **Needs data file** |
| CEA | `registries.CEAClient` | Official station list | none | file | Requires publication id and date | Stored | **Needs data file** |
| Sentinel-2 (Element84 Earth Search STAC) | `sentinel.SatelliteSearchService` | Scene search, previews, metadata | none | 45 s / 4 | `satellite` step `failed`; UI says "not searched" or "no scene" | Stored per event | **Live** |
| Copernicus Data Space STAC | `search_cdse` | Second catalogue | none | 45 s / 4 | As above | — | **Available** |
| Copernicus Sentinel Hub Process (OAuth) | `SatellitePreviewService.render_swir` | SWIR composite around the event | `COPERNICUS_CLIENT_ID`, `COPERNICUS_CLIENT_SECRET` | 60 s / 2 | 503 `provider_not_configured` / `source_unavailable` | Browser cache 24 h | **Needs credential** |
| Open-Meteo forecast/archive | `weather.WeatherClient` | Conditions at detection time, current | none | 20 s / 4 | `weather` step `failed`; "not available" | Stored per event | **Live** |
| OSM Nominatim | `enrichment.enrich_geocode` | State and district | none (≤ 1 req/s) | 15 s / 2 | `geocode` step `failed` | `api_cache`, 90 days | **Live** |
| SMTP | `alerts._send_email` | Email alerts | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME` (alias `SMTP_USER`), `SMTP_PASSWORD`, `SMTP_FROM` | 15 s | Delivery `skipped: SMTP not configured` or `failed` | — | **Needs credential** |
| Web Push (VAPID) | `alerts._send_push` | Push to installed PWAs | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | library | Delivery `skipped` or `failed` | — | **Needs credential** |
| Sentry | `main.py` | Error tracking | `SENTRY_DSN` | — | Logs only | — | Optional |
| CARTO basemaps / EOX cloudless | web app | Map tiles | none | browser | Map shows an error boundary if WebGL fails | Browser | **Live** (EOX is non-commercial) |

## Not integrated (considered)

- **VIIRS Nightfire.** Its licence must be reviewed before flare evidence can be used.
- **ESA WorldCover.** A land-cover raster; roadmap.
- **Supabase keys.** Not needed. `DATABASE_URL` can point at a Supabase Postgres.
