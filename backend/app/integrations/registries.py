"""Facility registry adapters: Global Energy Monitor, CEA, WRI Global Power Plant Database.

None of these publish a real-time API. They are *controlled dataset ingestion*: a specific,
versioned release file is imported and its version/publication date is stored and shown in
the UI. Nothing here pretends to be live.

- GlobalEnergyMonitorClient — GEM tracker releases (xlsx/csv) downloaded from
  globalenergymonitor.org after accepting GEM's terms (cannot be automated). Supported
  trackers are auto-detected by header: coal plant, oil & gas plant, steel plant, cement,
  coal mine, oil & gas extraction.
- CEAClient — CEA publishes plant lists as reports, not geocoded tables. This adapter imports
  an analyst-prepared CSV derived from a named CEA publication (template in
  data/datasets/README.md) and requires the publication id/date.
- WRIGPPDClient — the WRI GPPD CSV (CC BY 4.0). India rows are CEA-derived per WRI's `source`
  column; that lineage is preserved.
"""
import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.integrations.http import request

logger = logging.getLogger(__name__)

WRI_GPPD_URL = (
    "https://raw.githubusercontent.com/wri/global-power-plant-database/master/output_database/"
    "global_power_plant_database.csv"
)


@dataclass
class RegistryFacility:
    source_id: str
    external_id: str
    name: str | None
    facility_type: str
    source_type: str | None
    latitude: float
    longitude: float
    operator: str | None = None
    status: str | None = None
    capacity_value: float | None = None
    capacity_unit: str | None = None
    country: str | None = None
    state: str | None = None
    district: str | None = None
    source_url: str | None = None
    subtype: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class RegistryImport:
    source_id: str
    dataset_version: str
    published_at: date | None
    origin: str
    facilities: list[RegistryFacility]
    rejected: list[tuple[dict, str]]


