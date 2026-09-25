# Feature integration log — production consolidation (2026-09-25)

Each entry names the feature, where it came from, why it matters, and where it now lives.

---

**Feature:** Local facility index (scheduled OSM tile sync)
**Source:** New. It addresses the production bottleneck: the Demo's whole-India query timed out and production's per-cell queries were slow.
**Why it matters:** Facility attribution is the core of industrial-vs-natural classification. Public Overpass took about 30 s per 5.5 km cell, so most events waited hours for context.
**Production implementation:**
- **Backend**: `services/facility_sync.py`, which registers 1° tiles from event density, syncs the busiest first, refreshes every 30 days, retries failures after 6 h, and re-attributes events in each synced tile.
- **Queries**: `integrations/overpass.py` split into tile (facilities) and land queries. `services/enrichment.py` uses land-only queries once the surrounding tiles are fresh.
- **Jobs and access**: `facility_sync` job (bulk lane, hourly, drains its backlog), `python -m app.cli sync-facilities`, and `GET /api/v1/sources/facility-index`.
- **Frontend**: coverage panel and "Sync next 4 facility tiles" trigger on Data sources.
- **Mobile:** — (operations screen, desktop only)
- **Database:** `facility_sync_tiles` (migration 0003)
- **Measured:** one tile took 24 s and returned 2,233 OSM features. OSM error rate fell from 15.2 % to 3.0 %.
- **Tests:** `test_facility_tiles_cover_attribution_radius`, `test_overpass_split_queries`
- **Status:** IMPLEMENTED. The background sync is working through 297 tiles.

---

**Feature:** Triage priority with explanation
**Source:** Prototype (`computePriority`, `ExplainabilityPanel`), re-based on real evidence.
**Why it matters:** Analysts need a principled order for a queue of more than 1,300 events. The Prototype's idea is kept, but the score is built only from observed and derived evidence, and it is explicitly labelled *not a risk score*.
**Production implementation:**
- **Backend**: `processing/priority.py`, with five 20-point components: thermal intensity, persistence, industrial proximity, classification confidence and sensor corroboration. It is computed in `pipeline.analyse_event`.
- **API**: `priority_score` on events, `priority_components` on the bundle, `sort=priority`, `min_priority`, and a `priority` property in the GeoJSON.
- **Frontend**: `components/triage.tsx` (PriorityPill, PriorityPanel), the Events queue sorted by priority by default, the Priority column, and panels on the summary tab and event page.
- **Mobile:** "Priority" queue (default), pills on list items, and a "Why prioritised" evidence card.
- **Database:** `thermal_events.priority_score` (indexed), `priority_components` (migration 0003).
- **Tests:** `test_priority_components_and_tiers`, integration `test_priority_search_training_export_and_facility_profile`, Vitest PriorityPill/PriorityPanel.
- **Status:** IMPLEMENTED.

---

**Feature:** Global search
**Source:** Prototype (`GlobalSearch`, client-side over the mock array), rebuilt server-side.
**Why it matters:** Jumping straight to an event, district, facility or coordinate is basic analyst navigation.
**Production implementation:**
- **Backend**: `GET /api/v1/search`, which matches event public ids, districts/states (aggregated with centroids), facilities/operators and class labels. A coordinate query returns the nearest events within 25 km.
- **Frontend**: `components/GlobalSearch.tsx` in the desktop header. It has debounced queries, keyboard navigation, the `/` shortcut and combobox ARIA.
- **Mobile:** search on the Events screen.
- **Database:** pg_trgm GIN indexes on `facilities.name` and `thermal_events.admin_district` (migration 0003).
- **Tests:** `test_search_coordinate_parsing`, integration search assertions, and the E2E desktop search step.
- **Status:** IMPLEMENTED.

---

**Feature:** Evidence chain
**Source:** Prototype (`buildEvidenceChain`, `EvidenceChain`).
**Why it matters:** It gives a one-glance narrative of how the evidence builds up to the classification. Missing stages are shown as missing, not glossed over.
**Production implementation:**
- **Frontend**: `buildEvidenceChain()` in `components/triage.tsx`, built purely from real bundle fields. It has 8 stages, including a weather stage the Prototype lacked.
- **Where it appears**: summary tab, event page, and a mobile evidence card.
- **Backend / Database:** — (derived from the existing bundle)
- **Tests:** Vitest `evidence chain` (stage order, missing imagery, "not yet retrieved" facility state)
- **Status:** IMPLEMENTED.

