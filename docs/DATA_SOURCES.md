# Data sources

Every source is registered in the `data_sources` table. Its health (status, last success, latest record, latency EWMA and error rate) is tracked on every call and shown on the **Data sources** page.

**Failure policy.** When a provider fails, ThermalTrace records a failed run and marks the source `degraded` or `down`. It never substitutes other data.

| Source | Used for | Access | Credential | Freshness (what the UI claims) |
|---|---|---|---|---|
| NASA FIRMS | Thermal detections: MODIS C6.1 (Terra, Aqua), VIIRS 375 m (S-NPP, NOAA-20, NOAA-21) | Public regional NRT CSVs (24 h / 48 h / 7 d) for polling. Area/Country API for history. | None for NRT. `FIRMS_MAP_KEY` for history. | Near real time: files refresh about every 3 h per sensor and are polled every 30 min. |
| OpenStreetMap (Overpass) | Facilities (power, works, flare, wells, offshore platforms, industrial, quarry, landfill, mineshaft, kiln). Land use (farmland, orchard, meadow, forest, wood, scrub, residential). | Overpass API: bounded per-cell queries with mirror rotation, cached 7 days | None. A `User-Agent` is required. | Live OSM at query time. Coverage in India is uneven. |
| WRI Global Power Plant Database | Power plants with fuel and capacity. India rows are CEA-derived. | CSV release (v1.3.0, June 2021) | None (CC BY 4.0) | Static release. Shown as "GPPD v1.3.0 (published 02 Jun 2021)". |
| Global Energy Monitor | Coal and gas plants, steel, cement, coal mines, oil and gas extraction | File import of a downloaded tracker release (terms acceptance is manual) | None, but needs the release file | Release-dated. The version and date are stored. |
| CEA (India) | Official station list | File import of the official *List of Power Stations* PDF (see CEA_REGISTRY.md) | None | Publication-dated. The publication id and date are stored at import. |
| Sentinel-2 L2A (Element84 Earth Search) | Scene search around each event (before, during, after), cloud cover, public preview JPEGs, band COGs for NDVI / NBR | STAC API | None (public; Copernicus credentials are **not** needed for search or NDVI / NBR) | Scene acquisition time is shown on every image. |
| Copernicus Data Space | Second STAC catalogue. AOI SWIR render (B12/B8A/B4) around an event. | STAC (keyless) and Sentinel Hub Process API (OAuth) | `COPERNICUS_CLIENT_ID` / `SECRET` for SWIR | Per scene |
| ESA WorldCover 10 m 2021 v200 | Land-cover shares (tree, shrub, grass, cropland, built-up, bare, water, wetland) in a 1.5 km square around each event | Windowed reads of the public cloud-optimised GeoTIFF tiles on AWS (3° tiles, HTTP range requests) | None (CC BY 4.0) | 2021 product. Shown with its year; land use may have changed since. |
| Open-Meteo | Weather at the last detection hour: temperature, RH, wind, precipitation, pressure, condition | Archive API (ERA5) for events older than 6 days, Forecast API recent hours otherwise (and as the fallback while ERA5 has not caught up, up to 92 days back) | None | Hourly. ERA5 arrives about 5 days late. |
| GeoNames cities500 | Offline place names for events: nearest populated place (about 10,000 places in the region) | Downloaded once by `python -m app.cli import-places` (`download.geonames.org/export/dump/`), stored in PostGIS | None (CC BY 4.0, attribute GeoNames) | Static; refresh on demand |
| OSM Nominatim | Admin geocoding (state, district) | Reverse geocoding at ≤ 1 req/s, cached 90 days | None | On demand |
| EOX Sentinel-2 cloudless 2021 | Optional satellite basemap tiles | WMTS | None (CC BY-NC-SA 4.0: **non-commercial**) | 2021 mosaic. Context only. |
| CARTO Positron / Dark Matter | Vector basemap | Style JSON | None | — |

## Source states (one definition, shown everywhere)

`services/source_health.effective_state` turns the recorded health and configuration of a source into the state shown
on the landing page, the source-health list and the Data sources page. A source is **Active** only after a real request
to it succeeded; nothing is assumed from configuration alone.

| State | Meaning |
|---|---|
| Active | The last request succeeded |
| Degraded | Recent requests failed after a recent success |
| Unavailable | Requests are failing |
| Credentials required | The provider needs credentials that are not configured (`requirement` names them) |
| Import required | A file-import source with no successful import yet |
| Not currently used | Configured, but nothing has exercised it yet |

Providers that no scheduled job exercises are verified by the `source_probe` job (every 6 h, interactive lane): for
Copernicus Data Space it requests a fresh OAuth token, which proves the credentials without using processing units.
SWIR renders also record Copernicus health. Unconfigured providers are skipped, never marked healthy.

