"""CEA power-station registry: PDF -> stations -> coordinate matching -> validation -> PostGIS.

The CEA list is authoritative for *which* stations exist (identity, sector, organisation, units, capacity). It has no
coordinates. A station gets a location only by matching it to a facility already located by another source (WRI Global
Power Plant Database or Global Energy Monitor), and that source is recorded as `coordinate_source`. Matching requires
the same state (facility state from the India admin boundaries), a compatible fuel, similar distinctive name tokens,
and uses capacity to break ties. Ties between different facilities are left ambiguous for review, never guessed.
"""
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.integrations.cea_pdf import CATEGORY, CEAUnit, ParsedCEA, parse_pdf, reconcile
from app.models.facilities import Facility, FacilitySource
from app.models.ops import DataSource
from app.models.reference import RegistryStation
from app.services.facilities import _recompute_confidence

# Words that describe plant type or phase, not the place/plant identity.
STOP = {
    "TPS", "STPS", "TPP", "STPP", "TS", "CCPP", "CCGT", "GT", "GTPP", "GPS", "GTPS", "CPP", "PP", "PH", "PHASE", "STAGE",
    "STG", "EXT", "EXTN", "EXPN", "EXP", "EXPANSION", "UNIT", "UNITS", "POWER", "THERMAL", "STATION", "STATIONS", "PLANT",
    "PROJECT", "PROJ", "SUPER", "LTD", "LIMITED", "PVT", "PRIVATE", "CO", "COMPANY", "HEP", "HPS", "HE", "HYDRO", "HYDEL",
    "ELECTRIC", "MW", "NEW", "OLD", "THE", "OF", "DG", "APS", "NPP", "COMPLEX", "GENERATING", "GENERATION", "ENERGY",
    "CAPTIVE", "WORKS", "GAS", "BASED", "COMBINED", "CYCLE", "AND", "REPLACEMENT", "HPP", "SHP", "PSS", "PSP", "PUMPED",
    "STORAGE", "ATOMIC", "NUCLEAR", "DIESEL", "LIGNITE", "COAL", "TPS-II", "INDIA", "CORPORATION", "CORP",
}
ROMAN = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}
# CEA prime mover -> source fuels that are compatible with it.
FUEL_OK = {
    "Steam": {"coal", "lignite", "petcoke", "oil", "biomass", None},
    "GT-Gas": {"gas", "oil", "lng", "naphtha"}, "GT-Liquid": {"oil", "gas"}, "GT-Naphtha": {"oil", "gas"},
    "Diesel": {"oil", "diesel"}, "Hydro": {"hydro"}, "Nuclear": {"nuclear"},
}
SOURCE_LABEL = {"wri_gppd": "WRI Global Power Plant Database", "gem": "Global Energy Monitor (Global Coal Plant Tracker)",
                "osm": "OpenStreetMap"}
MATCH_MIN = 0.70        # combined score to accept
NAME_MIN = 0.60         # name similarity to be considered at all
TIE_MARGIN = 0.08       # a different facility this close to the best -> ambiguous
SAME_PLACE_KM = 2.0     # equally good candidates closer than this are the same location (duplicate facility rows)


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def norm_state(s: str | None) -> str:
    s = _ascii(s or "").upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return {"ORISSA": "ODISHA", "PONDICHERRY": "PUDUCHERRY", "UTTARANCHAL": "UTTARAKHAND",
            "JAMMU AND KASHMIR UT": "JAMMU AND KASHMIR"}.get(s, s)


def tokens(name: str) -> tuple[set[str], set[str]]:
    """(distinctive tokens, qualifier tokens such as roman numerals, letters and phase numbers)."""
    s = _ascii(name).upper().replace("&", " AND ")
    s = re.sub(r"\(.*?\)", lambda m: " " + m.group(0)[1:-1] + " ", s)
    words = re.findall(r"[A-Z0-9]+", s)
    core, qual = set(), set()
    for w in words:
        if w in ROMAN or len(w) == 1 or w.isdigit():
            qual.add(w)
        elif w not in STOP:
            core.add(w)
    return core, qual


