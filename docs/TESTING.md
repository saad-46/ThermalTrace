# Testing

## Backend (pytest)

```bash
cd backend
pytest -p no:warnings                                   # unit + ML tests; integration tests skip without a DB
TEST_DATABASE_URL=postgresql+psycopg://thermaltrace:<pw>@localhost:5432/thermaltrace_test pytest -p no:warnings
ruff check app tests
```

| Suite | Count | Covers |
|---|---|---|
| `tests/test_units.py` | 27 | FIRMS normalisation (MODIS and VIIRS, bad rows, HTML and auth responses), geodesy, persistence classes, attribution decay, OSM taxonomy (e.g. `man_made=works` ≠ refinery; "thermal" ≠ coal), Overpass query shape, STAC de-duplication, rule cascade, confidence maths and state rules (never CONFIRMED without an imagery check), analyst override, data-quality grading, password policy, JWT tamper detection |
| `tests/test_ml.py` | 2 | LightGBM train → save → load → predict → SHAP; refusal to train without enough labels |
| `tests/test_integration.py` | 11 | Alembic base→head on an empty DB, idempotent ingestion, GiST index presence, clustering + persistence + attribution + classification end to end, event extension, auth flow and session revocation, no role self-assignment, viewer cannot review, error shapes, review → alert (with a recorded skipped email delivery) → PDF report, demo data refused, health/ready/metrics |

The last recorded run was **40 passed**.

## Web (Playwright)

```bash
cd frontend
npm run typecheck && npm run build
E2E_EMAIL=analyst@... E2E_PASSWORD=... [E2E_EVENT=TT-2026-001323] npm run test:e2e   # needs API + worker + vite running
```

`e2e/acceptance.spec.ts` automates the final acceptance scenario:

- **Desktop**: login → live map with real events → select event → evidence tabs (Evidence, Facilities, History, Satellite, Weather, Model, Provenance) → full event page → record an analyst decision → add a note → generate and download a PDF → create an alert rule from "Alert on area" → Overview, Events, Facilities, Analytics, Sources, Watchlists and Reports render. The test fails on any console error.
- **Mobile (390×844, touch)**: map → events list → event → swipeable evidence cards → review → alerts.

The last recorded run was **2 passed**. Screenshots from it are in `docs/screenshots/`.

## Recorded query plans (2026-09-25, real data)

```
Viewport query (events in bbox, last 7 days):
  Bitmap Index Scan on ix_events_geom … Execution Time: 5.5 ms
  (enable_seqscan=off was needed to show the index on a 1,351-row table; the planner prefers a seq scan at this size)

Facility attribution (facilities within 10 km of an event):
  Index Scan using ix_facilities_geom … Index Cond: geom && _st_expand(e.geom, 10000) … Execution Time: 62 ms
```

## Manual acceptance (2026-09-25)

Checked against the steps in the build brief:

| # | Step | Result |
|---|---|---|
| 1–2 | Open app; see live and historical events | ✅ 1,351 real events from 4,737 FIRMS detections (MODIS Terra/Aqua, VIIRS S-NPP/NOAA-20/NOAA-21) |
| 3–5 | Select event; backend bundle; coordinates | ✅ |
| 6 | Nearby facilities | ✅ OSM + WRI GPPD, distance-ranked (e.g. Hazira: AM/NS steel at 566 m) |
| 7–8 | Historical observations; persistence | ✅ Daily observations, persistence metrics |
| 9–11 | Classification, confidence, evidence | ✅ |
| 12 | SHAP | ✅ Pipeline tested. Live SHAP appears once a GBM is trained (needs enough labels; see FINAL_STATUS) |
| 13–14 | Satellite, weather | ✅ Sentinel-2 L2A scenes (Earth Search); Open-Meteo at detection time |
| 15–16 | Review; confirm, reject, notes | ✅ |
| 17 | Alert and watchlist | ✅ |
| 18 | Report | ✅ PDF (≈ 68 KB, 3 pages) |
| 19 | Mobile investigation | ✅ PWA shell |
| 20 | No fake data in production mode | ✅ `DEMO_MODE=false`; demo loader refused (tested) |
