# ThermalTrace — SIH26162 Idea Submission Package

## Differentiation (why this, not just FIRMS or a generic dashboard)

**Why not just NASA FIRMS?** FIRMS is an anomaly *detector*, not a classifier — it says a pixel is hot, not why. That gap is the entire PS.

**Why not just point at FIRMS's own "Static Thermal Anomalies" feature?** STA (since Feb 2025) is the closest existing thing to this PS, and we cite it explicitly rather than pretend it doesn't exist. It's a global annual mask keyed to a stale (~2022) WRI power-plant database, with no fine-grained taxonomy, no confidence/evidence UI, and no dashboard. ThermalTrace differentiates on three specific things: (1) a fresher, India-specific fused reference layer (OSM + Global Energy Monitor + CEA, not WRI alone), (2) a transparent evidence bundle per detection instead of a bare mask, (3) an integrated open pipeline with an actual analyst-facing GIS dashboard.

**Why AI, if the classifier is rule-based right now?** Because the honest answer to "is this XGBoost or is it duct tape?" matters more than sounding impressive — see `01-research.md` §7. The rule cascade *is* the documented, correct v0 given zero labeled data exists on day one; it directly produces the weakly-labeled examples a trained classifier needs next. This is stated as a roadmap item, not hidden.

**Why persistence, why evidence, why "insufficient evidence" as an output?** A refinery flare burning every night is normal; a new hotspot at a facility with no thermal history is not. Treating both as "a fire was detected" throws away the signal that actually matters to an analyst. And a system that can say "I don't have enough evidence yet" is more trustworthy to a security-adjacent evaluator than one that always outputs a confident label — false-positive classifications cost analyst time.

**What we are not claiming:** not real-time (near-real-time — FIRMS's own ~3hr NRT latency), not a replacement for analysts or for FIRMS/Kayrros/Capterio, not globally validated, not a novel classification *concept* (US Patent 11,308,595 B1 already covers a similar taxonomy — our novelty is the India-specific data fusion and evidence transparency, not the taxonomy idea itself).

## Predicted judge questions — strong vs. weak answers (selected, see `01-research.md` for full grounding)

| Question | Weak answer to avoid | Strong answer |
|---|---|---|
| "Isn't this just FIRMS STA with a new UI?" | "No one else does this" | Name STA explicitly, name the three specific differentiators above |
| "What's novel about your classification scheme?" | "We invented this taxonomy" | "The taxonomy concept has prior art (US 11,308,595 B1) — our contribution is India-specific data fusion and evidence transparency, not the category list" |
| "How accurate is your classifier?" | A bare, unqualified accuracy number | State it's a rule-based v0 pending trained-model validation, and that any future accuracy number will be reported on a spatial+temporal held-out split, never a random split |
| "Is this real-time?" | "Yes" | "Near-real-time — FIRMS's own documented NRT latency is ~3 hours" |
| "What if your API is down during the demo?" | Panic / no plan | Offline demo mode with a visible "DEMO DATA" indicator — designed to survive exactly this |
| "Can this replace analysts?" | "Eventually, yes" | "No — it's a triage aid that surfaces evidence; the analyst decides" |
| "How do you tell a flare from process heat?" | Claim it's solved | Name it as the hardest boundary in the taxonomy, explain the deliberately lower confidence ceiling |

## 6-slide idea submission content

**Slide 1 — Title:** SIH26162 · AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources Using NASA FIRMS, OSM & Satellite Data · NTRO · Category: Software · Theme: Miscellaneous.

**Slide 2 — Idea:** ThermalTrace — evidence-based industrial thermal source intelligence. Proposed solution: FIRMS near-real-time ingestion → India-tuned OSM/GEM/CEA facility fusion → rule-based (roadmap: ML-upgraded) source-type + persistence classification → evidence bundles, not bare labels → PostGIS GIS dashboard. Problem → Solution → Outcome: a raw hotspot can't distinguish flare from wildfire from crop-burn → fuse infrastructure context + transparent classification → analysts get a type, a persistence class, and the evidence, not just a dot. Innovation: existing capability (FIRMS STA, a granted taxonomy patent, commercial flare intelligence) already exists and is named explicitly; our innovation is India-specific fused reference data + transparent evidence + one integrated open pipeline none of the existing options combine.

**Slide 3 — Technical approach:** FIRMS Area/Country API + OSM Overpass (ingestion) → PostGIS/GeoPandas (spatial join, persistence scoring) → rule-based classifier v0 with a documented path to XGBoost/LightGBM + SHAP once weak-labeled data exists → FastAPI backend → React/MapLibre GIS dashboard.

**Slide 4 — Feasibility:** Data — high, every input source is free and India-accessible. Technical — high, mature open-source geospatial stack. Compute — high, CPU-only, no GPU dependency. Challenges: label scarcity, FIRMS spatial-resolution ambiguity, flare-vs-process-heat boundary, uneven OSM coverage in India. Mitigations: weak-supervision cascade with imagery spot-checks, distance-decay evidence instead of binary attribution, explicit lower confidence ceiling on hard boundaries, multi-source facility fusion roadmap.

**Slide 5 — Impact:** Target audience — government geospatial/infrastructure-monitoring analysts (NTRO context). Impact — faster, evidence-backed triage of thermal anomalies near industrial infrastructure. Benefits: Social (faster situational awareness), Economic (less manual cross-referencing time), Environmental (visibility into recurring burn/combustion sources), Operational (transparent evidence supporting, not replacing, analyst decisions).

**Slide 6 — References:** Official SIH26162 PS · NASA FIRMS documentation · OSM Wiki/Overpass · US Patent 11,308,595 B1 (Google Patents) · Global Energy Monitor trackers · Central Electricity Authority.

## Demo script (5 minutes)

0:00–0:30 — problem framing: one warm dot, five possible meanings.
0:30–1:30 — open the India map (live or demo data, clearly labeled), point to the classified overlay.
1:30–2:30 — click a high-persistence industrial event, walk the evidence bundle.
2:30–3:30 — click an agricultural-burning seasonal cluster as the classification contrast case.
3:30–4:15 — deliberately show one "insufficient evidence — manual review required" case, and say why that's a feature, not a bug.
4:15–5:00 — close on evidence transparency, near-real-time framing, and the honest roadmap (rule-based v0 → trained classifier next).

**Open item before this is submission-ready:** re-verify the Theme field and full official text live on sih.gov.in (see `00-audit-and-verification.md` §2 — the direct portal fetch this session couldn't reach SIH26162's page directly), and spend 10 minutes looking at `pyrosights.vercel.app` manually (it renders client-side, so it needs an actual browser look, not a fetch) to know what the named competitor has actually built.