def name_similarity(a: set[str], b: set[str]) -> float:
    """Share of each side's distinctive tokens found (fuzzily) in the other, weighted towards the station side."""
    if not a or not b:
        return 0.0

    def covered(x: set[str], y: set[str]) -> float:
        hit = 0
        for t in x:
            best = max((SequenceMatcher(None, t, u).ratio() for u in y), default=0.0)
            hit += 1 if best >= 0.84 else 0
        return hit / len(x)

    return 0.7 * covered(a, b) + 0.3 * covered(b, a)


@dataclass
class Station:
    key: str
    name: str
    category: str
    region: str
    state: str
    sector: str
    organisation: str
    units: list[CEAUnit] = field(default_factory=list)

    @property
    def capacity(self) -> float:
        return round(sum(u.capacity_mw for u in self.units), 3)

    @property
    def movers(self) -> list[str]:
        return sorted({u.prime_mover for u in self.units})

    @property
    def flags(self) -> list[str]:
        out = sorted({r for u in self.units for r in u.repairs})
        c = Counter(u.unit for u in self.units)
        if any(n > 1 for n in c.values()):
            out.append("duplicate_unit_number")
        return out


def stations_from(parsed: ParsedCEA) -> list[Station]:
    by: dict[tuple, Station] = {}
    for u in parsed.units:
        k = (u.appendix, u.state, u.organisation, u.project)
        if k not in by:
            key = re.sub(r"[^A-Z0-9]+", "-", _ascii(f"{u.appendix}|{u.state}|{u.organisation}|{u.project}").upper()).strip("-")[:200]
            by[k] = Station(key=key, name=u.project, category=CATEGORY.get(u.appendix, u.appendix), region=u.region,
                            state=u.state, sector=u.sector, organisation=u.organisation)
        by[k].units.append(u)
    return list(by.values())


_CANDIDATES = text("""
    SELECT s.source_id, s.external_id, s.name AS source_name, f.id AS facility_id, f.name AS facility_name,
           f.capacity_value, f.status, f.latitude, f.longitude, f.subtype, f.source_count, f.confidence, f.primary_source,
           lower(coalesce(s.raw->>'primary_fuel', CASE WHEN s.source_id = 'gem' THEN 'coal' END)) AS fuel,
           s.raw->>'location_accuracy' AS location_accuracy, a.name AS state
    FROM facility_sources s
    JOIN facilities f ON f.id = s.facility_id
    LEFT JOIN admin_areas a ON a.country = 'IND' AND ST_Contains(a.geom, f.geom::geometry)
    WHERE s.source_id IN ('wri_gppd', 'gem')
      AND coalesce(lower(f.status), '') NOT IN ('cancelled', 'shelved', 'announced', 'pre-permit', 'permitted')
""")


def load_candidates(db: Session) -> dict[str, list[dict]]:
    by_state: dict[str, list[dict]] = defaultdict(list)
    for r in db.execute(_CANDIDATES).mappings():
        c = dict(r)
        c["core"], c["qual"] = tokens(c["source_name"] or c["facility_name"] or "")
        by_state[norm_state(c["state"])].append(c)
    return by_state


