# Raw datasets (controlled dataset ingestion)

Downloaded, versioned source files live here; they are not committed (see `.gitignore`). Imports record each file's
dataset version and publication date, which the UI shows next to the data. Import files are only read from inside
this directory (`DATASETS_DIR`). Generated outputs go to `processed/`.

## Files and what is done with them

| File | Content (inspected) | Used for |
|---|---|---|
| `List_of_Power_Station_as_on_31.03.2025.pdf` | Official CEA list of thermal (Appendix A), hydro (B) and nuclear (C) stations, **one row per generating unit**: region, state, sector, organisation, project name, prime mover, unit, installed capacity (MW), year of commissioning, with state/region totals. **No coordinates, no districts.** | CEA registry: 1,633 units / 503 stations imported (`services/cea_registry.py`). Locations come only from matched facilities (WRI GPPD, GEM, OpenStreetMap), recorded as `coordinate_source`. |
| `Global-Coal-Plant-Tracker-July-2026.xlsx` | GEM Global Coal Plant Tracker, sheet *Units*: one row per unit with status, capacity, owner, coordinates and location accuracy; India: 1,996 units at 662 locations. | GEM facilities (one per location). Plant status is derived from all units (operating > construction > mothballed > retired > permitted > pre-permit > announced > shelved > cancelled); capacity counts built units; plants never built are kept but are not attribution candidates. |
| `IC_Aug_2026.pdf` | CEA monthly *All India Installed Capacity* summary (8 pages): capacity by fuel, region, state and sector. No stations or coordinates. | **Not imported.** It cannot identify or locate stations. Kept as the source of national totals. |
| `IC_allocation_as_on_31.08.2026.xlsx` | Sheets *Summary* and *IC*: capacity by region x sector x mode (coal, lignite, gas, diesel, nuclear, hydro, RES). No stations. | **Not imported**, for the same reason. Its date (31.08.2026) also differs from the station list (31.03.2025), so totals are not comparable one to one. |
| `ne_10m_admin_0_countries_ind.geojson`, `ne_10m_admin_1_states_provinces.geojson` | Natural Earth 1:10m countries (India point of view) and states (public domain). | Source of `backend/app/gis/data/*.geojson` (India outline incl. Lakshadweep and Andaman & Nicobar, states, neighbouring countries), built with `python -m app.cli build-boundaries`. |
| `cea_template.csv` | Template for a CEA-derived CSV with coordinates. | Optional alternative CEA import path. |

## Commands

```bash
# CEA station list (PDF): parse, reconcile with the printed totals, match locations, validate, import
python -m app.cli import-registry --source cea --path List_of_Power_Station_as_on_31.03.2025.pdf \
  --version "CEA List of Thermal, Hydro and Nuclear Power Stations as on 31.03.2025" --published 2025-03-31
# GEM tracker
python -m app.cli import-registry --source gem --path Global-Coal-Plant-Tracker-July-2026.xlsx --version "July 2026 release"
# WRI Global Power Plant Database (downloaded by the importer)
python -m app.cli import-registry --source wri_gppd
```

The CEA import writes `processed/cea_stations_normalized.csv` (every station with provenance and coordinate source),
`processed/cea_match_review.csv` (ambiguous, unmatched and medium-confidence matches with their candidates) and
`processed/cea_validation_report.json`. See `docs/CEA_REGISTRY.md`.
