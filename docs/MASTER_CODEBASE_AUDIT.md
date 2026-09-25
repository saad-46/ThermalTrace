# Master codebase audit — production consolidation

**Date:** 2026-09-25 · **Branch:** `production-consolidation`

This audit covers every codebase that fed into the final repository. It was done by reading the source, not the READMEs.

| Codebase | Location during audit | Nature | After consolidation |
|---|---|---|---|
| **Production** | `D:\Projects\ThermalTrace` (clone of `saad-46/ThermalTrace`, commit `876f229`) | FastAPI + PostGIS + React/MapLibre platform on live data | **The only long-term repository** |
| **Demo** | `D:\Projects\ThermalTrace Demo` (git clone of `saad-46/thermal-trace-demo-1` @ `4bc32a6`) | FastAPI + psycopg2 + React vertical slice with a synthetic dataset | Reference only. Safe to delete. |
| **Prototype** | `D:\Projects\ThermalTrace Prototype` (not a git repository) | Next.js 14 + Zustand + Tailwind UI running entirely on a mock dataset (`DEMO_MODE=true`) | Reference only. Safe to delete. |
| sih-fire-backend (donor) | `D:\Projects\ThermalTrace (pre-consolidation)\sih-fire-backend` | FastAPI async backend with a backdoor login | Audited previously (`REPOSITORY_AUDIT.md`). Nothing further migrated. |

## Production (before this phase)

- **Backend**: FastAPI `/api/v1` with 72 operations, SQLAlchemy 2 + GeoAlchemy2 + Alembic (migrations 0001–0002, 40 tables), JWT auth with revocable sessions, a role hierarchy and an audit log.
- **Real data**:
  - NASA FIRMS NRT for all sensors (4,700+ detections), clustered into events.
  - OSM Overpass enrichment.
  - WRI GPPD (1,589 Indian plants).
  - Open-Meteo, Sentinel-2 STAC (Earth Search) and Nominatim.
- **Processing**: persistence engine, distance-decay attribution, 26-feature pipeline, rule cascade and LightGBM + SHAP (pipeline tested, not yet trained on live labels), confidence and data-quality engines, evidence bundles.
- **Workflow**: reviews, notes, assignment, alerts (in-app / email / push with recorded delivery), watchlists, PDF reports.
- **Frontend**: 13 desktop screens and a mobile PWA shell.
- **Operations**: 40 pytest tests, 2 Playwright flows, Docker, CI.
- **Gaps found in this audit**:
  1. Enrichment queried public Overpass for every event cell (≈30 s each). This is the dominant real-data bottleneck.
  2. No triage ordering of the analyst queue.
  3. No global search.
  4. No export of the adjudicated training dataset.
  5. No alert cooldown.
  6. No frontend unit/component tests.
  7. Weak tablet layout.
  8. A latent Events-page refetch loop.
  9. Per-IP rate limiting that penalises analysts behind a shared NAT.
  10. Table headers not exposed to assistive tech.
  11. Migration 0002 downgrade failing on a populated database.

## Demo (`thermal-trace-demo-1` @ `4bc32a6`)

- **Working tree**: clean. Its `.env` is identical to `.env.example`: dev-only DB password, empty `FIRMS_MAP_KEY`. It contains no secrets.
- **Content**: this is the exact commit production was rebuilt from. Every file was reviewed in the first phase (`REPOSITORY_AUDIT.md`, R2).
- **Everything of value is already in production, in improved form**: honest `data_mode`, the evidence supporting/counter model, the classifier cascade (now `rule-cascade-v1.0`), VIIRS confidence normalisation, the MapLibre map, the research docs (`docs/01-research.md`, `docs/SIH-SUBMISSION.md`), and the labelled synthetic dataset (`data/demo/`, loadable only with `DEMO_MODE=true`).
- **Obsolete**: the psycopg2 connection-per-request API, the `init.sql` schema, CLI-only ingestion, the silent live-to-demo fallback, and the missing Overpass User-Agent.
- **Only unique artefacts**: a built `frontend/dist` bundle (generated output) and a local `.env` (no secrets). Nothing to migrate.

## Prototype (Next.js, ~5,100 lines)

- **Architecture**: Next.js App Router pages and route handlers, Zustand store persisted to `localStorage`, Tailwind, Recharts, MapLibre.
- **Data**: all four "services" (FIRMS, OSM, satellite, classification) return a hard-coded 541-line demo dataset. There are no live integrations. API routes echo requests without persisting them ("persisted client-side only").
- **Features found**, including ones with no visible UI:

