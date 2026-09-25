# ThermalTrace — Research Report (Condensed)

Consolidates: SIH26162 verification, remote-sensing science, data sources, competitive landscape, and prior art. Sources tiered: **T1** official (NASA/ESA/OSM/govt), **T2** peer-reviewed/patents, **T3** reputable secondary (NGO/industry), **T4** community repos, **T5** blogs (avoided as primary support).

## 1. The problem, verified

| Field | Value | Source tier |
|---|---|---|
| PS ID | SIH26162 | T1 (portal scrape, dated 2026-08-22) |
| Title | AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources Using NASA FIRMS, OSM & Satellite Data | T1 |
| Organization | National Technical Research Organisation (NTRO) | T1 |
| Category | Software | T1 |
| Theme | Miscellaneous | T1 |
| Dataset pointer | `firms.modaps.eosdis.nasa.gov/map` | T1 |
| **Expected solution (verbatim, the literal floor)** | (i) Classification/segregation of industrial fires from forest fires and other natural fires. (ii) GIS-based solution for data storage, visualization of output as map overlay. | T1 |
| Idea submission deadline (this PS) | 20 September 2026 | T1 (scrape) — re-verify live |

**Everything beyond the two-line expected solution — persistence scoring, evidence bundles, anomaly baselines — is value-added scope, not the literal ask.** The system must nail the floor before anything else is credible.

**Plain-language framing:** every thermal-anomaly satellite product answers "is this patch of ground hotter than it should be?" but not "why?". A refinery flare, a decades-old coal-seam fire, routine stubble burning, and an actual runaway industrial fire all look like the same warm dot to VIIRS/MODIS. NASA FIRMS says so itself — it is an anomaly detector, not a semantic classifier. Classification is what turns an undifferentiated stream of dots into something an analyst can triage.

## 2. NASA FIRMS — the core data source

**FIRMS** (Fire Information for Resource Management System) runs under NASA LANCE, serving MODIS and VIIRS thermal-anomaly detections near-real-time.

| | MODIS | VIIRS |
|---|---|---|
| Satellites | Terra + Aqua | Suomi-NPP, NOAA-20, NOAA-21 |
| Pixel size | ~1 km nadir | ~375 m nadir |
| Archive start | Nov 2000 | S-NPP Jan 2012, NOAA-20 Apr 2018, NOAA-21 Jan 2024 |
| Overpasses/day | ~4 | ~4–6 |
| Brightness fields | `brightness`, `bright_t31` | `bright_ti4`, `bright_ti5` |
| Confidence format | 0–100% | categorical: low/nominal/high |

**API:** free `MAP_KEY` via email signup (`firms.modaps.eosdis.nasa.gov/api/map_key/`). Rate limit 5,000 transactions/10-min window.
- Area API: `https://firms.modaps.eosdis.nasa.gov/api/area/csv/[MAP_KEY]/[SOURCE]/[WEST,SOUTH,EAST,NORTH]/[DAY_RANGE]/[DATE]`
- Country API: `.../api/country/csv/[MAP_KEY]/[SOURCE]/IND/[DAY_RANGE]` (India = `IND`)
- WMS/WFS layers available for direct map overlay without a CSV parser.

**Since Feb 2025, FIRMS itself ships an experimental "Static Thermal Anomalies" (STA) feature** — a 400m-grid mask of cells with ≥5 detections/year, cross-referenced against the (stale, ~2022) WRI Global Power Plant Database, separating vegetation from non-vegetation heat. NASA's own caveat: *"NASA FIRMS accepts no responsibility for the accuracy and comprehensiveness of the industrial/natural heat source data."* **This is the single most important competitive fact in this report** — cite it explicitly. It sets the technical bar to beat and the exact gap to fill: fresher, India-specific reference data and a real taxonomy, not a global annual static mask.

