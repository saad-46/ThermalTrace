# Final status — production consolidation (2026-09-25)

**Repository:** `D:\Projects\ThermalTrace` (the only long-term repository; remote `saad-46/ThermalTrace`). **Branch:** `production-consolidation`, not yet merged or pushed. `main` is unchanged.

## Live state (real data only, `DEMO_MODE=false`)

| Measure | Value |
|---|---|
| FIRMS detections | 4,907 from 5 platforms (Terra, Aqua, S-NPP, NOAA-20, NOAA-21) |
| Thermal events | 1,457 |
| Classifications | 133 process heat · 50 coal-seam fire · 13 wildfire · 8 agricultural burn · 6 flare · 12 other · 1,235 unknown (awaiting context or insufficient signal) |
| Triage tiers | 3 high · 127 elevated · 204 routine · 1,123 low |
| Facilities | 12,176 (OSM local index + WRI GPPD), 126 corroborated by two sources |
| Local facility index | 17 of 297 tiles synced (busiest first); syncs continuously in the background |
| Analyst reviews | 14 |

## COMPLETED (this phase)

- **Consolidation**: `D:\Projects\ThermalTrace` is now the repository root (a clean clone of `saad-46/ThermalTrace`). The Demo and Prototype were fully audited (`MASTER_CODEBASE_AUDIT.md`, `MASTER_FEATURE_MATRIX.md`). Everything valuable is integrated or recorded as rejected with a reason (`FEATURE_INTEGRATION_LOG.md`).
- **Local facility index**: scheduled 1° tile sync from OSM into PostGIS. Enrichment now asks Overpass only for land use where tiles are fresh. The OSM error rate fell from 15.2 % to 3.0 %.
- **Triage priority** (from the Prototype, re-based on real evidence), with its explanation, a priority-sorted queue and a priority filter.
- **Global search**: server-side, trigram-indexed search across event IDs, districts, facilities, classifications and coordinates.
- **Evidence chain**, **per-day persistence strip**, **qualitative confidence decomposition**, **attribution rings**, and **weather in the timeline**.
- **Training feedback dataset export** (CSV and JSON, audited).
- **Alert cooldown** with recorded delivery suppression.
- **Facility thermal-activity profile**.
- **Tablet layout** (icon rail) and **table accessibility** (`scope="col"` on 109 headers).
- **Frontend unit and component tests** (Vitest, 17). **E2E** extended to tablet, with guards for console errors, horizontal overflow and request storms.
- **Security**: every dependency with a published advisory upgraded. Both `pip-audit` and `npm audit` are clean. LightGBM 4.5.0 had a remote-code-execution advisory.
- **Fixes**: Events-page refetch loop, per-IP rate-limit bucket, migration 0002 downgrade, MapLibre worker missing from production builds, Nominatim health tracking, idle-in-transaction sessions, and the priority tier/label mismatch. Details are in `BUG_FIXES.md` #12–23.
- **Delete-safety test passed.** A fresh clone rebuilds, migrates, ingests real data and passes every test with the reference directories hidden (`TESTING.md`).
- **Docs**: MASTER_CODEBASE_AUDIT, MASTER_FEATURE_MATRIX, FEATURE_INTEGRATION_LOG, API_INTEGRATION_MATRIX, DATABASE_AUDIT, SECURITY_AUDIT, FEATURE_ROADMAP, plus BUG_FIXES, TESTING, API (75 operations), DATA_SOURCES, ML, GIS and README updates.

## PARTIALLY COMPLETED

- **ML.** A LightGBM model (`lgbm-20260925115351`) is now **trained on live data but deliberately left inactive**:
  - Its labels are 1 analyst adjudication plus 209 rule-derived weak labels.
  - Its hold-out macro-F1 of 1.0 only shows that it reproduces the rule cascade. It is **not** evidence of accuracy, and the model card says so.
  - The rule cascade remains the classifier of record.
  - Once analysts have adjudicated a meaningful number of events, retrain it with `python -m app.cli train` and review the card under *System health* before activating it.
- **Facility index coverage.** 17 of 297 tiles are synced so far. The rest sync in the background, with public Overpass taking about 25–150 s per tile. Events outside synced tiles still get context through the per-cell fallback.
- **Mobile.** A first-class installable PWA: bottom nav, bottom sheet, swipeable evidence cards, search, priority queue, GPS "near me", offline reads and Web Push. None of the source repositories contained a native app, so none was started (per the brief).

## BLOCKED BY CREDENTIALS

| Variable(s) | Unlocks |
|---|---|
| `FIRMS_MAP_KEY` | Historical/archive backfill. Today "persistent" means persistent within about 8 days of loaded history. |
| `COPERNICUS_CLIENT_ID`, `COPERNICUS_CLIENT_SECRET` | SWIR renders and a future imagery-backed `CONFIRMED` state |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME` (or `SMTP_USER`), `SMTP_PASSWORD`, `SMTP_FROM` | Email alert delivery (currently recorded as skipped) |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Web Push delivery |
| `SENTRY_DSN` | Error tracking (optional) |
| GEM tracker files, CEA publication CSV | Additional facility registries (manual download or transcription; not keys) |

## BLOCKED BY EXTERNAL API

- **Public Overpass** is slow and intermittently times out, especially the `overpass.kumi.systems` mirror. That limits how fast the facility index fills. A self-hosted Overpass instance or an India OSM extract removes the limit.

## KNOWN LIMITATIONS

- The region of interest is a bounding box, so it includes parts of neighbouring countries. Country comes from geocoding.
- OSM industrial mapping is uneven. An absence is reported as "not mapped", never as "no facility".
- Land context comes from OSM polygons (bounding-box distance), not a land-cover raster. The land-cover filter is deferred for that reason.
- Map, list and analytics filters are not yet shared across screens.
- Tokens are kept in `localStorage`. The rate limiter is per API replica.
- The EOX Sentinel-2 cloudless basemap is non-commercial (CC BY-NC-SA).

## NEXT PRIORITIES

1. Add `FIRMS_MAP_KEY` and backfill 12 months of history.
2. Let the facility index finish, or self-host Overpass.
3. Have analysts adjudicate the high- and elevated-priority queue, then retrain, review the model card and activate the model if it adds value over the rules.
4. Add ESA WorldCover as a feature, then the land-cover filter.
5. Configure Copernicus credentials and implement the SWIR hot-pixel check that makes `CONFIRMED` reachable.
6. Share filter state between map, list and analytics.
7. Add SSO/MFA and a shared rate limiter for multi-replica deployments.
