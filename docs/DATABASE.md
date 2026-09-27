# Database

The database is PostgreSQL 16 with PostGIS 3.4. The schema is owned by **Alembic** (`backend/alembic/versions`); nothing is created at application start.

```bash
cd backend && alembic upgrade head      # create or upgrade
alembic downgrade base                  # tested in CI: tests/conftest.py runs base -> head on every integration run
```

## Tables (43)

| Domain | Tables |
|---|---|
| Identity | `organizations`, `users`, `roles`, `permissions`, `role_permissions`, `user_sessions`, `push_subscriptions` |
| Thermal | `thermal_detections` (FIRMS pixels), `thermal_events` (clusters), `thermal_observations` (event × day) |
| Facilities and places | `facilities`, `facility_sources`, `facility_relationships`, `event_facility_links`, `land_context`, `places` (GeoNames populated places, used to name events) |
| Enrichment | `weather_observations`, `satellite_observations`, `landcover_observations` (ESA WorldCover shares per event), `imagery_analyses` (NDVI / NBR change per event) |
| ML | `model_versions`, `model_predictions`, `classifications`, `classification_evidence` |
| Workflow | `analyst_reviews`, `investigations`, `investigation_notes`, `alert_rules`, `alerts`, `alert_deliveries`, `saved_locations`, `watchlists`, `watchlist_items`, `reports`, `report_exports` |
| Operations | `data_sources`, `ingestion_runs`, `ingestion_errors`, `ingestion_checkpoints`, `jobs`, `worker_heartbeats`, `api_cache`, `audit_logs`, `system_health` |

## Key design points

- **Geometry**: `geography(Point|Polygon|Geometry, 4326)` throughout, so distances are true metres. GiST indexes cover `thermal_detections.geom`, `thermal_events.geom` and `facilities.geom`. Lat/lon are also stored as plain columns for cheap reads.
- **Idempotent ingestion**: `uq_detection_natural_key (dataset, latitude, longitude, acq_datetime)` on detections and `uq_facility_source_external (source_id, external_id)` on facility sources.
- **Provenance on every row**:
  - `data_mode` (`live`, `historical` or `demo`, enforced by a CHECK constraint)
  - `source_ref`
  - the `raw` payload
  - `retrieved_at`
  - `ingestion_run_id`
- **Classification history**: `classifications.is_current` marks the active row. Earlier rows are kept.
- **Event ids**: public ids (`TT-YYYY-NNNNNN`) come from `thermal_event_public_seq`.
- **Job queue**: `jobs` has a partial unique index on `dedupe_key WHERE status IN ('queued','running')`. Workers claim jobs with `FOR UPDATE SKIP LOCKED`.
- **Other indexes**:
  - `thermal_events`: last_detected, classification, persistence, confidence, (status, review_status)
  - `thermal_detections`: acq_datetime, dataset, sensor, confidence, event_id, plus a partial index on unassigned rows
  - `thermal_observations`: event_id
  - `alerts`: rule_id and event_id

## Seed data (migration 0002)

- Roles and the permission matrix.
- The data-source registry (10 sources, including `demo`, which stays disabled unless `DEMO_MODE`).
- **No users are seeded.** Create the first admin with `python -m app.cli create-user --role admin`.

## Migrations