### What FIRMS cannot do (state these limitations in the product, not just this doc)
- Reported lat/lon is pixel center, not fire location; distorts 2–4× toward swath edges.
- Minimum detectable fire size (clear sky): MODIS ~100 m² day; VIIRS ~20 m² day, ~2 m² night. Sub-pixel sources are simply missed.
- Cloud/smoke fully blocks detection (documented: 2024 Jasper wildfire vanished from detections for days under cloud).
- Confidence is **not** a calibrated hit/miss probability — NASA states there's "no way to establish an optimal cutoff a priori."
- No native industrial/wildfire classification — exactly the PS's gap.
- Typical NRT latency ~3 hours → the product must say **"near-real-time,"** never "real-time."

## 3. Classification taxonomy (adopted)

Two orthogonal axes rather than one flat list — grounded in FIRMS's own vegetation/non-vegetation split, VIIRS Nightfire's temperature-regime discrimination, and (as prior art, not a template to copy) US Patent 11,308,595 B1's category set.

**Axis 1 — source type:** `industrial_flare` · `industrial_process_heat` · `mining_coal_fire` · `agricultural_burning` · `wildfire` · `other_unknown`
**Axis 2 — persistence class:** `transient` · `recurring` · `persistent`

| Source type | Primary evidence | Confusable with |
|---|---|---|
| Industrial flare | Near/inside industrial polygon, very high FRP, tight spatial stability, strong night recurrence | Process heat |
| Industrial process heat | Inside facility polygon, moderate/stable FRP, low jitter, no flame plume | Flare (hardest boundary — deliberately capped confidence) |
| Mining/coal-seam fire | Near mapped coalfield/mine polygon, multi-year recurrence, low FRP, minimal seasonality | Generic persistent industrial source |
| Agricultural burning | Cropland land cover, Oct–Nov / Apr–May seasonal clustering, short duration, spatially dispersed | Wildfire at forest-crop boundaries |
| Wildfire | Forest/scrub land cover, FIRMS vegetation flag, no industrial proximity, spreading footprint | Agricultural burning |
| Other/unknown | Evidence conflicting/insufficient | — deliberate escape hatch |

**Honest caveat, stated up front:** flare-vs-process-heat and coal-fire-vs-generic-persistent are genuinely hard boundaries. The system assigns a lower confidence ceiling to these pairs rather than pretending they're cleanly separable.

## 4. Persistence scoring (adopted, labeled PROPOSED)

```
persistence_score = detections_observed / expected_overpass_opportunities
```
over a trailing N-day window per ~375m grid cell, where `expected_overpass_opportunities` counts usable (non-cloud-obscured) satellite passes — not raw detection count, which conflates "actually persistent" with "got lucky with clear skies." Grounded in VIIRS Nightfire's stability-over-count logic and FIRMS's own ≥5-detection STA heuristic; this is a refinement, not a re-derivation, and is credited as such.

Proposed thresholds (30-day window, to be tuned against real data): `<0.15` → transient; `0.15–0.5` with seasonal clustering → recurring; `>0.5` sustained → persistent.

## 5. Data sources

| Source | Auth | Rate limit | License | India coverage | Role |
|---|---|---|---|---|---|
| NASA FIRMS (MODIS+VIIRS) | Free MAP_KEY | 5,000/10min | Public domain, attribution requested | Global | Core hotspot ingestion |
| VIIRS Nightfire | None for data, **but Data Use License mandatory since Jan 2025** | — | Restricted license — must review before use | Global | Flare weak-labels |
| OpenStreetMap / Overpass | None | Fair-use, shared instance | **ODbL — mandatory "© OpenStreetMap contributors" + link on every map view** | Uneven outside major industrial corridors | Facility polygons |
| WRI Global Power Plant DB | None | — | CC BY 4.0 | Global, stale (~2022) | Power-plant reference (same baseline NASA STA uses) |
| Global Energy Monitor trackers | Varies by tracker | — | Verify per tracker | India-detailed, updated ~quarterly | Coal/oil&gas/steel reference |
| CEA (Central Electricity Authority) | Govt open data | — | Govt terms | **Authoritative for India** | Primary Indian power-plant ground truth |
| Copernicus Sentinel-2 | Free account | Fair-use | Free + Copernicus attribution | Global, 10m, 5-day revisit | Optical confirmation (not primary detection) |
| Landsat 8/9 (USGS) | Free account | Standard | Public domain + USGS attribution | Global, 30m thermal | Optional hero-visual confirmation |
| Sentinel-1 SAR | Free account | Fair-use | Free + Copernicus attribution | Global, ~5–20m | Optional cloud-penetrating confirmation (stretch) |

