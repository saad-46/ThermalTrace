# Data sources

Every source is registered in the `data_sources` table. Its health (status, last success, latest record, latency EWMA and error rate) is tracked on every call and shown on the **Data sources** page.

**Failure policy.** When a provider fails, ThermalTrace records a failed run and marks the source `degraded` or `down`. It never substitutes other data.

| Source | Used for | Access | Credential | Freshness (what the UI claims) |
|---|---|---|---|---|
| NASA FIRMS | Thermal detections: MODIS C6.1 (Terra, Aqua), VIIRS 375 m (S-NPP, NOAA-20, NOAA-21) | Public regional NRT CSVs (24 h / 48 h / 7 d) for polling. Area/Country API for history. | None for NRT. `FIRMS_MAP_KEY` for history. | Near real time: files refresh about every 3 h per sensor and are polled every 30 min. |
| OpenStreetMap (Overpass) | Facilities (power, works, flare, wells, offshore platforms, industrial, quarry, landfill, mineshaft, kiln). Land use (farmland, orchard, meadow, forest, wood, scrub, residential). | Overpass API: bounded per-cell queries with mirror rotation, cached 7 days | None. A `User-Agent` is required. | Live OSM at query time. Coverage in India is uneven. |
| WRI Global Power Plant Database | Power plants with fuel and capacity. India rows are CEA-derived. | CSV release (v1.3.0, June 2021) | None (CC BY 4.0) | Static release. Shown as "GPPD v1.3.0 (published 02 Jun 2021)". |
| Global Energy Monitor | Coal and gas plants, steel, cement, coal mines, oil and gas extraction | File import of a downloaded tracker release (terms acceptance is manual) | None, but needs the release file | Release-dated. The version and date are stored. |
| CEA (India) | Official station list | File import of a CSV transcribed from a named CEA publication | None | Publication-dated. The publication id and date are required at import. |
| Sentinel-2 L2A (Element84 Earth Search) | Scene search (before, during, after, latest), cloud cover, public preview JPEGs | STAC API | None | Scene acquisition time is shown on every image. |
| Copernicus Data Space | Second STAC catalogue. AOI SWIR render (B12/B8A/B4) around an event. | STAC (keyless) and Sentinel Hub Process API (OAuth) | `COPERNICUS_CLIENT_ID` / `SECRET` for SWIR | Per scene |
| ESA WorldCover 10 m 2021 v200 | Land-cover shares (tree, shrub, grass, cropland, built-up, bare, water, wetland) in a 1.5 km square around each event | Windowed reads of the public cloud-optimised GeoTIFF tiles on AWS (3° tiles, HTTP range requests) | None (CC BY 4.0) | 2021 product. Shown with its year; land use may have changed since. |
| Open-Meteo | Weather at the last detection hour: temperature, RH, wind, precipitation, pressure, condition | Forecast API (≤ 6 days old) or Archive API (ERA5) | None | Hourly. ERA5 arrives about 5 days late. |
| OSM Nominatim | Admin geocoding (state, district) | Reverse geocoding at ≤ 1 req/s, cached 90 days | None | On demand |
| EOX Sentinel-2 cloudless 2021 | Optional satellite basemap tiles | WMTS | None (CC BY-NC-SA 4.0: **non-commercial**) | 2021 mosaic. Context only. |
| CARTO Positron / Dark Matter | Vector basemap | Style JSON | None | — |

## Raster land cover (ESA WorldCover)

- **Step:** `landcover` in enrichment (`services/landcover.py`, `integrations/raster.py`). About 3 s per event.
- **Sampling:** a 1.5 km square around the event centroid, read at 30 × 30 cells. Class shares are computed over valid pixels only.
- **No data:** if fewer than half the pixels are valid (offshore or outside coverage), nothing is stored and the step says so.
- **Backfill:** a scheduled `landcover_backfill` job fills events enriched before this step existed, highest triage priority first.
- **Use:** evidence (`landcover`, context only), features (`lc_*_frac`), the confidence engine's land support for vegetation classes, and the rule cascade's raster fallback (docs/ML.md). It never decides a classification by itself.

## Sentinel-2 spectral change (NDVI / NBR)

- **Trigger:** on demand (`POST /events/{ref}/imagery-analysis`, the *Compute NDVI / NBR change* button), because it reads several band windows per scene.
- **Scenes:** the latest clear scene before the first detection and the earliest after the last detection, from the scenes already stored for the event (cloud ≤ 40 %).
- **Method:** 1 km window at 20 m; bands B04, B08, B8A, B12 plus the scene classification layer (SCL). Only SCL classes 4, 5 and 7 are used, so clouds, shadows, cirrus, water and snow are excluded. The −1000 DN offset for processing baseline ≥ 04.00 is applied. A scene needs ≥ 50 % usable pixels.
- **Finding:** dNDVI ≤ −0.10 and dNBR ≥ 0.10 → *vegetation loss consistent with burning*; one of the two → *partial change*; neither → *no change above threshold*.
- **Honesty rules:** missing scenes are stored as `unavailable` with the reason, never as "no change". A change is described as consistent with burning, not as proof; no change does not rule out a fire.