def match_station(st: Station, by_state: dict[str, list[dict]]) -> dict:
    core, qual = tokens(st.name)
    if not core:  # e.g. a name made only of generic words: try the organisation too
        core = tokens(st.organisation)[0]
    scored = []
    for c in by_state.get(norm_state(st.state), []):
        if not any(c["fuel"] in FUEL_OK.get(m, set()) for m in st.movers):
            continue
        sim = name_similarity(core, c["core"])
        if sim < NAME_MIN:
            continue
        cap = c["capacity_value"]
        cap_score = (min(cap, st.capacity) / max(cap, st.capacity)) if cap and st.capacity else 0.5
        qual_bonus = 0.05 if qual and qual & c["qual"] else 0.0
        scored.append({**c, "name_similarity": round(sim, 3), "capacity_ratio": round(cap_score, 3),
                       "score": round(0.75 * sim + 0.25 * cap_score + qual_bonus, 3)})
    scored.sort(key=lambda c: (-c["score"], c["source_id"], str(c["facility_id"])))  # deterministic
    # several sources can back one facility: keep the best row per facility
    best_per_fac: dict = {}
    for c in scored:
        best_per_fac.setdefault(c["facility_id"], c)
    ranked = sorted(best_per_fac.values(), key=lambda c: -c["score"])
    summary = [{"facility_id": str(c["facility_id"]), "source": c["source_id"], "name": c["source_name"], "score": c["score"],
                "name_similarity": c["name_similarity"], "capacity_ratio": c["capacity_ratio"], "capacity_mw": c["capacity_value"]}
               for c in ranked[:4]]
    if not ranked or ranked[0]["score"] < MATCH_MIN:
        return {"status": "unmatched", "candidates": summary}
    best = ranked[0]
    rivals = [c for c in ranked[1:] if c["score"] >= best["score"] - TIE_MARGIN]
    if rivals and all(_km(best["latitude"], best["longitude"], c["latitude"], c["longitude"]) <= SAME_PLACE_KM for c in rivals):
        # The equally good candidates are duplicate facility rows at the same place: the location is agreed, only the
        # row differs. Link the best-supported row; flagged, medium confidence.
        chosen = max([best, *rivals], key=lambda c: (c["source_count"] or 0, c["confidence"] or 0, c["score"]))
        return {"status": "matched", "facility_id": chosen["facility_id"], "source": chosen.get("primary_source") or chosen["source_id"], "score": best["score"],
                "confidence": "medium", "candidates": summary, "reason": "duplicate facility rows at the same location",
                "flag": "duplicate_facility_rows"}
    if len(ranked) > 1 and ranked[1]["score"] >= best["score"] - TIE_MARGIN:
        # One plant located differently by two sources, or several distinct plants: report the gap for review.
        gap = _km(best["latitude"], best["longitude"], ranked[1]["latitude"], ranked[1]["longitude"])
        return {"status": "ambiguous", "candidates": summary, "score": best["score"], "candidates_km_apart": round(gap, 1),
                "reason": "same plant name at two locations" if gap <= 25 and ranked[1]["source_id"] != best["source_id"]
                          else "several facilities fit equally well"}
    confidence = "high" if best["name_similarity"] >= 0.99 and best["capacity_ratio"] >= 0.75 else "medium"
    if best.get("location_accuracy") == "approximate":
        confidence = "medium"
    # The location is the facility's: credit the source that created its geometry, not whichever record matched.
    return {"status": "matched", "facility_id": best["facility_id"], "source": best.get("primary_source") or best["source_id"], "score": best["score"],
            "confidence": confidence, "candidates": summary}


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def build(parsed: ParsedCEA, db: Session) -> tuple[list[Station], dict[str, dict], dict]:
    """Stations, their match results, and the validation report (nothing written)."""
    stations = stations_from(parsed)
    by_state = load_candidates(db)
    matches = {s.key: match_station(s, by_state) for s in stations}
    rec = reconcile(parsed)
    shared = Counter(m["facility_id"] for m in matches.values() if m["status"] == "matched")
    name_dupes = [n for n, k in Counter((s.state, s.name) for s in stations).items() if k > 1]
    status = Counter(m["status"] for m in matches.values())
    by_cat = defaultdict(Counter)
    for s in stations:
        by_cat[s.category][matches[s.key]["status"]] += 1
    report = {
        "units": len(parsed.units), "stations": len(stations),
        "stations_by_category": dict(Counter(s.category for s in stations)),
        "capacity_mw": round(sum(u.capacity_mw for u in parsed.units), 2),
        "printed_category_totals_mw": parsed.category_totals,
        "state_totals_checked": len(rec), "state_total_mismatches": [r for r in rec if not r["ok"]],
        "unparsed_lines": parsed.unparsed,
        "repairs": dict(Counter(r for u in parsed.units for r in u.repairs)),
        "coordinates_in_source": False,
        "match_status": dict(status),
        "match_status_by_category": {k: dict(v) for k, v in by_cat.items()},
        "matched_by_coordinate_source": dict(Counter(m["source"] for m in matches.values() if m["status"] == "matched")),
        "matched_confidence": dict(Counter(m["confidence"] for m in matches.values() if m["status"] == "matched")),
        "stations_sharing_a_location": sum(n for n in shared.values() if n > 1),
        "ambiguous_reasons": dict(Counter(m.get("reason") for m in matches.values() if m["status"] == "ambiguous")),
        "matched_on_duplicate_facility_rows": sum(1 for m in matches.values() if m.get("flag") == "duplicate_facility_rows"),
        "duplicate_station_names_in_state": [list(k) for k in name_dupes],
        "duplicate_unit_numbers": [s.name for s in stations if "duplicate_unit_number" in s.flags],
        "missing_names": sum(1 for s in stations if not s.name.strip()),
        "missing_years": sum(1 for u in parsed.units if u.year is None),
        "invalid_capacity": sum(1 for u in parsed.units if not (0 < u.capacity_mw < 5000)),
    }
    return stations, matches, report