| Area | Prototype implementation | Assessment |
|---|---|---|
| Prioritisation | `computePriority`: five 20-point factors (intensity, persistence, industrial proximity, classification confidence, historical context) → 0–100 → severity | **Valuable idea**. Production had no queue ordering. Re-implemented on real evidence as *triage priority* (explicitly not a risk score). |
| Explainable priority | `ExplainabilityPanel` "why was this prioritised?" | **Integrated** (desktop panel and mobile card). |
| Evidence chain | `buildEvidenceChain` (detection → location → facility → persistence → satellite → classification → confidence) | **Integrated**, built from real bundle fields, with a weather stage added and missing stages marked. |
| Persistence timeline | 7-period detected/not-detected strip | **Integrated** as a per-day strip over the event's span, so gaps are visible. |
| Global search | Client-side filter over the demo array (id, region, facility, classification, lat/lon) | **Integrated** as server-side `/api/v1/search` with pg_trgm, coordinate parsing and nearest events. |
| Proximity buffer overlay | 8 km circle around a facility | **Integrated** as 2 km (rule threshold) and 10 km (attribution radius) rings around the selected event. |
| Filters | time / confidence / persistence / land cover / severity / classification | Production already had a superset. Land-cover filtering is deferred: OSM land context covers too few events to filter on honestly. |
| Alert status workflow | new / investigating / reviewed / dismissed, stored locally | Production already has persistent server-side equivalents (alert new/acknowledged/resolved plus review decisions and investigation status). |
| Analyst assessment | Status + notes in `localStorage` | Production already persists this server-side with an audit trail. |
| Classification engine | Hand-weighted scoring, labels "Possible Gas Flare", etc. | **Rejected**. Production's rule cascade and confidence engine are more rigorous. The Prototype's contributions are not probabilities. |
| Notifications badge | Unreviewed high-priority count | Production already has the unread-alert badge. |
| Guided "Run Demo Investigation" walkthrough | Scripted 7-step tour over demo data | **Rejected**. It only makes sense over synthetic data. |
| "Why ThermalTrace" comparison card | Marketing content | **Rejected** (P3, not product functionality). |
| Printable report view | Browser print | Production's PDF reports supersede it. |
| Severity encoding by size + outline (not colour only) | Map markers | Production already encodes by size (FRP) and ring (state). |
| Thermal history chart (brightness + FRP) | Recharts | Covered by production's evolution chart. The strip was added. |
| Settings "reset local state" | Clears `localStorage` | Not applicable; state lives server-side. |

- **Dependencies not adopted**: `next`, `zustand`, `recharts`, `tailwindcss`, `clsx`, `date-fns`. Production's existing stack (Vite, TanStack Query, hand-built SVG charts, plain CSS tokens) already covers these needs, and adopting them would duplicate libraries.
- **Security**: no secrets, and `.env.local` holds only `DEMO_MODE` and the map style. The route handlers have no auth, which is acceptable for a mock but is a reason not to port them.

## Overlap

| Capability | Production | Prototype | Demo |
|---|---|---|---|
| FIRMS ingestion | Real (all sensors) | Mock | Real (MAP_KEY) with a silent demo fallback |
| Facility context | OSM + WRI (+ GEM/CEA importers) | Mock catalogue | OSM (broken UA) + demo |
| Classification | Rule cascade + GBM/SHAP + confidence engine | Hand-weighted demo | Rule cascade v0.1 |
| Map | MapLibre, viewport loading, clustering | MapLibre over the demo array | MapLibre, full-dataset load |
| Review workflow | Server-side, audited | `localStorage` | None |

## Security issues (all codebases)

See `SECURITY_AUDIT.md`. Summary: production and the Prototype have no secrets and no backdoors. The Demo has a dev-only DB password in `.env`, matching the example. The donor backend's backdoor account remains public in that repository's history; nothing from it was migrated.

## Technical debt addressed in this phase

- Per-event Overpass facility queries were replaced by a local, tile-synced facility index.
- The Events page refetch loop was fixed and guarded in E2E.
- Rate limiting is now keyed per session token.
- Table header semantics fixed (`scope="col"` on 109 headers).
- Enrichment no longer holds a DB transaction across slow provider calls.
- Nominatim health is now tracked.
- The migration 0002 downgrade was fixed.