| Rev | Content | Up/down tested |
|---|---|---|
| 0001 | Initial schema: 40 tables, PostGIS, GiST and B-tree indexes, `thermal_event_public_seq` | ✅ |
| 0002 | Seed roles, permissions, data-source registry. The downgrade originally deleted every `data_sources` row and failed on any populated database (FK from `ingestion_runs`); it now removes only unreferenced seed rows. | ✅ |
| 0003 | `thermal_events.priority_score` (indexed) + `priority_components`; `alert_rules.cooldown_minutes` + `last_notified_at`; `facility_sync_tiles`; pg_trgm extension and GIN trigram indexes on `facilities.name` and `thermal_events.admin_district` | ✅ |
| 0004 | `landcover_observations` and `imagery_analyses` (one row per event, cascade on delete); `alert_rules.min_priority`, `min_repeat_events`, `repeat_days`, `activity_increase`; data source `esa_worldcover` | ✅ |
| 0005 | `places` (GiST-indexed GeoNames cities500 for the region); `thermal_events.place_name`, `place_admin1`, `place_country`, `place_distance_m` (+ trigram index on `place_name`); data source `geonames` | ✅ |
| 0006 | `users.is_demo` (system accounts behind guided exploration; downgrade deactivates them first) | ✅ |
| 0007 | `land_context.osm_id` INTEGER → BIGINT (OpenStreetMap ids passed 2^31; downgrade removes rows that no longer fit) | ✅ |
| 0008 | Indexes for the slow read paths at full-year scale: current classifications per model, persistent-source ranking, priority queue order (`priority_score DESC NULLS LAST, id`), trigram search on event id, state and region | ✅ |
| 0009 | `cube` + `btree_gist` extensions; GiST KNN index over the five numeric fingerprint dimensions keyed by facility type (similar events), `lower(admin_district)` (watchlist district items) | ✅ |
| 0010 | India boundary (`boundaries`, `boundary_parts` GiST, `admin_areas` GiST; loaded from app/gis/data), `thermal_events.in_india` (+ index), `registry_stations` (CEA stations with or without a location), `data_sources.health_detail` (per-capability checks), WRI fuel copied to `facilities.subtype` | ✅ |
| 0011 | `ix_jobs_event` expression index on `jobs(payload->>'event_id')` for per-event job status | ✅ |
| 0012 | `analyst_reviews.previous_status` / `new_status` (decision widened to 24 chars); `alert_rules.increase_factor`, `increase_window_days`, `repeat_within_m`, `min_active_days`, `min_evidence_stages`; trigram indexes on `facilities.operator`, `facility_sources.external_id`, `registry_stations.name` | ✅ (downgrade to 0011 and upgrade verified on the disposable test database) |
| 0013 | Unique current classification per event (`uq_classifications_event_current`, partial on `is_current`); one delivery record per alert and channel (`uq_alert_deliveries_alert_channel`). Both previously enforced only in application code; verified duplicate-free on the development data | ✅ on the test database (upgrade, downgrade, upgrade); apply to other databases when no processing pass is running |

`alembic check` reports no drift between models and schema. The integration suite runs `downgrade base → upgrade head` on every run, and it has passed repeatedly against a populated test database.

## Schema review

| Aspect | Finding |
|---|---|
| Normalisation | Facilities are split into `facilities` (consolidated) and `facility_sources` (per-source record, unique `(source_id, external_id)`). Event-level aggregates and daily observations are derived, and rebuilt idempotently from `thermal_detections`. |
| Foreign keys | Present on all relations, with `ON DELETE CASCADE` for event-owned data and `SET NULL` for optional links (assignee, run). |
| Spatial | `geography` columns (metres), with GiST on detections, events and facilities. The viewport query uses `ix_events_geom` (bitmap index scan, 5.5 ms). Attribution uses `ix_facilities_geom` (62 ms at 10 km). |
| Search | Trigram GIN indexes back `ILIKE '%…%'` on facility names and districts. |
| Constraints | `data_mode` CHECK; natural-key uniqueness on detections; one alert per (rule, event); one investigation per event; partial unique index on active job dedupe keys; lowercase-email CHECK. |
| Timestamps / provenance | `created_at` / `updated_at` throughout. Every detection carries `retrieved_at`, `source_ref`, `raw` and `ingestion_run_id`. Facility sources carry `dataset_version`, `published_at` and `retrieved_at`. Weather and satellite rows carry their provider and retrieval times. |
| Audit | `audit_logs` covers logins, reviews, notes, assignments, rules, job triggers, user and role changes, reports, model activation and training exports. |
| Soft deletion | Not used. Analyst decisions and classifications are append-only (`is_current` history), which serves the same purpose for the records that matter. |