def write_outputs(stations: list[Station], matches: dict, report: dict, out_dir: Path, source_file: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    fac_coords = report.get("_facility_coords", {})
    rows = []
    for s in stations:
        m = matches[s.key]
        lat, lon = fac_coords.get(str(m.get("facility_id")), (None, None)) if m["status"] == "matched" else (None, None)
        rows.append({
            "facility_id": s.key, "facility_name": s.name, "facility_type": _facility_type(s),
            "category": s.category, "region": s.region, "state": s.state, "district": "",
            "owner": s.organisation, "sector": s.sector, "capacity_mw": s.capacity, "fuel_type": "/".join(s.movers),
            "unit_count": len(s.units), "status": "listed (installed)",
            "first_year": min((u.year for u in s.units if u.year), default=""),
            "latitude": lat if lat is not None else "", "longitude": lon if lon is not None else "",
            "registry_source": "CEA", "metadata_source": "CEA",
            "coordinate_source": SOURCE_LABEL.get(m.get("source"), "") if m["status"] == "matched" else "",
            "coordinate_confidence": m.get("confidence", "") if m["status"] == "matched" else "",
            "match_status": m["status"], "match_score": m.get("score", ""),
            "source": "Central Electricity Authority", "source_file": source_file, "source_date": "2025-03-31",
            "flags": ";".join(s.flags),
        })
    csv_path = out_dir / "cea_stations_normalized.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    review = out_dir / "cea_match_review.csv"
    with review.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["station", "state", "category", "capacity_mw", "match_status", "reason", "candidates_km_apart", "candidate",
                    "candidate_source", "score", "name_similarity", "capacity_ratio"])
        for s in stations:
            m = matches[s.key]
            if m["status"] == "matched" and m.get("confidence") == "high":
                continue
            for c in m["candidates"] or [{}]:
                w.writerow([s.name, s.state, s.category, s.capacity, m["status"], m.get("reason", ""), m.get("candidates_km_apart", ""),
                            c.get("name", ""), c.get("source", ""),
                            c.get("score", ""), c.get("name_similarity", ""), c.get("capacity_ratio", "")])
    rep = {k: v for k, v in report.items() if not k.startswith("_")}
    json_path = out_dir / "cea_validation_report.json"
    json_path.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    return [csv_path, review, json_path]


def _facility_type(s: Station) -> str:
    if s.category == "thermal":
        return "power_plant_gas" if set(s.movers) <= {"GT-Gas", "GT-Liquid", "GT-Naphtha"} else (
            "power_plant_coal" if "Steam" in s.movers else "power_plant_other")
    return "power_plant_other"