---

**Feature:** Per-day persistence strip
**Source:** Prototype (`PersistenceTimeline`).
**Why it matters:** It makes gaps between detection days visible. That is what separates *persistent* from *recurring*.
**Production implementation:** `PersistenceStrip` in `components/triage.tsx`, shown in the persistence panel (desktop History tab, event page and mobile card).
**Tests:** Vitest `PersistenceStrip shows gap days explicitly`.
**Status:** IMPLEMENTED.

---

**Feature:** Attribution radius rings
**Source:** Prototype (proximity-buffer overlay).
**Production implementation:** 2 km (the rule threshold) and 10 km (the facility search radius) dashed rings around the selected event. They are a toggleable map layer ("Attribution radius").
**Status:** IMPLEMENTED.

---

**Feature:** Training feedback dataset export
**Source:** New, from the brief's §23.
**Why it matters:** It gives a continuously improving label set: event → prediction → analyst label → features → reviewer → model version.
**Production implementation:**
- **Backend**: `GET /api/v1/ml/training-dataset?format=json|csv`, supervisor or above. Every export is written to the audit log. Features are taken as of the time of review. The label semantics are documented in the response.
- **Frontend**: "Export training dataset (CSV)" on Analytics → Analyst feedback loop.
- **Tests:** integration test (label, model version, features, reviewer, CSV header, 403 for analysts).
- **Status:** IMPLEMENTED.

---

**Feature:** Alert cooldown with recorded suppression
**Source:** New, from the brief's §30.
**Why it matters:** It prevents notification floods. Every match still creates an in-app alert, and each suppressed email or push is recorded, so nothing disappears silently.
**Production implementation:**
- **Backend**: `alerts.in_cooldown()` / `deliver()`. The cooldown clock starts only after a *real* external send.
- **Database**: `alert_rules.cooldown_minutes`, `last_notified_at` (migration 0003).
- **Frontend**: cooldown field (default 60 min) and a rule summary.
- **Tests:** `test_alert_cooldown_window`, integration `test_alert_cooldown_suppresses_external_delivery`.
- **Status:** IMPLEMENTED.

---

**Feature:** Qualitative confidence decomposition
**Source:** New, from the brief's §65-L.
**Production implementation:** each confidence component is shown as Strong, Moderate, Weak or **Unavailable**. It is Unavailable when the evidence is missing, never "weak" by default.
**Tests:** Vitest `qualitative confidence decomposition`.
**Status:** IMPLEMENTED.

---

**Feature:** Facility thermal-activity profile
**Source:** New, from the brief's §65-B (the wording avoids "risk").
**Production implementation:** a profile on `GET /facilities/{id}/events`: events, persistent, active, analyst-confirmed, detections, peak FRP, activity window and classification mix. The facility page shows a metrics row and chips.
**Status:** IMPLEMENTED.

---

**Feature:** Weather in the event timeline (evidence stream)
**Source:** New, from the brief's §65-E.
**Status:** IMPLEMENTED (in `repositories/events.build_timeline`).

---

**Feature:** Tablet layout
**Source:** New, found by testing at 820 px.
**Status:** IMPLEMENTED. The icon-rail navigation is used between 768 and 1100 px, and the evidence panel is 340 px wide.

---

## Considered and not migrated

| Feature | Source | Reason |
|---|---|---|
| Hand-weighted classification engine | Prototype | Its outputs are not probabilities. Production's cascade and confidence engine are stricter and evidence-based. |
| Guided demo walkthrough | Prototype | Meaningful only over synthetic data. |
| "Why ThermalTrace" card | Prototype | Marketing, not functionality. |
| `localStorage` analyst state | Prototype | Production persists this server-side with an audit trail. |
| Next.js / Zustand / Recharts / Tailwind | Prototype | These would duplicate production's stack. No capability gap. |
| Land-cover filter | Prototype | OSM land context covers too few events. It returns with a land-cover raster (roadmap). |
| Demo vertical slice code | Demo | Superseded. It was the base of the production rebuild. |
