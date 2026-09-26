# Facility registry release files (controlled dataset ingestion)

Put downloaded, versioned release files here. They are not committed (see `.gitignore`). Each import records its dataset version and publication date, and the UI shows both next to every facility.

| Source | How to obtain | Import command |
|---|---|---|
| **WRI Global Power Plant Database** (CC BY 4.0) | Fetched automatically from WRI's GitHub release (v1.3.0). | `python -m app.cli import-registry --source wri_gppd` |
| **Global Energy Monitor** trackers: coal plant, oil and gas plant, steel, cement, coal mine, oil and gas extraction | Download the tracker release (xlsx) from globalenergymonitor.org. Licence (from the tracker's About sheet): CC BY 4.0; cite e.g. "Global Energy Monitor, Global Coal Plant Tracker, July 2026 release." A person has to do this step. | `python -m app.cli import-registry --source gem --path <file>.xlsx --version "2026-H1" --published 2026-07-01` |
| **Central Electricity Authority (CEA)** | CEA publishes station lists in reports, not geocoded tables. The monthly *Installed Capacity* report and its `IC_allocation_*.xlsx` hold only region/state/sector capacity totals (no stations, no coordinates) and cannot be imported as facilities. Transcribe a named CEA publication into `cea_template.csv` and keep the source PDF alongside it. | `python -m app.cli import-registry --source cea --path cea_2026.csv --version "CEA Installed Capacity Report Aug-2026" --published 2026-08-31` |

**How imports are processed**

- The GEM importer detects which tracker it has from the column headers.
- GEM rows are per unit. The importer combines them into one facility per location.
- Each imported facility is merged with any nearby OSM facility of a compatible type.
- A facility's confidence rises when independent sources agree.
- Import files are only read from inside this directory (`DATASETS_DIR`).