def import_registry(db: Session, pdf_path: Path, dataset_version: str, published_at: date, out_dir: Path) -> dict:
    parsed = parse_pdf(pdf_path)
    stations, matches, report = build(parsed, db)
    if report["state_total_mismatches"] or report["unparsed_lines"]:
        raise ValueError(f"CEA extraction did not reconcile with the printed totals: {report['state_total_mismatches'][:3]} "
                         f"{report['unparsed_lines'][:3]}")
    now = datetime.now(UTC)
    # Full refresh of this registry: previous CEA links and rows are replaced by this publication.
    touched = set(db.execute(select(FacilitySource.facility_id).where(FacilitySource.source_id == "cea")).scalars())
    db.execute(delete(FacilitySource).where(FacilitySource.source_id == "cea"))
    db.execute(delete(RegistryStation).where(RegistryStation.source_id == "cea"))
    coords = {}
    for s in stations:
        m = matches[s.key]
        fac = db.get(Facility, m["facility_id"]) if m["status"] == "matched" else None
        if fac is not None:
            coords[str(fac.id)] = (fac.latitude, fac.longitude)
            reg = {"source": "CEA", "station": s.name, "organisation": s.organisation, "sector": s.sector,
                   "capacity_mw": s.capacity, "units": len(s.units), "prime_movers": s.movers,
                   "coordinate_source": m["source"], "coordinate_confidence": m["confidence"],
                   "publication": dataset_version}
            attrs = dict(fac.attributes or {})
            attrs.setdefault("registries", [])
            attrs["registries"] = [r for r in attrs["registries"] if r.get("station") != s.name or r.get("source") != "CEA"] + [reg]
            fac.attributes = attrs
            fac.operator = fac.operator or s.organisation
            if s.category in ("hydro", "nuclear") and fac.facility_type == "power_plant_other":
                fac.subtype = fac.subtype or s.category
            if (fac.status or "").lower() in ("cancelled", "shelved", "announced", "pre-permit", "permitted", ""):
                fac.status = "operating"  # CEA lists its units as installed capacity
                attrs["status_source"] = "CEA installed capacity list"
                fac.attributes = attrs
            db.add(FacilitySource(
                facility_id=fac.id, source_id="cea", external_id=s.key, name=s.name,
                source_type=f"CEA listed station ({'/'.join(s.movers)})", source_url=None, dataset_version=dataset_version,
                published_at=published_at, retrieved_at=now,
                raw={"region": s.region, "state": s.state, "sector": s.sector, "organisation": s.organisation,
                     "capacity_mw": s.capacity, "units": [{"unit": u.unit, "capacity_mw": u.capacity_mw, "year": u.year,
                                                          "prime_mover": u.prime_mover} for u in s.units],
                     "coordinate_source": m["source"], "coordinate_confidence": m["confidence"],
                     "match_score": m["score"], "note": "Location from the coordinate source; CEA publishes no coordinates."}))
            touched.add(fac.id)
        db.add(RegistryStation(
            source_id="cea", station_key=s.key, name=s.name, category=s.category, region=s.region, state=s.state,
            sector=s.sector, organisation=s.organisation, prime_movers=s.movers, unit_count=len(s.units),
            capacity_mw=s.capacity, first_year=min((u.year for u in s.units if u.year), default=None),
            last_year=max((u.year for u in s.units if u.year), default=None),
            units=[{"unit": u.unit, "capacity_mw": u.capacity_mw, "year": u.year, "prime_mover": u.prime_mover, "page": u.page}
                   for u in s.units],
            source_file=pdf_path.name, source_date=published_at, facility_id=fac.id if fac else None,
            match_status=m["status"], match_score=m.get("score"),
            coordinate_source=m.get("source") if fac else None, coordinate_confidence=m.get("confidence") if fac else None,
            match_detail={"candidates": m["candidates"], "reason": m.get("reason"), "candidates_km_apart": m.get("candidates_km_apart")},
            flags=s.flags + ([m["flag"]] if m.get("flag") else []), imported_at=now))
    db.flush()
    for fid in touched:
        f = db.get(Facility, fid)
        if f is not None:
            _recompute_confidence(db, f)
    src = db.get(DataSource, "cea")
    if src is not None:
        src.dataset_version = dataset_version
        src.dataset_published_at = datetime.combine(published_at, datetime.min.time(), tzinfo=UTC)
    report["_facility_coords"] = coords
    files = write_outputs(stations, matches, report, out_dir, pdf_path.name)
    report.pop("_facility_coords", None)
    report["facilities_linked"] = len({m["facility_id"] for m in matches.values() if m["status"] == "matched"})
    report["outputs"] = [p.name for p in files]
    return report
