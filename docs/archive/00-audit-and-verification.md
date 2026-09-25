# ThermalTrace — Current State Audit & Source Verification

**Date:** 2026-09-05
**Status:** Pre-build. No application code exists yet anywhere.

## 1. What actually exists

| Location | Contents |
|---|---|
| `https://github.com/saad-46/ThermalTrace.git` | One file: `README.md`, 14 bytes, contents `# ThermalTrace`. No other commits, branches, or files. |
| `D:\Projects\ThermalTrace` (local) | `git init` only — zero commits, no remote configured. |
| Claude artifact `b92b0db4-ae52-466f-8a9a-6c35ff0e8daf` | **Not a prototype application.** It is a ~5,000-line HTML research report ("What kind of hot spot is this, really?") — a deep-research dossier covering SIH26162 verification, remote-sensing science, data sources, ML architecture choice, prior art/patents, risk register, judge Q&A, and 6-slide pitch content. No frontend, backend, database, or ML code is contained in it. |

**Conclusion:** there is nothing technical to reverse-engineer, preserve, or fix. The engagement starts from zero code, but not from zero research — the artifact is a genuinely strong, mostly self-critical research pass and is treated below as a first draft to *verify*, not a ground truth to *copy*.

## 2. Independent verification performed this session

| Claim in artifact | Verification method | Result |
|---|---|---|
| Official PS text (background/description/expected solution) | Cross-checked against a structured scrape of the SIH2026 portal (`NoBugNinja/Smart-India-Hackathon-SIH-2026-Problem-Statements`, GitHub, dataset dated 2026-08-22) | **Confirmed, near-verbatim match.** See `01-sih26162-research.md`. |
| PS Theme field — artifact reported a 3-way conflict ("Disaster Management" vs "Miscellaneous" vs "Space Technology") | Same scrape | Resolves to **"Miscellaneous."** Still recommend a final live glance at sih.gov.in before the submission is locked, since the direct portal fetch attempted this session paginated only through SIH26001–SIH26025 and could not reach SIH26162 directly (portal likely paginates/filters server-side in a way plain fetch doesn't drive). |
| US Patent 11,308,595 B1 is real, granted, and covers a thermal-anomaly classification taxonomy including gas flares/agricultural anomalies/wildfires/stationary targets | Fetched Google Patents directly | **Confirmed.** Assignee EarthDaily Analytics (formerly Descartes Labs), filed 2020-06-30, granted 2022-04-19. Categories: ignition events, ongoing fires, stationary targets, agricultural anomalies, gas flares, wildfire detection. This is real, specific prior art — the taxonomy *concept* is not novel and must never be pitched as such. |
| NASA FIRMS API mechanics (Area/Country API, MAP_KEY auth, 5,000 req/10-min limit, ~3hr NRT latency) | Not independently re-fetched this session (matches long-standing, stable, well-documented NASA FIRMS behavior) | Treated as reliable; will be re-verified live against the actual FIRMS docs the moment we write the ingestion client. |
| Overpass API (OSM) reachable, no auth required | Live test query against `overpass-api.de/api/interpreter` | **Confirmed working**, returned valid JSON. |
| A competing/prior SIH26162 submission exists publicly ("Pyrosight — Industrial Fire Screening") | Found via web search, `pyrosights.vercel.app` | Site exists but is a client-rendered SPA; static fetch returned only the page title, no content could be extracted. Noted as a competitive signal (see `04-competitive-analysis.md`) but not analyzed in depth — could not access enough content to say more than "a team has publicly deployed something under this PS ID." |

## 3. The single most important operational finding this session

The original brief did not mention a deadline. Independent research surfaced one:

- A scraped SIH portal record lists **"deadline for idea submission": 20 September 2026** for this PS specifically.
- Independent web search confirms the general SIH 2026 process: college-level internal hackathon first, then SPOC nomination/idea submission on the national portal — commonly cited as **by 30 September 2026** — with individual institutions running internal rounds in early-to-mid September 2026.
- The user confirmed (via clarifying question) they are **already selected and prepping for SPOC idea submission** — i.e., the runway is **roughly 1–3 weeks**, not the multi-week/enterprise timeline the original 35-phase brief implicitly assumes.

**This changes prioritization materially.** The plan going forward (see `ROADMAP.md`) is: condensed, high-quality docs → a real running vertical slice (ingestion → PostGIS → rule-based classification → GIS map) → idea-submission package, in that order, rather than the full 30+ document enterprise suite before any code is written.

## 4. What is retained from the artifact vs. redesigned

**Retained (validated, adopted as-is or near-as-is):**
- Two-axis taxonomy: source-type × persistence-class, independently confidence-scored.
- Primary model choice: gradient-boosted trees (XGBoost/LightGBM) on engineered tabular features, not CNN/YOLO — correct given FIRMS data ships already-structured, not raw imagery.
- Opportunity-normalized persistence score, not raw detection count.
- Mandatory spatial + temporal (never random) train/test split, citing the Soltan & González-Martínez (2026) F1-inflation finding — **this citation could not be independently re-verified this session** (no DOI/venue was surfaced by search) and is flagged accordingly wherever it's referenced going forward; the *underlying engineering principle* (spatial/temporal leakage in geo-tagged data is real and well-documented elsewhere) is sound regardless and is retained as a hard rule.
- Weak-supervision labeling cascade (Nightfire → flare; facility-proximity+persistence → process heat; coalfield polygon → mining fire; seasonal cropland → agri burn; forest/no-industrial-proximity → wildfire), with imagery spot-check and manual adjudication of hard cases.
- Evidence-bundle-over-bare-label design, "insufficient evidence" as a legitimate output state, near-real-time (never "real-time") framing.
- Demo case studies: Jamnagar refinery flares, Jharia coalfield fires, Punjab/Haryana stubble burning, Uttarakhand wildfires.

**Redesigned / de-scoped for the demo-first build:**
- The 30+-document enterprise doc suite → consolidated into 5 docs (this audit, research, PRD, architecture, roadmap) plus the SIH submission package. Depth preserved; file count cut.
- RBAC/multi-role auth, alerts (email/webhook), report PDF export, mobile PWA, admin/model-health screens → documented as designed-for but **not built** in the first working slice; explicit roadmap items, not silently dropped.
- ML classifier → **v0 is rule-based** (per the artifact's own recommended build order: "validate the weak-supervision approach... before investing in dashboard polish"), not a trained XGBoost model, because no labeled data exists yet on day zero and a real trained model needs the ingestion pipeline running first to have anything to train on. This is stated as a real limitation, not hidden.

## 5. Production blockers identified

1. **No FIRMS MAP_KEY yet** — free, instant, self-serve at `firms.modaps.eosdis.nasa.gov/api/map_key/`, but requires the user's own email signup; Claude Code cannot obtain this. Ingestion adapter is built against the real API contract with a deterministic offline fallback so this doesn't block development.
2. **No labeled ground truth** — inherent to the problem, addressed via the weak-supervision plan, not solvable by more research.
3. **VIIRS Nightfire Data Use License** (mandatory since Jan 2025) must be read and complied with before using Nightfire records for flare weak-labels in any public demo — not yet done, flagged as a task.
4. **OSM industrial tagging in India is uneven** outside major corridors — confirmed as a real, structural data-quality constraint, not a bug to fix.
