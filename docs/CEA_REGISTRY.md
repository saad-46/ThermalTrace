# CEA power-station registry and the India facility reference layer

## What the CEA list is (and is not)

`List_of_Power_Station_as_on_31.03.2025.pdf` (Central Electricity Authority) lists **generating units**: region, state,
sector, organisation, name of project, prime mover, unit number, installed capacity (MW) and year of commissioning.
Appendix A is thermal, B hydro, C nuclear. **It contains no coordinates and no districts.** ThermalTrace therefore uses
it for *identity* (which stations exist, who owns them, their units and capacity) and never presents it as a source of
locations.

## Pipeline (`backend/app/integrations/cea_pdf.py`, `backend/app/services/cea_registry.py`)

```
CEA PDF ──► unit rows (layout text) ──► reconciliation with the printed totals ──► stations
         ──► name/state/fuel normalisation ──► matching to located facilities (WRI GPPD, GEM, OSM)
         ──► validation ──► registry_stations + facility_sources (PostGIS) ──► map, attribution, UI
```

- **Extraction**: pypdf layout mode. Deterministic repairs, each recorded on the unit: prime mover glued to the project
  name (42), organisation and project merged (7, e.g. "TOR. POW. (UNOSUGEN)SABARMATI"), organisation printed twice (4,
  OPG). Nothing is dropped silently: unparsed lines are returned and fail the import.
- **Reconciliation**: the 58 printed state totals and the 3 appendix totals are compared with the parsed units. The
  import refuses to run if any differs.
- **Matching** (per station): same state (a facility's state is taken from the India state boundaries), a compatible
  fuel (Steam: coal/lignite/oil; GT: gas/oil; hydro; nuclear), similar distinctive name tokens (generic words such as
  TPS, STPS, CCPP, "Thermal Power Station" ignored; spelling variants tolerated) and capacity as a tie-breaker.
  - **matched**: one facility clearly fits; `coordinate_confidence` high (all name tokens and capacity within 25%) or
    medium.
  - **ambiguous**: different places fit equally well; nothing is linked, listed for review with the distance between
    the candidates.
  - Equally good candidates **within 2 km** are duplicate facility rows at one place: the location is agreed, the
    best-supported row is linked (medium, flagged `duplicate_facility_rows`).
  - **unmatched**: no located facility fits; the station is kept in `registry_stations` without coordinates.
- **Provenance**: `registry_source` = CEA; `coordinate_source` = the source that created the linked facility's
  geometry (WRI GPPD, GEM or OpenStreetMap), never CEA. A CEA record is attached to the facility as a
  `facility_sources` row whose raw data carries the units, the match score and "CEA publishes no coordinates".
  A matched facility without a status is marked operating (status source: CEA installed capacity list).

## Results (import of 27 Sep 2026)

| | Stations | Units / MW |
|---|---|---|
| Extracted | 503 (279 thermal, 216 hydro, 8 nuclear) | 1,633 units, 302,843.62 MW = printed totals (246,935.46 + 47,728.16 + 8,180) |
| Matched (located) | **403** (224 thermal, 175 hydro, 4 nuclear) | coordinates from WRI GPPD 379, GEM 12, OpenStreetMap 12; confidence high 281, medium 122 |
| of which on duplicate facility rows at one place | 14 | |
| Ambiguous (for review) | 8 (7 "several facilities fit equally well", 1 "same plant name at two locations") | |
| Unmatched (kept, not on the map) | 92 (48 thermal, 40 hydro, 4 nuclear) | |
| Facilities linked | 364 (several CEA stations can describe one plant complex: 69 stations share a location) | |

Validation: 0 state-total mismatches, 0 unparsed lines, 0 missing names, 0 missing years, 0 invalid capacities; one
station with a repeated unit number as printed (KOYNA-I&II HPS); no duplicate station names within a state.

Files: `data/datasets/processed/cea_stations_normalized.csv`, `cea_match_review.csv`, `cea_validation_report.json`.

## GEM (Global Coal Plant Tracker, July 2026)

India: 1,996 units at 662 locations, all with coordinates (location accuracy exact for 1,438 units, approximate for 558).
Unit statuses: operating 862, cancelled 758, retired 168, announced 62, construction 57, permitted 41, pre-permit 39,
mothballed 9. The importer now derives each plant's status from all its units (operating > construction > mothballed >
retired > permitted > pre-permit > announced > shelved > cancelled) and counts only built units in its capacity.
Result: 287 operating, 10 construction, 4 mothballed, 12 retired, 6 permitted, 3 pre-permit, 12 announced,
328 cancelled locations. Plants that were never built stay in the layer (with their status) but are **not** attribution
candidates; a never-built status never overwrites a facility that other sources show to exist.

## Other CEA files

`IC_Aug_2026.pdf` and `IC_allocation_as_on_31.08.2026.xlsx` contain installed-capacity totals by region, state,
sector and fuel (as on 31.08.2026). They have no station names, units or coordinates and so cannot enrich the
registry; they are kept as raw sources and not imported.
