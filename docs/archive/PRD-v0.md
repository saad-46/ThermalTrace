# ThermalTrace — Product Requirements Document

## 1. Executive summary
ThermalTrace turns raw NASA FIRMS thermal-anomaly detections into evidence-backed intelligence: it fuses each detection with industrial infrastructure context (OSM/GEM/CEA), computes temporal persistence, applies a transparent rule-based classifier (source type × persistence class), and presents the result as a traceable evidence bundle on a GIS map — not a bare AI label. Built for SIH26162 (NTRO): "AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources Using NASA FIRMS, OSM & Satellite Data."

## 2. Problem statement
See `01-research.md` §1 for the verified official text. The literal floor: (i) classify industrial vs. forest/natural fires, (ii) GIS map-overlay visualization. FIRMS itself cannot do (i); nothing in the open ecosystem does (i)+(ii) together with India-specific data and transparent evidence (see competitive analysis).

## 3. Target users
- **Primary (SIH judges' framing):** an NTRO geospatial/infrastructure-monitoring analyst who needs to triage which of today's hundreds of FIRMS hotspots deserve attention.
- **Secondary:** a safety officer at a facility wanting to see their own site's thermal history.
- **Demo audience:** SIH judges evaluating technical depth, honesty, and differentiation.

## 4. User journey (also the demo script)
1. Analyst opens the India map, sees classified thermal detections as an overlay (not raw FIRMS dots).
2. Filters to a region/classification/persistence class of interest.
3. Clicks a detection → sees its evidence bundle: FRP, distance/type of nearest facility, persistence score, classification, confidence, and *why* — plus counter-evidence and, where confidence is genuinely low, an explicit "insufficient evidence" state.
4. Compares against a facility's historical detection pattern.
5. Trusts the system specifically because it shows its work and admits uncertainty rather than always outputting a confident label.

## 5. Functional requirements (this build)

**P0 — must work, is the literal PS floor:**
- FR1: Ingest NASA FIRMS thermal detections (VIIRS + MODIS) for India, live via Area/Country API when a MAP_KEY is present, else deterministic offline demo data with a visible "DEMO DATA" indicator.
- FR2: Ingest OSM industrial facility polygons (refineries, power plants, mines/quarries) via Overpass for India regions.
- FR3: Spatially join each detection to its nearest facility (distance, type, inside/outside).
- FR4: Classify each detection: source type (industrial_flare / industrial_process_heat / mining_coal_fire / agricultural_burning / wildfire / other_unknown) + persistence class (transient/recurring/persistent), via the documented rule-based cascade — **industrial vs. natural/agricultural is the one split that must be visibly reliable.**
- FR5: Attach a human-readable evidence bundle (not a bare label) to every classification, including supporting *and* counter-evidence.
- FR6: Store everything in PostGIS with proper spatial indexing.
- FR7: Serve a REST API (FastAPI) for events, facilities, and map data.
- FR8: Render a GIS map overlay (MapLibre) showing classified detections, filterable, with an evidence panel on click.

**P1 — major differentiators, built if P0 is solid:**
- FR9: Persistence scoring (opportunity-normalized, per `01-research.md` §4) with a visible score/trend per location.
- FR10: Facility-level rollup — all historical detections tied to one facility.
- FR11: "Why now?" panel for newly-persistent or elevated events.
- FR12: Data Quality panel — ingestion run status, last successful pull, records in/rejected, live vs. cached indicator.

**P2 — documented, not built in this pass:** trained ML classifier (needs labeled data this pipeline itself will help produce), SHAP explainability, alerts (email/webhook), PDF reports, RBAC/multi-role auth, mobile PWA, active-learning analyst feedback loop, Sentinel-2 imagery confirmation.

## 6. Non-functional requirements
- **Scientific honesty (non-negotiable):** "near-real-time" not "real-time"; confidence never presented as a calibrated probability without calibration; "insufficient evidence" is a legitimate, visibly-used output state; every classification traceable to stored evidence, never a black-box label.
- **Resilience:** the system must run a convincing demo with zero internet/API access (offline demo mode), and must clearly distinguish LIVE vs DEMO/CACHED data in the UI at all times — never silently substitute one for the other.
- **Attribution:** OSM ODbL notice and NASA FIRMS citation are present on every map view, unconditionally.
- **Reproducibility:** every ingestion run is logged (source, timing, record counts, failures) so results are auditable.

## 7. Explicit non-goals (this build)
- Not a wildfire *emergency-response* system — no claim of operational alerting readiness.
- Not a replacement for analysts, FIRMS, or commercial tools (Kayrros/Capterio) — a triage/evidence aid.
- Not globally validated — designed and reasoned about for India; the pipeline architecture would generalize, the reference-data fusion would not without re-sourcing.
- No CNN/YOLO imagery pipeline, no blockchain, no LLM chatbot layer, no native mobile app, no 3D globe — the artifact's own "what NOT to build" list, retained because the reasoning still holds.

## 8. Success metrics for the SIH submission
- The two literal PS deliverables work end-to-end on real (or clearly-labeled demo) data: a classified map overlay, distinguishing industrial from natural/agricultural fire.
- At least one demo case study each for: industrial flare (Jamnagar-style), persistent mining fire (Jharia-style), agricultural burning (Punjab-style), wildfire (Uttarakhand-style), and one deliberately low-confidence "insufficient evidence" case.
- Every classification shown in the demo has a real, inspectable evidence bundle — not a decorative confidence bar.
- Judges can ask "why isn't this just FIRMS STA with a new UI?" and get a specific, honest, three-point answer (see `SIH-SUBMISSION.md`).

## 9. Risks (see `01-research.md` §7, §9, `00-audit-and-verification.md` §5 for detail)
Label scarcity → rule-based v0, not silently upgraded to "AI-trained" language. FIRMS resolution/geolocation ambiguity → distance-decay evidence, never binary inside/outside claims presented as certain. OSM completeness gaps in India → multi-source fusion path documented, OSM-only in this pass, explicitly flagged as a known gap. Timeline (idea submission ~20 Sep 2026) → demo-first build order.
