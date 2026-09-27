# Testing

## Commands

```bash
# backend
cd backend
ruff check app tests
alembic check                                     # models ↔ migrations drift
TEST_DATABASE_URL=postgresql+psycopg://thermaltrace:<pw>@localhost:5432/thermaltrace_test pytest
pip-audit -r requirements.txt

# frontend
cd frontend
npm run typecheck && npm test && npm run build
npm audit --omit=dev
E2E_EMAIL=analyst@... E2E_PASSWORD=... [E2E_BASE_URL=http://localhost:5174] [E2E_SEARCH=term] npm run test:e2e   # needs API + worker + web, events and facilities
```

## Suites

| Suite | Tests | Covers |
|---|---|---|
| `backend/tests/test_landcover_imagery.py` | 19 | WorldCover tile naming, class shares, reflectance offset, NDVI/NBR maths and SCL masking, local GeoTIFF window read, change classification, scene choice, missing-imagery honesty, land-cover evidence direction, rule-cascade raster fallback and its guards, facility-activity alert conditions, every job kind served by a worker lane, **dNBR sign (green-up is not a burn signal)**, **no finding over dark surfaces** |
| `backend/tests/test_units.py` | 53 | FIRMS normalisation and error handling, geodesy, persistence classes, attribution decay, OSM taxonomy (works ≠ refinery; "thermal" ≠ coal), Overpass query shapes (bounded, split tile and land), STAC dedupe, rule cascade, confidence maths and state rules (never CONFIRMED without imagery), analyst override, data-quality grading, password policy, JWT tamper detection, **triage priority**, **coordinate search parsing**, **facility tile coverage**, **alert cooldown window**, **SMTP_USER alias**, **per-token rate limiting**, **env templates parse to empty values**, **Copernicus token: missing / invalid / valid and cached, secret only in the body** |
| `backend/tests/test_ml.py` | 2 | LightGBM train → save → load → predict → SHAP; refusal without enough labels |
| `backend/tests/test_enrichment_flows.py` | 12 | API → queue → worker → database for on-demand evidence: Sentinel-2 search windows at the event's location and before/after counts, no scenes vs provider failure, NDVI / NBR refused without a clear scene on both sides and computed from band values when ready, unknown steps and demo sessions refused, weather at the event's coordinates and hour, no data is not a provider failure, archive-to-recent fallback, weather + imagery backfill, facility detail / paginated history / relationship / authorisation |
| `backend/tests/test_integration.py` | 37 | Alembic base → head on a populated DB, idempotent ingestion, GiST indexes, clustering → persistence → attribution → classification, event extension, auth and session revocation, no role self-assignment, viewer cannot review, error shapes, review → alert → PDF, demo data refused, health endpoints, **priority / search / training export / facility profile**, **cooldown suppresses external delivery (recorded)** |
| `frontend/src/__tests__/logic.test.ts` | 11 | Formatting, query strings, taxonomy completeness, qualitative confidence ("Unavailable", never "Weak", when evidence is missing), evidence chain stages and missing-state honesty, **query-key stability** (refetch-loop regression) |
| `frontend/src/__tests__/landcover.test.tsx` | 6 | Land-cover shares and legend, "<1%" for tiny shares, not-retrieved / failed / no-data states, spectral change table and caveats, evidence chain land-cover stage |
| `frontend/src/__tests__/tour.test.tsx` | 14 | Guided tours: unique step ids, every target rendered, glossary, banned marketing wording, route/target resolution (desktop, phone, empty database), placement inside the viewport, event-driven target waiting |
| `frontend/src/__tests__/landing.test.tsx` | 13 | Landing page: hero, sign-in, both Explore modes (server demo flow), loading / live / unavailable statistics, source-health disclosure (every backend state and what inactive sources need), flames on the busiest distinct areas only, India outline on the Copernicus card, no hard-coded figures or unsupported claims, reduced motion |
| `frontend/src/__tests__/enrichment.test.tsx` | 11 | Weather, Sentinel-2 and NDVI / NBR panels: not requested, pending, provider failure, no data, no suitable scene, failed job, ready, result (only returned values shown), demo sessions told why they cannot request; facility card facts, relation to the selected event, link to details, phone bottom sheet |
| `frontend/src/__tests__/components.test.tsx` | 9 | PriorityPill / PriorityPanel, EvidenceChain (list semantics), PersistenceStrip (gap days), StatePill hint, Meter ARIA, SHAP chart signs, error boundary |
| `frontend/e2e/explore.spec.ts` | 7 | Guided exploration: login page, full analyst and admin tours on desktop, tablet and phones (360/390/430 px) with overflow, viewport and no-cover checks on every step; Back/Next/Skip/Restart, keyboard, read-only review refused, explicit role switch with privileges checked, exit revokes the session on the server |
| `frontend/e2e/landing.spec.ts` | 11 | Landing page at 1920×1080, 1440×900, 1280×800, 1024×768, 768×1024, 360×800, 390×844, 430×932: flames on real busiest areas, source-health list equal to the backend (states and reasons), India outline on the Copernicus card, sign-in and Explore buttons in the first viewport, live figures equal to the public endpoint, every section, no overflow or escaping panels, no console errors; wrong-password error; reduced motion; Explore Analyst then Admin start server demo sessions and their tours |
| `frontend/e2e/investigation.spec.ts` | 1 | A real event: Sentinel-2 state and search, weather retrieval (values or an explicit no-data / provider state), then its attributed facility clicked on the map, the facility page, and the relationship back from the event. Assumes no facility name or future scene |
| `frontend/e2e/acceptance.spec.ts` | 3 | **Desktop**: search → map → event → all tabs → review → note → PDF → alert rule with cooldown → priority queue → every screen; asserts zero console errors, no horizontal overflow, ≤ 1 list request while idle. **Tablet** (820 × 1180): icon rail, map, tables. **Mobile** (390 × 844, touch): map, search, priority queue, event, swipeable evidence, review, alerts, watchlist, more. |