**GOES is explicitly unusable** — geostationary sub-satellite points (75.2°W / ~137°W) don't cover India. INSAT-3D/3DR/3DS (ISRO) is a credible India-specific future-work mention, not realistic to integrate on this timeline.

**Data availability verdict:** every *feature-building* input is freely available. The real gap is *labels* — no public dataset ships ready-made "this detection is a flare/coal-fire/agri-burn/wildfire" labels. Addressed via weak supervision (§7).

## 6. Feature catalogue

| Feature group | Examples | Leakage risk | Recommended use |
|---|---|---|---|
| FIRMS-native | FRP, scan/track, confidence, day/night, satellite, detection count in window | Low | Direct model input |
| Spatial/OSM-proximity | Distance to nearest facility polygon (by type), inside/outside flag, facility type, OSM density (completeness proxy) | Medium — raw lat/lon must **never** be a direct feature, only derived distances | Direct model input |
| Temporal | Persistence score, day/night ratio, seasonal flag, 7/30/90-day recurrence | Low | Direct model input |
| Satellite-derived (optional tier) | NDVI, NBR, SWIR brightness ratio (flare-plume proxy) | Low | Confirmation evidence, secondary features |

## 7. ML architecture — decision and why

Framing: this is **multi-class tabular classification on engineered per-detection/cluster features**, not raw image classification — FIRMS already ships structured data, and the highest-value features are themselves engineered scalars.

| Approach | Verdict |
|---|---|
| XGBoost/LightGBM/Random Forest on tabular features | **Primary path** — matches data shape, trains on CPU in minutes, SHAP is exact and fast, workable on small/imbalanced label sets |
| CNN/ResNet/YOLO on raw imagery | Rejected as primary — needs far more labeled imagery than achievable on this timeline; imagery is a *confirmation* signal, not the primary input; FIRMS has already solved "where is the hotspot" |
| Vision Transformer | Rejected — data-hungry, weak explainability, no advantage here |
| Unsupervised anomaly detection | Adopted as a secondary pre-filter feeding the "insufficient evidence" pathway |

**v0 (this build): rule-based weak-label cascade**, not a trained model — stated as a real, deliberate limitation (see `00-audit-and-verification.md` §4), matching the artifact's own recommended build order: validate the labeling logic before investing further. A trained XGBoost classifier is the documented next step once the pipeline has produced enough weakly-labeled + spot-checked examples to train on.

### Labeling cascade (weak supervision)
1. VIIRS Nightfire match → weak-label `industrial_flare` (high confidence — Nightfire is itself a validated flare product; gated by its Data Use License).
2. Facility (power plant/refinery) proximity + high persistence → weak-label `industrial_process_heat`.
3. Known coalfield polygon (e.g. Jharia) + multi-year persistence → weak-label `mining_coal_fire`.
4. Cropland land cover + Oct–Nov/Apr–May seasonal window + short duration → weak-label `agricultural_burning`.
5. Forest/scrub land cover + no industrial proximity → weak-label `wildfire`.
6. Sentinel-2 spot-check on a sample; manual adjudication of the hard boundary cases (flare-vs-process-heat, coal-fire-vs-generic-persistent) — these become the highest-value labels precisely because they're hard.

**Mandatory: spatial-block + temporal train/test splitting, never random.** Random splitting on geo-tagged detection data is well documented to inflate apparent accuracy by letting models memorize lat/lon-correlated patterns rather than learning transferable signal. (The artifact cited a specific 2026 paper — Soltan & González-Martínez — for this exact finding; that citation could not be independently re-verified this session and should be treated as unconfirmed, but the underlying leakage risk is real, well-established practice regardless, and the rule is retained as non-negotiable.) Train on Region A (e.g. Gujarat/Punjab), validate on Region B (Jharkhand), test on Region C (Maharashtra/Rajasthan); raw lat/lon is never a direct model feature.

## 8. Competitive landscape

