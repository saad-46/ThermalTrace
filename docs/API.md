# API reference

The API is available at `/api/v1`. Interactive OpenAPI docs are served at `/api/docs` (Swagger) and `/api/redoc`, and the machine-readable schema at `/api/openapi.json`.

## Authentication

```
POST /api/v1/auth/login   {"email": "...", "password": "..."}   ->  {"access_token", "expires_at", "user"}
Authorization: Bearer <access_token>
POST /api/v1/auth/logout  (revokes the server-side session)
```

- Tokens are HS256 JWTs. Each token carries a `jti` that refers to a `user_sessions` row, so logging out or deactivating a user revokes access immediately.
- Roles form a hierarchy: `viewer < analyst < supervisor < admin`.
  - Every read endpoint requires `viewer`.
  - Reviews, notes, alert rules, watchlists and reports require `analyst`.
  - Assignment and ingestion triggers require `supervisor`.
  - Users, models, audit and system endpoints require `admin`.
- Roles are assigned only by an admin, through `POST /api/v1/admin/users` or `PATCH /api/v1/admin/users/{id}`.

## Conventions

- **Errors** always have this shape:
  `{"error": {"code": "not_found", "message": "Event not found", "details": {}, "request_id": "a1b2..."}}`.
  - Common codes: `unauthorized`, `forbidden`, `not_found`, `validation_error`, `invalid_bbox`, `rate_limited`, `source_unavailable`, `provider_not_configured`, `demo_mode_disabled`.
- **Pagination** uses `limit` (1–500, default 50) and `offset`. Responses look like `{items, total, limit, offset}`.
- **Spatial filters** use `bbox=west,south,east,north` in WGS84. The map endpoints require a viewport and cap the number of features returned (`truncated: true` when the cap applies).
- **Time filters** are `since` and `until` (ISO 8601). `since` matches events that were active on or after that time.
- **Event references**: every `/events/{ref}` endpoint accepts either the UUID or the public id (`TT-2026-001323`).
- **Rate limits**: 240 requests/min per client IP by default, and 10/min on `/auth/login`. Exceeding them returns `429` with `retry-after`.
- **Correlation**: every response carries an `x-request-id` header. You can send your own, and it is echoed back and logged.

## Common calls

```bash
# Events in a viewport, last 7 days, persistent only, sorted by confidence
GET /api/v1/events?bbox=68,20,75,25&since=2026-09-18T00:00:00Z&persistence=persistent&sort=confidence

# Map layer (compact GeoJSON)
GET /api/v1/events/geojson?bbox=68,6,98,36&classification=flare&classification=process_heat&limit=3000

# Full investigation bundle: observations, facilities, land, weather, satellite, predictions (SHAP),
# evidence, confidence components, data quality, timeline, evidence matrix, reviews, notes, alerts
GET /api/v1/events/TT-2026-001323

# Analyst decision (feeds the training feedback dataset)
POST /api/v1/events/TT-2026-001323/reviews  {"decision": "reclassify", "source_class": "flare", "notes": "Flare stack visible in SWIR"}

# Alert rule: persistent events within 5 km of a refinery
POST /api/v1/alert-rules {"name": "Persistent near refineries", "persistence_classes": ["persistent"],
                          "facility_types": ["refinery"], "facility_within_m": 5000, "channels": ["in_app", "email"]}

# PDF report (asynchronous): poll the report until status == "ready", then download it
POST /api/v1/reports {"event_id": "TT-2026-001323"}
GET  /api/v1/reports/{id}/download
```

## Endpoints

### admin

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/admin/audit` | Audit Log |
| GET | `/api/v1/admin/system` | Workers, queue depth, DB size, recent failures |

### alerts

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/alert-rules` | List Rules |
| POST | `/api/v1/alert-rules` | Create Rule |
| DELETE | `/api/v1/alert-rules/{rule_id}` | Delete Rule |
| PUT | `/api/v1/alert-rules/{rule_id}` | Update Rule |
| GET | `/api/v1/alerts` | List Alerts |
| GET | `/api/v1/alerts/unread-count` | Unread |
| POST | `/api/v1/alerts/{alert_id}/{action}` | Alert Action |

### analytics

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/analytics/diurnal` | Day/night + hour-of-day pattern by sensor |
| GET | `/api/v1/analytics/feedback` | Training feedback dataset + false-positive intelligence |
| GET | `/api/v1/analytics/hotspots` | Districts and facility types with most thermal activity |
| GET | `/api/v1/analytics/persistent-sources` | Locations repeatedly producing thermal anomalies â€” ranked by evidence, not a threat ranking |
| GET | `/api/v1/analytics/sensors` | Sensors |
| GET | `/api/v1/analytics/summary` | Summary |
| GET | `/api/v1/analytics/trends` | Daily detections/events by class (operational trend) |

### auth

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/admin/users` | List Users |
| POST | `/api/v1/admin/users` | Create a user (roles are only ever assigned by an admin) |
| PATCH | `/api/v1/admin/users/{user_id}` | Update User |
| POST | `/api/v1/auth/login` | Exchange email + password for a bearer token |
| POST | `/api/v1/auth/logout` | Revoke the current session |
| GET | `/api/v1/auth/me` | Me |
| GET | `/api/v1/users/directory` | Minimal user directory for assignment pickers |

