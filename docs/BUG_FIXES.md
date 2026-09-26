# Bug fixes

This log covers major defects: the root cause, the impact, the fix, and how the fix is guarded against regression. Source-repository IDs (R1-…, R2-…) refer to `PROJECT_HISTORY.md`.

## Inherited from the source repositories

| ID | Root cause | Impact | Fix | Guard |
|---|---|---|---|---|
| R1-B1 | FIRMS URLs built as `https://nasa.gov{KEY}/…` and `https://nasa.gov` | FIRMS ingestion never worked; the worker returned silently | New `FIRMSClient` with the documented endpoints for all sensors | `test_viirs_row_normalized`, live runs recorded in `ingestion_runs` |
| R1-B3/B4 | No acquisition time columns; no uniqueness | Persistence impossible; duplicates on every trigger | Full FIRMS field set; natural-key unique constraint | `test_ingestion_is_idempotent` |
| R1-B5/B6 | Queried a nonexistent `planet_osm_polygon` table; fabricated distances on exceptions | Spatial context always "none"; features invented | Overpass enrichment into `facilities` / `land_context`; features are NaN when unknown | `test_rule_agri_needs_land_context` |
| R1-B9/B10 | Toxicology claims keyed on substrings; invented spread-rate formula | Unsupported claims shown as fact | Removed. Replaced by the wind-derived *potential dispersion direction*, labelled as such | Docs + UI copy |
| R1-S1/S2/S3 | Backdoor account, self-assigned roles, default JWT secret | Critical auth bypass | New auth (see SECURITY.md) | `test_roles_cannot_be_self_assigned`, `test_auth_flow_and_error_shape` |
| R2-D1 | Overpass requests sent no User-Agent → HTTP 406 | Silent fallback to *synthetic* facilities while FIRMS was live | UA always sent; failures recorded; no demo fallback | Verified live 2026-09-25 |
| R2-D2 | One Overpass query for all industrial land in India | Timeouts → demo fallback | Bounded per-cell queries | `test_overpass_query_is_bounded_and_uses_bb` |
| R2-D3 | Facilities re-inserted every run | Duplicate attribution | `(source_id, external_id)` unique + consolidation | Integration tests |
| R2-D6 | `man_made=works` mapped to "refinery" | Any factory could produce a "flare" label | Explicit taxonomy; name hints only where unambiguous | `test_osm_taxonomy` |
| R2-D7/D8 | Per-detection classification with four spatial queries each | Same fire classified N times; unusable at live volume | Event clustering + set-based stats | `test_clustering_persistence_attribution_classification` |

## Found during this build

| # | Symptom | Root cause | Fix | Guard |
|---|---|---|---|---|
| 1 | Every OSM way/relation dropped (Hazira returned 3 facilities instead of 42) | Overpass `out center bb`: `center` and `bb` are mutually exclusive, so ways had bounds but no centre | `out tags bb` + centre derived from bounds | `test_overpass_query_is_bounded_and_uses_bb` |
| 2 | Overpass 504s and 75 s timeouts; 35 of 1,351 events enriched after 35 min | Key-only `industrial=*` filter + one land clause per event point (84 clauses) | 6 combined regex clauses; land in a padded bbox | Same test; Data sources error rate |
| 3 | NTPC Kawas (gas) labelled a coal plant | Name heuristic `thermal power → coal`; in India "thermal" also covers gas | Coal only for unambiguous names; registry fuel overrides via merge | `test_osm_taxonomy` |
| 4 | JSONB insert failed for every event | `datetime` in evidence provenance; NaN would also be rejected by Postgres JSON | Engine `json_serializer` that ISO-formats dates, stringifies UUIDs, maps NaN/inf → null | Integration tests |
| 5 | `ingest` crashed after fetch | `.rowcount` on a `RETURNING` result object | Count returned rows | `test_ingestion_is_idempotent` |
| 6 | Login rejected `analyst@thermaltrace.local` | `EmailStr` rejects special-use TLDs | Login accepts any bounded string (exact match); creation keeps `EmailStr` | Manual |
| 7 | PDF report stuck "pending" for minutes | One worker processed jobs serially; a long enrichment batch blocked the report | Interactive and bulk worker **lanes** | Playwright report step |
| 8 | Whole app crashed after login: "failed to invert matrix" | MapLibre received `center: undefined, zoom: undefined`, which overrode defaults with NaN | Build view options conditionally; map wrapped in an error boundary | Playwright console-error assertion |
| 9 | Map canvas blank (572×300) | `maplibre-gl.css` sets `.maplibregl-map { position: relative }` after app CSS, collapsing the absolutely positioned container to 0 px; the workspace also used `height:100%` in a flex child | Higher-specificity selector; workspace pinned with `position:absolute; inset:0` | Playwright screenshots |
| 10 | Review form state could reset on refetch | Panel component defined inside the page render → remounted each render | Hoisted to module scope | Manual |
| 11 | Docker Desktop failed to start on this machine | Orphaned AF_UNIX socket reparse points in `%LOCALAPPDATA%\Docker\run` and `docker-secrets-engine` could not be removed | Renamed the stale directories (non-destructive) | Environment note |

## Found during production consolidation (2026-09-25)

