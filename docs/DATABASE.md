# Database

The database is PostgreSQL 16 with PostGIS 3.4. The schema is owned by **Alembic** (`backend/alembic/versions`); nothing is created at application start.

```bash
cd backend && alembic upgrade head      # create or upgrade
alembic downgrade base                  # tested in CI: tests/conftest.py runs base -> head on every integration run
```

## Tables (40)

| Domain | Tables |
|---|---|
| Identity | `organizations`, `users`, `roles`, `permissions`, `role_permissions`, `user_sessions`, `push_subscriptions` |
| Thermal | `thermal_detections` (FIRMS pixels), `thermal_events` (clusters), `thermal_observations` (event × day) |
| Facilities | `facilities`, `facility_sources`, `facility_relationships`, `event_facility_links`, `land_context` |
| Enrichment | `weather_observations`, `satellite_observations` |
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