### events

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/events` | List thermal events (filterable, paginated) |
| GET | `/api/v1/events/geojson` | Viewport-bounded GeoJSON of events for the map |
| GET | `/api/v1/events/nearest` | Nearest event to a point (within max_km) |
| GET | `/api/v1/events/{ref}` | Full investigation bundle for one event (id or public id) |
| POST | `/api/v1/events/{ref}/assign` | Assign the event's investigation to an analyst |
| GET | `/api/v1/events/{ref}/detections.geojson` | Individual FIRMS pixels of an event (replay / map layer) |
| POST | `/api/v1/events/{ref}/enrich` | Queue enrichment (OSM, weather, imagery, geocoding) for this event |
| POST | `/api/v1/events/{ref}/notes` | Add a note or evidence link |
| POST | `/api/v1/events/{ref}/reanalyse` | Re-run classification with current context (synchronous, fast) |
| POST | `/api/v1/events/{ref}/reviews` | Record an analyst decision (confirm/reject/false positive/escalate/reclassify/note) |
| GET | `/api/v1/events/{ref}/similar` | Historically similar events by thermal fingerprint |

### facilities

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/facilities` | List Facilities |
| GET | `/api/v1/facilities/geojson` | Facilities in a viewport, for the map layer |
| GET | `/api/v1/facilities/{facility_id}` | Get Facility |
| GET | `/api/v1/facilities/{facility_id}/events` | Facility-level thermal history |

### models

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/ml/training-dataset` | Adjudicated training dataset (event â†’ prediction â†’ analyst label â†’ features â†’ reviewer â†’ model version) |
| GET | `/api/v1/models` | Model versions with model cards |
| POST | `/api/v1/models/{model_id}/activate` | Activate |

### push

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/push/public-key` | Push Key |
| DELETE | `/api/v1/push/subscriptions` | Push Unsubscribe |
| POST | `/api/v1/push/subscriptions` | Push Subscribe |

### reports

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/reports` | List Reports |
| POST | `/api/v1/reports` | Queue a PDF report for an event |
| GET | `/api/v1/reports/{report_id}` | Get Report |
| GET | `/api/v1/reports/{report_id}/download` | Download Report |

### satellite

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/satellite/{observation_id}/swir.png` | AOI SWIR composite (B12/B8A/B4) via Copernicus â€” requires CDSE OAuth credentials |

### search

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/search` | Search events, places, facilities, classifications and coordinates |

### sources

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/ingestion/runs` | Ingestion Runs |
| GET | `/api/v1/ingestion/runs/{run_id}/errors` | Ingestion Errors |
| POST | `/api/v1/ingestion/trigger` | Queue an ingestion/processing job (supervisor+; model training admin only) |
| GET | `/api/v1/jobs` | Jobs |
| GET | `/api/v1/jobs/{job_id}` | Job |
| GET | `/api/v1/sources` | Source registry with health, freshness and configuration state |
| GET | `/api/v1/sources/facility-index` | Local OSM facility index coverage (1Â° tiles) |

### system

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/health` | Liveness: the process is up |
| GET | `/api/v1/metrics` | Prometheus-style operational gauges |
| GET | `/api/v1/ready` | Readiness: database reachable and migrated |
| GET | `/api/v1/status` | Data freshness + mode indicator shown in every screen header |
| GET | `/health` | Liveness: the process is up |
| GET | `/metrics` | Prometheus-style operational gauges |
| GET | `/ready` | Readiness: database reachable and migrated |

### watchlists

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/saved-locations` | List Locations |
| POST | `/api/v1/saved-locations` | Save Location |
| DELETE | `/api/v1/saved-locations/{loc_id}` | Delete Location |
| GET | `/api/v1/watchlists` | List Watchlists |
| POST | `/api/v1/watchlists` | Create Watchlist |
| DELETE | `/api/v1/watchlists/{wl_id}` | Delete Watchlist |
| GET | `/api/v1/watchlists/{wl_id}` | Get Watchlist |
| GET | `/api/v1/watchlists/{wl_id}/events` | Events matching a watchlist (marks it viewed) |
| POST | `/api/v1/watchlists/{wl_id}/items` | Add Item |
| DELETE | `/api/v1/watchlists/{wl_id}/items/{item_id}` | Remove Item |

### weather

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/weather/current` | Current conditions at a point (live, not stored) |