| Source | What it needs | Where |
|---|---|---|
| Copernicus Data Space (SWIR composites) | `COPERNICUS_CLIENT_ID`, `COPERNICUS_CLIENT_SECRET` | Register at dataspace.copernicus.eu, create an OAuth client under User settings |
| NASA FIRMS historical / area API | `FIRMS_MAP_KEY` (NRT files work without it) | firms.modaps.eosdis.nasa.gov/api/map_key/ |
| CEA | A station list with coordinates transcribed from a named CEA publication (`data/datasets/cea_template.csv`) | `python -m app.cli import-registry --source cea ...`; the monthly *Installed Capacity* report and `IC_allocation_*.xlsx` hold only totals and cannot be imported as facilities |

## India boundary and the India-only view

- **Boundary**: Natural Earth 1:10m Admin 0, **India point of view** (`ne_10m_admin_0_countries_ind`, public domain):
  mainland India as India officially depicts it, plus Lakshadweep and the Andaman & Nicobar Islands (35 polygons).
  States/UTs: Natural Earth 1:10m Admin 1, clipped to that outline. Committed (simplified, ~200 m) in
  `backend/app/gis/data/`, loaded into PostGIS by migration 0010 (`boundaries`, `boundary_parts`, `admin_areas`).
- **Spatial filter**: every event gets `in_india` by point-in-polygon against subdivided, GiST-indexed pieces of the
  boundary (never a latitude/longitude box). Points within 1.5 km of the outline count as India unless they fall in a
  neighbouring country: FIRMS pixels are 375 m-1 km and the 1:10m outline is off by up to ~1.4 km on the smallest islands
  (Minicoy, Campbell Bay). Land borders keep the 1:10m precision (~1 km).
- **Effect**: the dashboard, map, lists, analytics, search and public figures show only events inside India
  (`region=india`, default; `region=all` on the events API returns everything). On 27 Sep 2026: 226,544 events
  (556,368 detections) inside India, 115,206 events (278,576 detections) outside and excluded.
- **Map**: the live map masks everything outside India, draws the outline with a subtle glow and the state lines, and
  fits India's extent including the islands. The outline never depends on the fire data (it shows with zero events).

## Copernicus Data Space checks

Health is recorded from real calls only (`data_sources.health_detail`), never inferred from configuration:
- **Authentication**: the `source_probe` job (every 6 h, interactive lane) requests a fresh OAuth token (client
  credentials; no processing units). Result, time, latency, HTTP status and an error category (authentication failed,
  timeout, service unavailable, rate limited, invalid request, ...) are stored; tokens and secrets are not.
- **Satellite preview**: every SWIR render records the same fields.
- **State**: credentials missing -> *Credentials required*; configured but never verified, or last success older than
  13 h -> *Not verified*; latest authentication failed, or two consecutive preview failures -> *Degraded*; otherwise
  *Active*.

## Place names for events (GeoNames)

Nominatim allows about one request per second, so it cannot name hundreds of thousands of events. `import-places` loads GeoNames populated places (500 inhabitants or more) for the region into a GiST-indexed PostGIS table, and every event gets its nearest place with one KNN query.

- **What it is:** a nearest-populated-place label, shown as `Near Dhanbad, Jharkhand · 1 km`, with the coordinates beside it. It is not an administrative boundary lookup, which is why it always says "Near" and gives the distance.
- **Precedence:** a Nominatim district/state, where the event has one, is shown instead: it is a real administrative lookup.
- **Not named:** an event more than 50 km from any place (for example at sea) stays unnamed and shows coordinates only. Its distance is still stored.
- **Border caveat:** a place across a border can be nearer than an Indian village below 500 inhabitants. Non-Indian places carry a country code, e.g. `Near Alahabad, Punjab (PK)`.
- **Search:** searching a place name finds the events near it.
- **New events** are named automatically when they are clustered.

## Raster land cover (ESA WorldCover)

- **Step:** `landcover` in enrichment (`services/landcover.py`, `integrations/raster.py`). About 3 s per event.
- **Sampling:** a 1.5 km square around the event centroid, read at 30 × 30 cells. Class shares are computed over valid pixels only.
- **No data:** if fewer than half the pixels are valid (offshore or outside coverage), nothing is stored and the step says so.
- **Backfill:** a scheduled `landcover_backfill` job fills events enriched before this step existed, highest triage priority first.
- **Use:** evidence (`landcover`, context only), features (`lc_*_frac`), the confidence engine's land support for vegetation classes, and the rule cascade's raster fallback (docs/ML.md). It never decides a classification by itself.

## Weather and Sentinel-2 enrichment: when it runs, and what each state means