## Results — 2026-09-25 (final cleanup, fresh clone)

Every check below ran in a **fresh clone** of `production-consolidation`. The clone had its own new virtualenv and `npm ci` install, a brand-new database, and `.env` copied from `.env.development.example` exactly as the README describes. Nothing outside the repository was used.

| Check | Result |
|---|---|
| `alembic upgrade head` on an empty database | `0003 (head)`, 46 tables (40 application tables, plus PostGIS and Alembic tables) |
| `alembic check` | no drift |
| `ruff check app tests` | clean |
| Real FIRMS ingestion (keyless NRT, 48 h, 4 datasets) | 910 detections inserted. A repeat run inserted 0 (idempotent). |
| `app.cli process` | 477 events analysed, **0 failed** |
| `app.cli import-registry --source wri_gppd` | 1,589 facilities, 0 rejected |
| pytest (unit + ML + PostGIS integration) | **50 passed** (49 + the new env-template regression test, BUG_FIXES #24) |
| `pip-audit -r requirements.txt` | no known vulnerabilities |
| `tsc --noEmit` | clean |
| Vitest | **17 passed** |
| `npm run build` | success (MapLibre worker emitted as its own asset) |
| `npm audit --omit=dev` | **0 vulnerabilities** |
| `scripts/smoke_test.sh` against the fresh stack | **12/12 passed** |
| Playwright vs dev server | **3 passed** (desktop, tablet, mobile) |
| Playwright vs production build (`vite preview`) | **3 passed** |
| Docker images (`docker compose build api web`, fresh clone) | built. The API image loads lightgbm 4.6.0, fastapi 0.141.1 and starlette 1.3.1, and runs as uid 10001. Neither image contains `.env`, a virtualenv or runtime data. The web image includes the MapLibre worker. |

**Found and fixed by this run:**

1. **The documented setup was broken** (BUG_FIXES #24). With `.env` copied from a template, blank keys followed by inline comments parsed as the comment text. As a result, Sentry failed to start, 14 integration tests errored, and SMTP, VAPID and Copernicus looked configured. Fixed in all three templates, with a regression test.
2. **The desktop E2E depended on enriched data.** It searched for a district name, which exists only after geocoding enrichment. The default search term now matches event ids, which exist in any processed database. `E2E_SEARCH` restores a district search. The facility-profile step needs facilities, which setup step 9 (the WRI import) provides.

## Performance (development database, 341k events, 834k detections, warm cache) — 2026-09-27

| Endpoint | Before | After | Change |
|---|---|---|---|
| `GET /models` | 17.5 s | 0.29 s | partial index on current classifications (0008); index-only after VACUUM (see #40) |
| `GET /analytics/persistent-sources` | 14 s | 0.30 s | index matching its ORDER BY (0008) |
| `GET /events?sort=priority` | 3.4 s | 0.28 s | `priority_score DESC NULLS LAST, id` index (0008); count without the facility join |
| `GET /search?q=<place>` | 5.6 s | 1.1 s | trigram indexes on id, state, region (0008) |
| `GET /events/{id}/similar` | 3.6-7 s (minutes under load) | 0.4-1.2 s | GiST KNN on the fingerprint (0009), exact |
| `GET /watchlists` | 4-11 s | 0.04 s (0.35 s cold) | indexed branch per item kind, `lower(admin_district)` index (0009) |
| `POST /alert-rules` | 6.4 s | 0.65 s | evaluates only the new rule, only alert-eligible events |
| `GET /events/featured` | new | 0.02 s | candidate set bounded by the priority index |

## Recorded query plans (real data)

```
Viewport query: Bitmap Index Scan on ix_events_geom … 5.5 ms
Facility attribution (10 km): Index Scan using ix_facilities_geom … 62 ms
```

## Advanced intelligence phase and stabilisation — 2026-09-27

- Backend: 132 passed, 0 skipped (unit + PostGIS integration on the disposable `thermaltrace_test` database), including
  `test_stabilization.py`: one evidence definition across page / alerts / analytics, `reviewed` status, demo sessions
  refused on all 24 write routes, owner scoping of rules / alerts / watchlists / saved locations, literal search input,
  analytics validation, alert rule snapshots, report conclusion.
- Migration 0012: downgrade to 0011 and upgrade to head on the test database; `alembic check` no drift on test and dev.
- Frontend: `tsc` clean, Vitest 68 passed, production build clean, no credentials from `.env` in the bundle except the
  browser-side CARTO basemap key (`VITE_CARTO_API_KEY`, by design; restrict it to the app's domains in CARTO).
- Browser (dev data): no horizontal overflow and no error states on event, share view, compare, analytics, overview,
  facility, events, alerts and sources at 360, 390, 430, 768 and 1440 px; every analyst (24) and admin (17) tour target
  mounted on its route; status and knowledge labels ≥ 4.5:1 contrast in light and dark themes.
- The acceptance E2E spec records a review and a note on the featured event, so it was not run against the development
  database; run it against a disposable database.

## Final release validation — 2026-09-28

- Backend: ruff clean, **144 passed** (unit + PostGIS integration on the disposable test database), migrations at 0013 on
  the development and test databases, `alembic check` no drift, worker startup and orphaned-job recovery checked.
- Frontend: `tsc` clean, Vitest **68 passed**, production build clean, `npm audit --omit=dev` 0 vulnerabilities.
- `pip-audit` (installed environment): no application dependency affected; the advisories reported are for the `pip`
  tool of the local virtual environment only.
- E2E: **22 passed** against a disposable copy of the development database (the acceptance spec records a review), with
  the API and an interactive worker pointed at the copy; the copy was dropped afterwards. On the first run against the
  freshly cloned (cold) database three checks timed out waiting for slow first queries and one layout check measured a
  panel while it was still loading; all passed on rerun with a warm cache. The E2E locator for the event *Review* tab was
  made exact (evidence-stage buttons also contain the word).
- Docker: API and web images build; the import check passes and the image refuses to start with development defaults.
- UI smoke: demo admin views (system health with workers, model versions and audit log; data sources; settings;
  analytics; facilities; reports) and the event page at 375 px, without console errors or horizontal overflow.

## Production hardening pass — 2026-09-28 (lightweight checks only)

The comprehensive suite was deliberately not re-run in this pass. Checked: ruff clean, `tsc` clean, backend unit files
(`test_units`, `test_landcover_imagery`, `test_ml`, new `test_hardening`) 86 passed, Vitest 68 passed, migration 0013
upgrade / downgrade / upgrade and `alembic check` on the disposable test database, PDF build from two real bundles,
similar-events results identical to a full scan on 22 real events. Still to run in the final verification phase: the
PostGIS integration suites (including `test_stabilization.py`), E2E, Docker build, bundle secret scan, and applying
0013 to the development database when no processing pass is running.