| # | Symptom | Root cause | Fix | Guard |
|---|---|---|---|---|
| 12 | Events page sent ~8 list requests/s from one open tab, exhausting the rate limit (477 requests in ~3 min) | `sinceFromDays()` stamped `new Date()` on every render → the React Query key changed on every render → refetch → re-render loop | Query memoised in the page; `since` rounded to the minute so keys are stable everywhere | Vitest `query-key stability`; E2E asserts ≤ 1 list request while idle for 5 s |
| 13 | Whole E2E run failed with 429 after the first test | Rate limiter keyed per client IP; shared-IP users (office NAT, test browsers) share one bucket | Keyed per session token (hashed); anonymous traffic per IP; default 600/min | `test_rate_limit_is_per_token_not_per_ip` |
| 14 | Assistive tech (and Playwright) saw table headers as plain cells | `<th>` without `scope` inside the table markup was not exposed as `columnheader` | `scope="col"` on all 109 table headers | E2E locates `columnheader` "Priority" |
| 15 | `alembic downgrade` failed on any database with ingestion history | Migration 0002 downgrade ran `DELETE FROM data_sources` despite FKs from runs, sources and observations | Delete only unreferenced seed rows | Integration suite runs base→head on a populated test DB (passes repeatedly) |
| 16 | Enrichment could take hours to reach most events | Public Overpass queried per 5.5 km cell (~30 s each) | Local facility index synced by 1° tile; land-only per-cell queries once tiles are fresh | Unit tests for tile coverage and query shape; OSM error rate 15.2 % → 3.0 % |
| 17 | Nominatim showed "Unknown" health despite continuous use | Geocoding step never reported to the source-health tracker | `record_success` / `record_failure` added | Data sources page |
| 18 | Worker sessions sat "idle in transaction" for minutes | A cache read opened a transaction held across slow Overpass calls | Commit before provider calls | `pg_stat_activity` check |
| 19 | Map at tablet width ≈250 px wide | 208 px sidebar + 360 px panel at 820 px viewport | Icon-rail navigation 768–1100 px; 340 px panel | E2E tablet test + overflow check |
| 20 | Triage priority 69.9 displayed as "70" yet tiered "elevated" | Tier computed on the unrounded score | Integer score; tier derived from the same integer | `test_priority_components_and_tiers` |
| 21 | Deployed map would fail to render tiles | MapLibre ≥ 5 loads `maplibre-gl-worker.mjs` via a relative URL; the production build referenced but never emitted it | Worker bundled by Vite (`?worker&url`, ES format) and registered with `setWorkerUrl` | Playwright suite run against the **production build** (`vite preview`) with zero-console-error assertion |
| 22 | Dev server: "Worker failed to load" after the MapLibre upgrade | Dependency pre-bundling moved MapLibre into `.vite/deps`, breaking its relative worker URL | `optimizeDeps.exclude: ["maplibre-gl"]` | Playwright suite against the dev server |
| 23 | LightGBM 4.6.0 (required: 4.5.0 has an RCE advisory) failed to import on Windows | 4.6.0 wheels no longer bundle the OpenMP runtime (`vcomp140.dll`) | `app/ml/__init__.py` registers scikit-learn's vendored copy; no system-wide install needed; Linux uses libgomp | `tests/test_ml.py`; container import check |
| 24 | Copying `.env.development.example` to `.env` (the documented setup) made Sentry fail to start, and made SMTP, VAPID and Copernicus look configured | Blank values were followed by inline comments (`SENTRY_DSN=   # [OPTIONAL]`), which dotenv parses as the value | Comments moved to their own line in all three templates | `test_env_templates_have_no_inline_comments_on_blank_values`; found by the fresh-clone test |
| 25 | Historical FIRMS backfill could not load more than one request's worth of data, and `--days 10` (the documented example) always failed | The Area API accepts at most 5 days per request (HTTP 400 above that); the code sent one request clamped to 10 days | Backfills are split into 5-day windows, each committed as its own run; sources and day counts are validated before a job is queued | `test_firms_backfill_windows_respect_the_5_day_api_limit`, `test_firms_backfill_is_chunked_and_keeps_progress_on_failure`, `test_firms_backfill_trigger_validates_before_queueing` |
| 26 | With SMTP configured in a developer's `.env`, the test suite sent a real alert email to a test address | Settings read the local `.env`, and tests did not override provider credentials | `conftest.py` blanks all provider credentials before settings load | `test_tests_never_see_real_provider_credentials` |
| 27 | Settings such as `SMTP_PORT`, `OVERPASS_URLS` and `HTTP_USER_AGENT` in `.env` never reached the Docker services | docker-compose forwarded a fixed list of variables | Backend services load `.env` via `env_file`; the web build receives the map and CARTO variables | `docker compose config` shows them |
| 28 | A deployment that forgot `ENVIRONMENT` ran with development defaults, including the insecure secret | `ENVIRONMENT` defaulted to `development` | The API image defaults to `production`; production also rejects the development database password and localhost-only CORS | `test_production_settings_fail_closed`; CI image check |
| 29 | After a large backfill only the first 50,000 detections became events; self-continuing jobs (`enrich_batch`, `landcover_backfill`) only resumed on the next schedule tick | One processing pass clusters at most 50,000 detections and nothing queued another pass; continuations re-used the running job's dedupe key, which the queue suppresses | `process_events` queues a continuation while detections remain; continuations use a distinct `<kind>:continue` key; `app.cli process` loops until the backlog is empty | `test_processing_continues_across_batches_and_continuations_are_not_suppressed` |
