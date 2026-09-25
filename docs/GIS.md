# GIS processing

All geometries use `geography(…, 4326)`. Distances are in metres on the spheroid, and GiST indexes back every spatial predicate.

## 1. Event clustering (`processing/clustering.py`)

Detections are processed in acquisition order. A detection joins an event when both of these hold:

- its distance to the event's running centroid is ≤ `CLUSTER_RADIUS_M` (1500 m), and
- `|acq_time − event.last_detected|` ≤ `CLUSTER_GAP_DAYS` (5 d).

Otherwise it seeds a new event. Candidate lookup uses a uniform grid (cell ≈ the radius) over a 3×3 neighbourhood, so each pass costs O(n).

After assignment, per-event statistics are recomputed in SQL: centroid, first and last detection, counts, sensors, FRP max/mean/std, night fraction, and a buffered convex-hull footprint. Daily rows (`thermal_observations`) are rebuilt at the same time.

An event is `active` while it has been seen within the gap tolerance, and `dormant` after that.

*Measured on real data (7-day South Asia NRT, 2026-09-25): 4,737 detections → 1,351 events in 3.3 s.*

## 2. Persistence (`processing/persistence.py`)

The engine stores every metric it uses: active days, span, observation frequency, longest gap, FRP coefficient of variation, sensor agreement, recurrence count (earlier separate events within 1.5 km in the prior 365 days), and history depth.

| Class | Rule |
|---|---|
| **PERSISTENT** | (active days ≥ 5 **and** frequency ≥ 0.5 **and** span ≥ 5) **or** recurrence ≥ 3 |
| **RECURRING** | (active days ≥ 2 **and** span ≥ 2) **or** recurrence ≥ 1 |
| **TRANSIENT** | otherwise |

The score is 0.35·min(active/10, 1) + 0.25·frequency + 0.20·min(span/30, 1) + 0.20·min(recurrence/3, 1).

When an event spans the entire loaded history, the rationale says so ("true duration may be longer"). Seven days of data cannot establish a year-long source.

## 3. Facility attribution (`processing/attribution.py`)

Attribution is never a binary inside/outside test. Every facility within 10 km is ranked by:

`score = relevance(type) × exp(−distance / 1500 m) × facility.confidence × status_factor`

- **Relevance** examples: flare stack 1.0, refinery or oil & gas 0.95, steel 0.9, coal mine 0.85, coal power 0.8, cement 0.75, factory 0.45, industrial area 0.4, solar or other power 0.2.
- **Status factor**: retired or cancelled facilities get 0.3.

The top 8 are stored in `event_facility_links` with distance, bearing, rank and score. Evidence is phrased as distances, for example: *"Thermal event is 566 m NNE of a mapped steel plant (ArcelorMittal Nippon Steel India; source osm)"*.

**Facility consolidation** (`services/facilities.py`) matches a new source record to an existing facility when both hold:

- the type is compatible (same group: oil, power, heavy, mine or waste), and
- the distance is within 1.5 km for large types or 600 m otherwise.

Confidence then becomes 1 − Π(1 − c_source), with OSM at 0.5, WRI 0.6, GEM 0.7 and CEA 0.75, capped at 0.95. A registry's specific type (e.g. coal power) overrides OSM's generic one (e.g. power, fuel unknown).

## 4. Land context

OSM land-use polygons (cropland, forest, scrub, residential) within about 1.5 km are stored in `land_context`. The distance is 0 when the event lies inside the feature's bounding box; otherwise it is measured to the feature centre. This is an approximation, and it is documented as one.

## 5. Weather and potential dispersion direction

Weather comes from Open-Meteo at the hour of the event's last detection. The wind direction is meteorological (the direction the wind comes *from*).

The **potential dispersion direction** is (direction + 180°) mod 360. It is drawn as a vector whose length is scaled by wind speed.

**It is not plume tracking**, and the UI and reports say so.

## 6. Satellite scenes

Earth Search STAC is searched with the event point, a window from 45 days before first detection to now, and cloud ≤ 60 %. Scenes are then:

- de-duplicated across reprocessing runs (e.g. `…_0_L2A` / `…_1_L2A`),
- labelled `before`, `during`, `after` or `latest`, and
- stored with platform, processing level, cloud % and item URL.

The public previews cover the full ~110 km tile. The UI states that they are context for analysts, not automated confirmation.

With CDSE credentials, a 5 km AOI **SWIR composite (B12/B8A/B4)** can be rendered around the event. SWIR highlights high-temperature pixels.

## 7. Performance notes

- **Map loading**: the map requests only the current viewport (`bbox` plus filters), at most 3,000 features, with a 250 ms debounce. Clustering happens client-side with MapLibre. Facilities load only at zoom ≥ 6.
- **Indexes**:
  - GiST on `thermal_detections.geom`, `thermal_events.geom` and `facilities.geom`.
  - B-tree on acquisition time, dataset, sensor, confidence, classification, persistence and status.
  - A partial index on unassigned detections.
- **Query plan**: `EXPLAIN ANALYZE` of the viewport query (`e.geom && ST_MakeEnvelope(...)::geography`) with the 1,351 events uses the GiST index. See `docs/TESTING.md` for the recorded plan.