Both are single keyless requests (~1 s), so they no longer wait behind the Overpass step that paces full enrichment
(~25 s per event, which had reached only ~0.25 % of events):

- **Automatic:** the `context_backfill` job (bulk lane, every 15 min, 30 events per run) fetches weather and searches
  Sentinel-2 for the most review-worthy events inside India that lack them (triage priority first). About 2,900 events
  a day, well inside Open-Meteo's free quota. Full enrichment (`enrich_batch`) still includes both steps.
- **On demand:** *Retrieve weather* and *Search Sentinel-2 imagery* on the event (`POST /events/{ref}/enrich?steps=weather`
  or `steps=satellite`; analyst and above; audited; refused in read-only demo sessions). The job runs on the interactive
  lane in seconds; the event page polls while it is queued or running (`jobs` in the event bundle).
- **Recorded outcome** (`thermal_events.enrichment_state[step]`), each shown differently in the UI:
  - `ok`: the provider answered. For imagery this may be zero scenes: *No suitable Sentinel-2 scene was available for
    this event*, with the searched window and cloud limit.
  - `no_data` (weather): Open-Meteo answered without values for that hour and place. Not counted as a provider failure.
  - `failed`: the provider could not be reached or refused (category: timeout, rate limited, service unavailable...).
    Recorded on the source's health; the details are in the server logs.
  - a failed **job** (a crash, not a provider answer) is shown as *did not complete*, with the error type only.
- **Sentinel-2 search windows:** the newest scenes in the 45 days before the first detection, and the oldest from the first
  detection until 60 days after the last, cloud ≤ 60 %, footprint containing the event point. (A single newest-first
  search over months returned only recent scenes for older events, so the "before" side was never found.)

## Sentinel-2 spectral change (NDVI / NBR)

- **Trigger:** on demand (`POST /events/{ref}/imagery-analysis`, the *Compute NDVI / NBR change* button), because it reads several band windows per scene (~30 s). The request is refused (409 `imagery_not_ready`) unless a scene with cloud ≤ 40 % exists both before the first detection and after the last; the event bundle's `imagery_readiness` states the same rule, so the button is only offered when a comparison is possible.
- **Scenes:** the latest clear scene before the first detection and the earliest after the last detection, from the scenes already stored for the event (cloud ≤ 40 %).
- **Method:** 1 km window at 20 m; bands B04, B08, B8A, B12 plus the scene classification layer (SCL). Only SCL classes 4, 5 and 7 are used, so clouds, shadows, cirrus, water and snow are excluded. The −1000 DN offset for processing baseline ≥ 04.00 is applied. A scene needs ≥ 50 % usable pixels.
- **Finding:** changes are stored as after minus before. NDVI change ≤ −0.10 and NBR change ≤ −0.10 (dNBR = NBR before − NBR after ≥ 0.10, the USGS convention: burning *lowers* NBR) → *spectral change is consistent with burning*; one of the two → *partial change*; neither → *no burn-consistent change*. (Before 27 Sep 2026 the NBR test had the wrong sign and flagged vegetation green-up.)
- **Dark surfaces:** if either scene's mean NIR (B8A) reflectance in the window is below 0.05 (water, coal, ash, deep shadow), NDVI / NBR are ratios of near-zero values and no finding is reported; the analysis is `unavailable` with that reason.
- **Honesty rules:** missing scenes are stored as `unavailable` with the reason, never as "no change". A change is described as consistent with burning, not as proof; no change does not rule out a fire.

## FIRMS history (keyed Area API)

- `FIRMS_MAP_KEY` is free (email registration at https://firms.modaps.eosdis.nasa.gov/api/map_key/). Limit: 5,000 transactions per 10 minutes per key.
- The Area API accepts a day range of **1–5 days** per request; 6 or more returns HTTP 400 (verified 2026-09-26). Backfills of any length are split into 5-day windows (`integrations/firms.date_chunks`). Each window is its own ingestion run and is committed before the next, so an interrupted backfill keeps what it loaded and can simply be re-run (detections deduplicate).
- Archive coverage reported by the key's `data_availability` call on 2026-09-26: `MODIS_SP` 2000-11-01 → 2026-06-30, `VIIRS_SNPP_SP` 2012-01-20 → 2026-06-30, `VIIRS_NOAA20_SP` 2018-04-01 → 2026-06-30. The NRT sources cover the months after the archive ends (e.g. `VIIRS_NOAA21_NRT` from 2024-01-17).
- Command: `python -m app.cli ingest-historical --source VIIRS_SNPP_SP --start 2025-09-26 --days 278` (up to 400 days per call). The same job is available as `firms_historical` via `POST /api/v1/ingestion/trigger` (supervisor+), validated before it is queued.

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
