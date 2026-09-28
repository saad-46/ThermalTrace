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

Weather comes from Open-Meteo at the event's own coordinates, at the hour of its last detection. The wind direction is meteorological (the direction the wind comes *from*). Only values the provider returned are shown; a missing value is left out, never shown as zero. Weather is context for an event, never a cause.

The **potential dispersion direction** is (direction + 180°) mod 360. It is drawn as a vector whose length is scaled by wind speed.

**It is not plume tracking**, and the UI and reports say so.

## 6. Satellite scenes

Earth Search STAC is searched with the event point in two windows (cloud ≤ 60 %): the newest scenes in the 45 days before the first detection, and the oldest from the first detection until 60 days after the last. Scenes are then:

- de-duplicated across reprocessing runs (e.g. `…_0_L2A` / `…_1_L2A`),
- kept as up to 4 before, 4 during and 3 after,
- stored with platform, processing level, cloud % and item URL. Their relation to the event (before / during / after) is computed from the event's current times when read, so an event that keeps growing does not keep a stale label.

The public previews cover the full ~110 km tile. The UI states that they are context for analysts, not automated confirmation.

With CDSE credentials, a 5 km AOI **SWIR composite (B12/B8A/B4)** can be rendered around the event. SWIR highlights high-temperature pixels.

## 7. Basemap and India-wide coverage

The basemap is CARTO (dark-matter / positron) vector tiles, OpenMapTiles schema, built from global OpenStreetMap data.
The data covers all of India. What differed between areas was the **style**: dark-matter draws roads below zoom 10
in near-black (`#1a1a1a` on `#0e0e0e`), has road fills only from z10 and road names from z13, and has no district
layer (India's districts are `admin_level` 5; the style only draws 6). Zoomed into one city everything appeared; at
state or country zoom almost nothing did. `MapCanvas.enhanceBasemap` adds a zoom-dependent hierarchy from the same
tiles, without adding any feature:

| Zoom | Added |
|---|---|
| ≥ 4.5 | motorways and trunk roads; state names from 4.5 (was 5) |
| ≥ 6.5 | major city names (was 8) |
| ≥ 7 | primary roads |
| ≥ 8.5 | district boundaries (`admin_level` 5; in the tiles from about z9) |
| ≥ 9 | industrial areas and quarries (mines) |
| ≥ 9.5 | secondary and tertiary roads (style fills start at 13) |
| ≥ 10 / 12 | trunk / primary road names (were 13 / 14) |

Limitations: detail still depends on how well OSM maps an area; districts appear only where OSM has them; CARTO's
free tier needs `VITE_CARTO_API_KEY` for production traffic (a public browser key, not a secret).

Facilities are drawn as squares (thermal events are circles); facilities attributed to the selected event are ringed.
Clicking one opens a compact card built from the map layer's own data (no request), with the distance to and
attribution rank for the selected event, and *View facility details*. The facility page (`/facilities/:id`, also
in the mobile app) loads the rest lazily: relationship to the event (`GET /facilities/{id}/relationship?event=`),
overview with registry identifiers, provenance, a map with the 2 km and 10 km rings, a weekly activity timeline and
a paginated event history (`GET /facilities/{id}/events?limit=&offset=`). On phones the card is a bottom sheet.

## 8. Local facility index

See DATA_SOURCES.md. Facilities are synced by 1° tile. An event counts as covered when every tile within about 0.1° is fresh, because the attribution radius is 10 km. After a tile syncs, events inside it (plus a 0.1° margin) are re-attributed locally.

## 9. Performance notes

- **Map loading**: the map requests only the current viewport (`bbox` plus filters), at most 3,000 features, with a 250 ms debounce. Clustering happens client-side with MapLibre. Facilities load only at zoom ≥ 6.
- **Indexes**:
  - GiST on `thermal_detections.geom`, `thermal_events.geom` and `facilities.geom`.
  - B-tree on acquisition time, dataset, sensor, confidence, classification, persistence and status.
  - A partial index on unassigned detections.
- **Query plan**: `EXPLAIN ANALYZE` of the viewport query (`e.geom && ST_MakeEnvelope(...)::geography`) with the 1,351 events uses the GiST index. See `docs/TESTING.md` for the recorded plan.

## 10. Clusters, recurring activity and map layers (advanced phase)

- **Activity cluster**: events whose geography lies within `radius_km` (2 to 25) of an event and that were active within
  `days` of its span (`ST_DWithin` on the GiST index). Summary: count, detections, duration, farthest distance, peak and
  mean FRP, convex-hull extent, classification / persistence / land-cover distributions and facilities within 3 km.
  A cluster groups activity for review; it does not mean the events share a source.
- **Recurring activity**: counts of events within 2 km (location) or linked within 2 km (facility) this week, the
  previous week, the last and previous 30 days and the weekly average over the loaded history. Places without a facility
  are grouped in ~5.5 km cells. Observed activity, never a risk measure.
- **Map layers**: thermal events and activity density; selected-event pixels, rings and dispersion; facilities (squares),
  OSM industrial areas and quarries; state and district boundaries, roads, rivers and OSM land cover (OpenMapTiles
  classes); the EOX satellite basemap. The legend lists only active layers. The selected facility gets an outline,
  facilities linked to the selected event a blue ring. The ESA WorldCover WMS was not reachable from the development
  network, so the map's land-cover layer uses OSM data; per-event land cover remains ESA WorldCover.
- **Facility satellite view**: the facility page's map has a Map / Satellite toggle (default Map, unchanged). Satellite
  adds EOX Sentinel-2 cloudless annual mosaic tiles (2018 to 2025, Web Mercator, to zoom 17) centred on the facility's
  registered coordinates, above the vector basemap and below the overlays: the same 2 km / 10 km rings (white over
  imagery), the selected event and the events linked to the facility within 3 km (class colours, FRP sizing; click
  opens the event). A mosaic is a composite with no single acquisition date, so the card shows "{year} annual mosaic"
  and "Date unavailable" when imagery did not load. Tiles are requested only after the first switch to Satellite and
  are kept (hidden) when switching back; the map is rebuilt per facility, so no imagery carries over. States: loading,
  available, no imagery (every tile 404; MapLibre reports these silently, so this is a settled source with nothing
  loaded), failure with Retry (network, 401/403, 429, other HTTP errors, offline, 20 s timeout), not configured
  (`VITE_SATELLITE_IMAGERY=off`) and invalid coordinates. The imagery is context, separate from the NDVI / NBR
  before/after analysis, and never evidence that a fire occurred or that the facility caused an anomaly.
