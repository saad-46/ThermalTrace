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
E2E_EMAIL=analyst@... E2E_PASSWORD=... [E2E_BASE_URL=http://localhost:5174] npm run test:e2e   # needs API + worker + web
```

## Suites

| Suite | Tests | Covers |
|---|---|---|
| `backend/tests/test_units.py` | 34 | FIRMS normalisation and error handling, geodesy, persistence classes, attribution decay, OSM taxonomy (works ≠ refinery; "thermal" ≠ coal), Overpass query shapes (bounded, split tile and land), STAC dedupe, rule cascade, confidence maths and state rules (never CONFIRMED without imagery), analyst override, data-quality grading, password policy, JWT tamper detection, **triage priority**, **coordinate search parsing**, **facility tile coverage**, **alert cooldown window**, **SMTP_USER alias**, **per-token rate limiting** |
| `backend/tests/test_ml.py` | 2 | LightGBM train → save → load → predict → SHAP; refusal without enough labels |
| `backend/tests/test_integration.py` | 13 | Alembic base → head on a populated DB, idempotent ingestion, GiST indexes, clustering → persistence → attribution → classification, event extension, auth and session revocation, no role self-assignment, viewer cannot review, error shapes, review → alert → PDF, demo data refused, health endpoints, **priority / search / training export / facility profile**, **cooldown suppresses external delivery (recorded)** |
| `frontend/src/__tests__/logic.test.ts` | 9 | Formatting, query strings, taxonomy completeness, qualitative confidence ("Unavailable", never "Weak", when evidence is missing), evidence chain stages and missing-state honesty, **query-key stability** (refetch-loop regression) |
| `frontend/src/__tests__/components.test.tsx` | 8 | PriorityPill / PriorityPanel, EvidenceChain (list semantics), PersistenceStrip (gap days), StatePill hint, Meter ARIA, SHAP chart signs, error boundary |
| `frontend/e2e/acceptance.spec.ts` | 3 | **Desktop**: search → map → event → all tabs → review → note → PDF → alert rule with cooldown → priority queue → every screen; asserts zero console errors, no horizontal overflow, ≤ 1 list request while idle. **Tablet** (820 × 1180): icon rail, map, tables. **Mobile** (390 × 844, touch): map, search, priority queue, event, swipeable evidence, review, alerts, watchlist, more. |

## Results — 2026-09-25 (final regression on `production-consolidation`)

| Check | Result |
|---|---|
| `ruff check app tests` | clean |
| `alembic check` | no drift |
| pytest (unit + ML + PostGIS integration) | **49 passed**, repeated twice against a populated test DB |
| `pip-audit` | **no known vulnerabilities** |
| `tsc --noEmit` | clean |
| Vitest | **17 passed** |
| `npm run build` | success (MapLibre worker emitted as its own asset) |
| `npm audit --omit=dev` | **0 vulnerabilities** |
| Playwright vs dev server | **3 passed** (desktop, tablet, mobile) |
| Playwright vs production build (`vite preview`) | **3 passed** |
| Docker images (`docker compose build api web`) | built; the container loads lightgbm 4.6.0, fastapi 0.141.1, starlette 1.3.1 |
| **Delete-safety test** (see below) | **passed** |

## Delete-safety test (the reference directories hidden)

`ThermalTrace Prototype`, `ThermalTrace Demo` and `ThermalTrace (pre-consolidation)` were renamed away. Then a **fresh clone** of `D:\Projects\ThermalTrace` was taken, and it:

1. installed backend and frontend dependencies from scratch;
2. created a brand-new database and ran migrations to `0003 (head)`;
3. ingested **real** FIRMS NRT data (457 detections from 4 sensors) and processed **277 events, 0 failures**;
4. passed ruff and **49** pytest tests, typecheck, **17** Vitest tests, and the production build;
5. started the API from the fresh clone, and `scripts/smoke_test.sh` passed all 12 checks. A worker claimed and completed a job.

`docker compose build api web` succeeded with the directories hidden. A repository-wide search found **no** runtime or config references to the temporary directories; the only matches are provenance comments. The directories were then restored.

## Recorded query plans (real data)

```
Viewport query: Bitmap Index Scan on ix_events_geom … 5.5 ms
Facility attribution (10 km): Index Scan using ix_facilities_geom … 62 ms
```