## FIRMS details

- **Normalisation** (`integrations/firms.py`):
  - MODIS confidence is kept as 0–100. VIIRS `low/nominal/high` maps to 25/60/90.
  - The raw value is always kept in `confidence_raw`.
  - Brightness is MODIS `brightness` or VIIRS `bright_ti4`. Brightness 2 is `bright_t31` or `bright_ti5`.
  - The original row is kept in `raw`, and the source URL (with any key redacted) in `source_ref`.
- **Idempotency**: the unique key is `(dataset, latitude, longitude, acq_datetime)`. Re-ingesting the same file inserts nothing and counts duplicates in the run record.
- **Checkpoints** (`ingestion_checkpoints`) store the latest acquisition time per dataset.
- **Retries**: up to 4 attempts with exponential backoff and jitter. `Retry-After` is honoured on HTTP 429. A 401/403 fails fast.

## Local facility index (preferred path)

Facilities are synced into PostGIS by **1° tile** (`services/facility_sync.py`). The busiest tiles, by event count, go first. Tiles are refreshed every 30 days, and failed tiles are retried after 6 h.

Event attribution then runs locally, with `ST_DWithin` on the GiST index, in milliseconds. Once every tile within about 11 km of an event is fresh, the per-event Overpass request shrinks to a land-use-only query (2 clauses).

- Measured: one tile took 24 s and indexed 2,233 OSM features. The previous per-cell approach took about 30 s per 5.5 km cell.
- Coverage is shown on *Data sources → Local facility index*.
- To sync manually: `python -m app.cli sync-facilities --tiles 4`.

## OSM query design (fallback for tiles not yet synced)

Each cell of about 5.5 km (0.05°) gets **one** Overpass request:

- facilities within 14 km of the cell centre (10 km attribution radius plus the cell half-diagonal), and
- land use in the bounding box of the cell's events, padded by 1.5 km.

The query uses six combined regex clauses. A key-only `industrial=*` filter, or one clause per event point, made the public servers return 504 or time out (observed 2026-09-25).

Results are cached per cell for 7 days. Configure a self-hosted Overpass instance (`OVERPASS_URLS`) for national-scale backfills.

## Mixing rules

- `data_mode` (`live`, `historical` or `demo`) is recorded on every detection and propagated to events.
- Synthetic demo data (`data/demo/`) can only be loaded when `DEMO_MODE=true`, which the production config refuses.
- A red **DEMO** banner is shown on every screen while demo rows exist.

## Integration matrix

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
| ESA WorldCover (AWS COG) | `raster.sample_worldcover` | Land cover around events | none | GDAL HTTP 30 s / 2 | `landcover` step `failed`; UI says "retrieval failed" | Stored per event | **Live** |
| Sentinel-2 L2A band COGs (AWS) | `raster.read_window` via `services/imagery` | NDVI / NBR change | none | GDAL HTTP 30 s / 2 | Analysis stored as `unavailable` with the reason | Stored per event | **Live (on demand)** |
| Sentinel-2 (Element84 Earth Search STAC) | `sentinel.SatelliteSearchService` | Scene search, previews, metadata | none | 45 s / 4 | `satellite` step `failed`; UI says "not searched" or "no scene" | Stored per event | **Live** |
| Copernicus Data Space STAC | `search_cdse` | Second catalogue | none | 45 s / 4 | As above | — | **Available** |
| Copernicus Sentinel Hub Process (OAuth) | `SatellitePreviewService.render_swir` | SWIR composite around the event | `COPERNICUS_CLIENT_ID`, `COPERNICUS_CLIENT_SECRET` | 60 s / 2 | 503 `provider_not_configured` / `source_unavailable` | Browser cache 24 h | **Needs credential** |
| Open-Meteo forecast/archive | `weather.WeatherClient` | Conditions at detection time, current | none | 20 s / 4 | `weather` step `failed`; "not available" | Stored per event | **Live** |
| OSM Nominatim | `enrichment.enrich_geocode` | State and district | none (≤ 1 req/s) | 15 s / 2 | `geocode` step `failed` | `api_cache`, 90 days | **Live** |
| SMTP | `alerts._send_email` | Email alerts | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME` (alias `SMTP_USER`), `SMTP_PASSWORD`, `SMTP_FROM` | 15 s | Delivery `skipped: SMTP not configured` or `failed` | — | **Needs credential** |
| Web Push (VAPID) | `alerts._send_push` | Push to installed PWAs | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | library | Delivery `skipped` or `failed` | — | **Needs credential** |
| Sentry | `main.py` | Error tracking | `SENTRY_DSN` | — | Logs only | — | Optional |
| CARTO basemaps / EOX cloudless | web app | Map tiles | none | browser | Map shows an error boundary if WebGL fails | Browser | **Live** (EOX is non-commercial) |

### Not integrated (considered)

- **VIIRS Nightfire.** Its licence must be reviewed before flare evidence can be used.
- **Supabase keys.** Not needed. `DATABASE_URL` can point at a Supabase Postgres.