def _num(v) -> float | None:
    if v in (None, "", "nan", "NaN", "unknown"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _rows_from_file(path: Path) -> list[dict]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        best: list[dict] = []
        for ws in wb.worksheets:  # trackers keep the data on the widest sheet
            it = ws.iter_rows(values_only=True)
            header = next(it, None)
            if not header:
                continue
            cols = [str(h).strip() if h is not None else "" for h in header]
            rows = [dict(zip(cols, r, strict=False)) for r in it]
            if len(cols) > 5 and len(rows) > len(best):
                best = rows
        return best
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _fuel_to_type(fuel: str | None) -> str:
    f = (fuel or "").lower()
    if f in ("coal", "petcoke", "lignite"):
        return "power_plant_coal"
    if f in ("gas", "oil", "diesel", "lng"):
        return "power_plant_gas"
    return "power_plant_other"


# ---------------------------------------------------------------------------------------------
class WRIGPPDClient:
    source_id = "wri_gppd"

    def fetch(self, country_iso3: str = "IND", url: str = WRI_GPPD_URL) -> RegistryImport:
        res = request("wri_gppd", "GET", url, timeout=120, max_attempts=3)
        return self.parse(res.response.text, country_iso3, origin=url)

    def parse(self, text: str, country_iso3: str, origin: str) -> RegistryImport:
        facilities, rejected = [], []
        for row in csv.DictReader(io.StringIO(text)):
            if country_iso3 and row.get("country") != country_iso3:
                continue
            lat, lon = _num(row.get("latitude")), _num(row.get("longitude"))
            if lat is None or lon is None:
                rejected.append((row, "missing coordinates"))
                continue
            fuel = row.get("primary_fuel")
            facilities.append(
                RegistryFacility(
                    source_id=self.source_id,
                    external_id=row["gppd_idnr"],
                    name=row.get("name"),
                    facility_type=_fuel_to_type(fuel),
                    subtype=(fuel or "").strip().lower() or None,
                    source_type=f"power plant ({fuel})",
                    latitude=lat,
                    longitude=lon,
                    operator=row.get("owner") or None,
                    status="operating (as of dataset)",
                    capacity_value=_num(row.get("capacity_mw")),
                    capacity_unit="MW",
                    country=row.get("country_long"),
                    source_url=row.get("url") or None,
                    raw={"primary_fuel": fuel, "commissioning_year": row.get("commissioning_year"),
                         "upstream_source": row.get("source"), "geolocation_source": row.get("geolocation_source")},
                )
            )
        # the default source is the archived WRI repository, whose final release is v1.3.0 (2021-06-02); any other file
        # is labelled as operator-supplied rather than given a version it may not have
        official = origin == WRI_GPPD_URL
        return RegistryImport(self.source_id, "GPPD v1.3.0" if official else "GPPD (operator-supplied file)",
                              date(2021, 6, 2) if official else None, origin, facilities, rejected)


# ---------------------------------------------------------------------------------------------
_GEM_PROFILES = [
    # (tracker label, required header, facility_type resolver, name col candidates, capacity col, unit)
    ("Global Coal Plant Tracker", "Combustion technology", lambda r: "power_plant_coal", ("Plant name", "Plant"), "Capacity (MW)", "MW"),
    ("Global Oil and Gas Plant Tracker", "Fuel", lambda r: "power_plant_gas", ("Plant name", "Plant"), "Capacity (MW)", "MW"),
    ("Global Steel Plant Tracker", "Main production equipment", lambda r: "steel_plant", ("Plant name (English)", "Plant name"), "Nominal crude steel capacity (ttpa)", "ttpa"),
    ("Global Cement Tracker", "Cement Capacity (millions metric tonnes per annum)", lambda r: "cement_plant", ("Plant name (English)", "Plant name"), "Cement Capacity (millions metric tonnes per annum)", "Mtpa"),
    ("Global Coal Mine Tracker", "Mine Name", lambda r: "coal_mine", ("Mine Name",), "Capacity (Mtpa)", "Mtpa"),
    ("Global Oil and Gas Extraction Tracker", "Unit type", lambda r: "oil_gas", ("Unit name", "Unit Name"), None, None),
]


def _first(row: dict, *cols: str):
    for c in cols:
        if c in row and row[c] not in (None, ""):
            return row[c]
    return None


def _coords(row: dict) -> tuple[float | None, float | None]:
    lat, lon = _num(_first(row, "Latitude", "latitude", "Lat")), _num(_first(row, "Longitude", "longitude", "Lon"))
    if lat is None and row.get("Coordinates"):  # steel tracker packs "lat, lon"
        m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", str(row["Coordinates"]))
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
    return lat, lon


# Plant status from its units: the most "physically present" unit status wins.
GEM_STATUS_PRECEDENCE = ("operating", "construction", "mothballed", "retired", "permitted", "pre-permit", "announced",
                         "shelved", "cancelled")
# Units in these states exist (or existed) on the ground; the others were never built.
GEM_BUILT = {"operating", "construction", "mothballed", "retired"}


def plant_status(unit_statuses: list[str]) -> str | None:
    s = {str(u).strip().lower() for u in unit_statuses if u}
    return next((p for p in GEM_STATUS_PRECEDENCE if p in s), sorted(s)[0] if s else None)


class GlobalEnergyMonitorClient:
    source_id = "gem"

    def import_file(self, path: Path, dataset_version: str, published_at: date | None, country: str = "India") -> RegistryImport:
        rows = _rows_from_file(path)
        if not rows:
            raise ValueError(f"{path.name}: no tabular rows found")
        headers = set(rows[0].keys())
        profile = next((p for p in _GEM_PROFILES if p[1] in headers), None)
        if profile is None:
            raise ValueError(f"{path.name}: unrecognised GEM tracker layout (headers: {sorted(headers)[:12]}...)")
        label, _, resolve_type, name_cols, cap_col, unit = profile
        plants: dict[str, RegistryFacility] = {}
        units: dict[str, list[tuple[str | None, float | None, str | None]]] = {}
        rejected: list[tuple[dict, str]] = []
        for row in rows:
            row_country = _first(row, "Country/Area", "Country", "Country/area")
            if country and row_country and str(row_country).strip().lower() != country.lower():
                continue
            lat, lon = _coords(row)
            if lat is None or lon is None:
                rejected.append((row, "missing coordinates"))
                continue
            name = _first(row, *name_cols)
            ext_id = str(_first(row, "GEM location ID", "GEM Plant ID", "Plant ID", "GEM Mine ID", "Unit ID", "GEM unit/phase ID") or f"{name}@{lat:.4f},{lon:.4f}")
            cap = _num(row.get(cap_col)) if cap_col else None
            # Trackers are unit-level: one facility per location id, status and capacity derived from all its units.
            units.setdefault(ext_id, []).append((_first(row, "Status", "Operating status"), cap, _first(row, "Location accuracy")))
            if ext_id in plants:
                continue
            plants[ext_id] = RegistryFacility(
                source_id=self.source_id,
                external_id=ext_id,
                name=str(name) if name else None,
                facility_type=resolve_type(row),
                source_type=label,
                latitude=lat,
                longitude=lon,
                operator=_first(row, "Owner", "Parent", "Owner name (English)", "Operator"),
                status=_first(row, "Status", "Operating status"),
                capacity_value=cap,
                capacity_unit=unit,
                country=str(row_country) if row_country else None,
                state=_first(row, "Subnational unit (province, state)", "State/Province", "Subnational unit"),
                source_url=_first(row, "Wiki URL", "GEM wiki page", "GEM Wiki Page (ENG)"),
                raw={k: (str(v) if v is not None else None) for k, v in list(row.items())[:40]},
            )
        for ext_id, plant in plants.items():
            us = units.get(ext_id, [])
            by_status: dict[str, float] = {}
            for st, cap, _ in us:
                k = str(st or "unknown").strip().lower()
                by_status[k] = round(by_status.get(k, 0.0) + (cap or 0.0), 3)
            status = plant_status([st for st, _, _ in us])
            plant.status = status
            if cap_col:
                built = sum(v for k, v in by_status.items() if k in GEM_BUILT)
                plant.capacity_value = (by_status.get("operating") or built or by_status.get(status or "", None)
                                        or sum(by_status.values()) or None)
            acc = {str(a).strip().lower() for _, _, a in us if a}
            plant.raw = {**plant.raw, "unit_count": len(us), "unit_status_mw": by_status, "plant_status": status,
                         "location_accuracy": "exact" if acc == {"exact"} else ("approximate" if acc else None)}
        return RegistryImport(self.source_id, f"{label} {dataset_version}", published_at, str(path.name), list(plants.values()), rejected)


# ---------------------------------------------------------------------------------------------
CEA_REQUIRED = ("name", "latitude", "longitude", "capacity_mw", "fuel")


class CEAClient:
    source_id = "cea"

    def import_file(self, path: Path, publication: str, published_at: date) -> RegistryImport:
        rows = _rows_from_file(path)
        missing = [c for c in CEA_REQUIRED if rows and c not in rows[0]]
        if not rows or missing:
            raise ValueError(f"{path.name}: CEA template requires columns {CEA_REQUIRED}; missing {missing}")
        facilities, rejected = [], []
        for i, row in enumerate(rows):
            lat, lon = _num(row.get("latitude")), _num(row.get("longitude"))
            if lat is None or lon is None:
                rejected.append((row, "missing coordinates"))
                continue
            facilities.append(
                RegistryFacility(
                    source_id=self.source_id,
                    external_id=str(row.get("cea_id") or f"{row['name']}#{i}"),
                    name=row["name"],
                    facility_type=_fuel_to_type(row.get("fuel")),
                    source_type=f"CEA listed station ({row.get('fuel')})",
                    latitude=lat,
                    longitude=lon,
                    operator=row.get("owner"),
                    status=row.get("status"),
                    capacity_value=_num(row.get("capacity_mw")),
                    capacity_unit="MW",
                    country="India",
                    state=row.get("state"),
                    district=row.get("district"),
                    raw=dict(row),
                )
            )
        return RegistryImport(self.source_id, publication, published_at, str(path.name), facilities, rejected)
