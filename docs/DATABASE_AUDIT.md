# Database audit

The database is PostgreSQL 16 + PostGIS 3.4 (+ pg_trgm), owned by Alembic.

## Migrations

| Rev | Content | Up/down tested |
|---|---|---|
| 0001 | Initial schema: 40 tables, PostGIS, GiST and B-tree indexes, `thermal_event_public_seq` | ✅ |
| 0002 | Seed roles, permissions, data-source registry. **Fixed this phase:** the downgrade deleted every `data_sources` row and failed on any populated database (FK from `ingestion_runs`); it now removes only unreferenced seed rows. | ✅ |
| 0003 | `thermal_events.priority_score` (indexed) + `priority_components`; `alert_rules.cooldown_minutes` + `last_notified_at`; `facility_sync_tiles`; pg_trgm extension and GIN trigram indexes on `facilities.name` and `thermal_events.admin_district` | ✅ |

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

## Reference schemas not adopted

- **Demo** `init.sql`: no migrations, no event entity, and facilities re-inserted every run.
- **Prototype**: no database at all (`localStorage`).
- **Donor backend**: no acquisition time, and startup DDL instead of migrations.