| Existing solution | Strength | Weakness | ThermalTrace's differentiation |
|---|---|---|---|
| NASA FIRMS Static Thermal Anomalies | Official, authoritative, closest existing thing to this PS | Experimental, stale WRI-only reference data, no fine-grained taxonomy, no evidence/confidence UI, not India-tuned | India-fused reference layer (OSM+GEM+CEA), full taxonomy, transparent evidence, purpose-built dashboard |
| FSI FAST 3.0 (India Forest Survey) | Official, VIIRS-based, mature | Forest-fire scoped only | Industrial/persistent-source focus is the explicit gap |
| EFFIS | Mature engineering | Europe-scoped, forest-fire focused | Different geography, different classification target |
| Capterio / FlareIntel | Commercial flare-tracking via Nightfire | Paywalled, flare-only scope | Open, broader taxonomy, India context |
| Kayrros | Commercial satellite intelligence | Closed methodology | Transparent, explainable |
| "Pyrosight" (`pyrosights.vercel.app`) | A public deployment exists under this exact PS ID — a real competing team | Could not be inspected (client-rendered SPA, static fetch returned no content) | Unknown — flagged as a real competitive signal, not analyzed further; worth a manual look before the pitch is finalized |

**Qualitative competition assessment: medium-high.** A basic "FIRMS points on a map" is a low-effort, common hackathon pattern many teams will attempt. The specific combination this PS actually demands — a defensible taxonomy, honest persistence scoring, and evidence-grade confidence — is a materially harder bar most attempts won't clear.

## 9. Prior art & IP risk (not legal advice)

**US Patent 11,308,595 B1** — "Thermal Anomaly Detection and Classification," EarthDaily Analytics (formerly Descartes Labs), filed 2020-06-30, granted 2022-04-19. Independently confirmed via Google Patents. Claims a two-stage (quick + robust) detection workflow and classification into ignition events, ongoing fires, stationary targets, agricultural anomalies, gas flares, and wildfires, using Landsat/MODIS at petabyte cloud-compute scale.

**Implication:** the classification *concept* (splitting thermal anomalies into flare/agricultural/wildfire/stationary categories) is not novel and must never be pitched as such. The defensible novelty claims for ThermalTrace are narrower and specific:
1. An **India-specific fused reference layer** (OSM + Global Energy Monitor + CEA) — fresher and more India-detailed than the stale WRI-GPPD baseline NASA's own STA uses.
2. A **transparent, evidence-bundle confidence system** (not a bare label) purpose-built for analyst trust — the patent and FIRMS STA both output labels/masks, not traceable evidence chains.
3. An **integrated open pipeline** (ingestion → classification → GIS → evidence) — FIRMS STA is a backend layer with no dashboard; commercial tools (Kayrros/Capterio) are closed and narrower.

A secondary, narrower patent (Schlumberger, unlit-flare detection) exists as adjacent context for the flare sub-category and is not a direct conflict.

## 10. Licensing / attribution obligations (binding on the product, not just this doc)

| Source | Requirement |
|---|---|
| NASA FIRMS | Attribution requested (not mandatory): cite "NASA FIRMS," link to firms.modaps.eosdis.nasa.gov |
| VIIRS Nightfire | **Mandatory Data Use License** (since Jan 2025) — must be reviewed and complied with before any public use |
| OpenStreetMap | **Mandatory:** "© OpenStreetMap contributors" visible on every derived map view, linking to openstreetmap.org/copyright |
| Copernicus Sentinel | "Contains modified Copernicus Sentinel data [year]" |
| USGS Landsat | Public domain, USGS attribution requested |
| WRI GPPD | CC BY 4.0 attribution required |

## 11. Scientific honesty commitments (binding on product copy, UI, and pitch)

- Never say "real-time" — say "near-real-time" (FIRMS NRT latency ~3 hours).
- Never present model confidence as a calibrated probability without calibration analysis to back it.
- Never claim the system replaces analysts — it is a triage/evidence aid.
- Never claim classification concept novelty — differentiate on data fusion, transparency, and integration instead.
- Always allow and clearly surface an "insufficient evidence" output state.
- Always disclose that labels are weak-supervised, not ground-truthed, until/unless a real validated label set exists.
