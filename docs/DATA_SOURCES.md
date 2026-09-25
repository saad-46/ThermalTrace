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
| Open-Meteo | Weather at the last detection hour: temperature, RH, wind, precipitation, pressure, condition | Forecast API (≤ 6 days old) or Archive API (ERA5) | None | Hourly. ERA5 arrives about 5 days late. |
| OSM Nominatim | Admin geocoding (state, district) | Reverse geocoding at ≤ 1 req/s, cached 90 days | None | On demand |
| EOX Sentinel-2 cloudless 2021 | Optional satellite basemap tiles | WMTS | None (CC BY-NC-SA 4.0: **non-commercial**) | 2021 mosaic. Context only. |
| CARTO Positron / Dark Matter | Vector basemap | Style JSON | None | — |

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
