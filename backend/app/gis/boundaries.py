"""India boundary: build the committed GeoJSON from Natural Earth, load it into PostGIS, classify points.

Source: Natural Earth 1:10m Admin 0 countries, India point of view (ne_10m_admin_0_countries_ind; public domain,
naturalearthdata.com), which depicts India's boundary as India officially claims it, including Lakshadweep and the
Andaman & Nicobar Islands. States/UTs: Natural Earth 1:10m Admin 1 (adm0_a3 = IND), clipped to the India outline.

`build_files` (developer step) simplifies the raw downloads with PostGIS and writes app/gis/data/*.geojson, which are
committed. `load` (migration 0010 / CLI) loads those files into `boundaries`, `boundary_parts` and `admin_areas`.
"""
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

DATA_DIR = Path(__file__).resolve().parent / "data"
INDIA_FILE = DATA_DIR / "india_ne10m_ind_pov.geojson"
STATES_FILE = DATA_DIR / "india_states_ne10m.geojson"
NEIGHBOURS_FILE = DATA_DIR / "india_neighbours_ne10m_ind_pov.geojson"
# Points within this distance of India's outline count as inside India unless they fall in a neighbouring country:
# FIRMS pixels are 375 m-1 km and the 1:10m outline is generalised by up to ~1.4 km on the smallest islands
# (e.g. Minicoy), so a strict test would drop real island and coastal anomalies. Land borders are unaffected because
# neighbouring countries are subtracted.
COASTAL_TOLERANCE_M = 1500
SOURCE = "Natural Earth 1:10m Admin 0 countries, India point of view (ne_10m_admin_0_countries_ind)"
STATES_SOURCE = "Natural Earth 1:10m Admin 1 states and provinces (adm0_a3 = IND), clipped to the India outline"
LICENSE = "Public domain (Natural Earth)"
COUNTRY_TOLERANCE = 0.002  # degrees (~200 m); keeps every Lakshadweep and Andaman & Nicobar island
STATES_TOLERANCE = 0.005


def build_files(db: Session, countries_path: Path, states_path: Path, version: str) -> dict:
    """Extract India from the raw Natural Earth files and write the simplified GeoJSON committed in the repo."""
    countries = json.loads(countries_path.read_text(encoding="utf-8"))
    ind = [f for f in countries["features"] if f["properties"].get("ADM0_A3") == "IND"]
    if len(ind) != 1:
        raise ValueError(f"expected one India feature in {countries_path.name}, found {len(ind)}")
    geom = db.execute(text("""
        SELECT ST_AsGeoJSON(ST_Multi(ST_SimplifyPreserveTopology(ST_MakeValid(ST_GeomFromGeoJSON(:g)), :tol)), 5)"""),
        {"g": json.dumps(ind[0]["geometry"]), "tol": COUNTRY_TOLERANCE}).scalar()
    india = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {
        "code": "IND", "name": "India", "source": SOURCE, "source_version": version, "license": LICENSE,
        "pov": "IND", "simplify_tolerance_deg": COUNTRY_TOLERANCE}, "geometry": json.loads(geom)}]}
    INDIA_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDIA_FILE.write_text(json.dumps(india, separators=(",", ":")), encoding="utf-8")

    states_raw = json.loads(states_path.read_text(encoding="utf-8"))
    feats = []
    for f in states_raw["features"]:
        p = f["properties"]
        if p.get("adm0_a3") != "IND":
            continue
        g = db.execute(text("""
            SELECT ST_AsGeoJSON(ST_Multi(ST_CollectionExtract(ST_SimplifyPreserveTopology(
                     ST_Intersection(ST_MakeValid(ST_GeomFromGeoJSON(:s)), ST_MakeValid(ST_GeomFromGeoJSON(:c))), :tol), 3)), 5)"""),
            {"s": json.dumps(f["geometry"]), "c": json.dumps(ind[0]["geometry"]), "tol": STATES_TOLERANCE}).scalar()
        if g and json.loads(g)["coordinates"]:
            feats.append({"type": "Feature", "properties": {"name": p.get("name"), "code": p.get("iso_3166_2"),
                                                            "type": p.get("type_en")}, "geometry": json.loads(g)})
    # Neighbouring countries (same India point-of-view file), clipped near India: they bound the coastal tolerance.
    neigh = []
    for f in countries["features"]:
        p = f["properties"]
        if p.get("ADM0_A3") == "IND":
            continue
        g = db.execute(text("""
            WITH c AS (SELECT ST_MakeValid(ST_GeomFromGeoJSON(:g)) g),
                 box AS (SELECT ST_Expand(ST_Envelope(ST_GeomFromGeoJSON(:ind)), 1.0) b)
            SELECT CASE WHEN ST_Intersects(c.g, box.b)
                        THEN ST_AsGeoJSON(ST_Multi(ST_CollectionExtract(ST_SimplifyPreserveTopology(ST_Intersection(c.g, box.b), :tol), 3)), 5)
                   END FROM c, box"""), {"g": json.dumps(f["geometry"]), "ind": json.dumps(ind[0]["geometry"]),
                                          "tol": COUNTRY_TOLERANCE}).scalar()
        if g and json.loads(g)["coordinates"]:
            neigh.append({"type": "Feature", "properties": {"code": p.get("ADM0_A3"), "name": p.get("NAME")},
                          "geometry": json.loads(g)})
    NEIGHBOURS_FILE.write_text(json.dumps({"type": "FeatureCollection", "properties": {
        "source": SOURCE, "source_version": version, "license": LICENSE, "note": "clipped to 1 degree around India"},
        "features": neigh}, separators=(",", ":")), encoding="utf-8")
    STATES_FILE.write_text(json.dumps({"type": "FeatureCollection", "properties": {
        "source": STATES_SOURCE, "source_version": version, "license": LICENSE}, "features": feats}, separators=(",", ":")),
        encoding="utf-8")
    return {"india_file": INDIA_FILE.name, "states": len(feats), "neighbours": [f["properties"]["code"] for f in neigh]}


def load(db: Session) -> dict:
    """Load the committed India boundary and states into PostGIS (idempotent)."""
    india = json.loads(INDIA_FILE.read_text(encoding="utf-8"))["features"][0]
    p = india["properties"]
    db.execute(text("DELETE FROM boundary_parts WHERE code = 'IND'"))
    db.execute(text("""
        INSERT INTO boundaries (code, name, source, source_version, license, pov, geom, loaded_at)
        VALUES ('IND', 'India', :source, :version, :license, :pov, ST_GeomFromGeoJSON(:g)::geography, now())
        ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, source = EXCLUDED.source,
          source_version = EXCLUDED.source_version, license = EXCLUDED.license, pov = EXCLUDED.pov,
          geom = EXCLUDED.geom, loaded_at = now()"""),
        {"source": p["source"], "version": p.get("source_version"), "license": p["license"], "pov": p.get("pov"),
         "g": json.dumps(india["geometry"])})
    # Classification geometry: India plus a seaward tolerance (never into a neighbouring country), subdivided so
    # point-in-polygon tests are index-assisted and cheap. The displayed outline (boundaries.geom) is unchanged.
    neighbours = json.loads(NEIGHBOURS_FILE.read_text(encoding="utf-8"))["features"] if NEIGHBOURS_FILE.exists() else []
    parts = db.execute(text("""
        WITH india AS (SELECT ST_GeomFromGeoJSON(:g) g),
             neigh AS (SELECT coalesce(ST_Union(ST_GeomFromGeoJSON(n)), ST_GeomFromText('POLYGON EMPTY', 4326)) g
                       FROM unnest(CAST(:n AS text[])) n),
             zone AS (SELECT ST_Union(india.g, ST_Difference(ST_Buffer(india.g::geography, :tol)::geometry, neigh.g)) g
                      FROM india, neigh)
        INSERT INTO boundary_parts (code, geom)
        SELECT 'IND', (ST_Dump(ST_Subdivide(ST_CollectionExtract(ST_MakeValid(zone.g), 3), 128))).geom FROM zone"""),
        {"g": json.dumps(india["geometry"]), "n": [json.dumps(f["geometry"]) for f in neighbours],
         "tol": COASTAL_TOLERANCE_M}).rowcount
    db.execute(text("DELETE FROM admin_areas WHERE country = 'IND'"))
    states = json.loads(STATES_FILE.read_text(encoding="utf-8"))["features"]
    for f in states:
        db.execute(text("""
            INSERT INTO admin_areas (country, code, name, level, kind, geom)
            VALUES ('IND', :code, :name, 1, :kind, ST_Multi(ST_GeomFromGeoJSON(:g)))"""),
            {"code": f["properties"].get("code"), "name": f["properties"]["name"], "kind": f["properties"].get("type"),
             "g": json.dumps(f["geometry"])})
    return {"boundary": "IND", "parts": parts, "states": len(states)}


# Point-in-India for events: true / false; NULL only when no boundary is loaded.
IN_INDIA_SQL = """
    CASE WHEN NOT EXISTS (SELECT 1 FROM boundary_parts WHERE code = 'IND') THEN NULL
         ELSE EXISTS (SELECT 1 FROM boundary_parts b WHERE b.code = 'IND' AND ST_Intersects(b.geom, {geom}::geometry)) END
"""


def classify_events(db: Session, batch: int = 20000, only_missing: bool = True, max_batches: int | None = None) -> dict:
    """Set thermal_events.in_india in batches (index-assisted point-in-polygon)."""
    done = 0
    for n in range(max_batches or 10**9):
        where = "in_india IS NULL" if only_missing else "TRUE"
        ids = db.execute(text(f"SELECT id FROM thermal_events WHERE {where} ORDER BY id LIMIT :n OFFSET :o"),
                         {"n": batch, "o": 0 if only_missing else n * batch}).scalars().all()
        if not ids:
            break
        db.execute(text(f"UPDATE thermal_events e SET in_india = {IN_INDIA_SQL.format(geom='e.geom')} WHERE e.id = ANY(:ids)"),
                   {"ids": ids})
        db.commit()
        done += len(ids)
        if not db.execute(text("SELECT EXISTS (SELECT 1 FROM boundary_parts WHERE code = 'IND')")).scalar():
            break  # nothing to classify against
    return {"classified": done}


def boundary_geojson(db: Session, tolerance: float) -> dict | None:
    """India outline (MultiPolygon), the mask covering everything else, and state boundary lines, simplified."""
    row = db.execute(text("""
        WITH b AS (SELECT geom::geometry g, source, source_version, license, pov FROM boundaries WHERE code = 'IND')
        SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(g, :t), 4) AS india,
               ST_AsGeoJSON(ST_Difference(ST_MakeEnvelope(-180, -85, 180, 85, 4326), ST_SimplifyPreserveTopology(g, :t)), 4) AS mask,
               ST_XMin(g) AS w, ST_YMin(g) AS s, ST_XMax(g) AS e, ST_YMax(g) AS n,
               ST_NumGeometries(g) AS parts, source, source_version, license, pov
        FROM b"""), {"t": tolerance}).mappings().first()
    if row is None:
        return None
    states = db.execute(text("""
        SELECT name, code, ST_AsGeoJSON(ST_Boundary(ST_SimplifyPreserveTopology(geom, :t)), 4) AS g
        FROM admin_areas WHERE country = 'IND' ORDER BY name"""), {"t": max(tolerance, STATES_TOLERANCE)}).mappings().all()
    return {
        "india": {"type": "Feature", "properties": {"name": "India"}, "geometry": json.loads(row["india"])},
        "mask": {"type": "Feature", "properties": {}, "geometry": json.loads(row["mask"])},
        "states": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": s["name"], "code": s["code"]}, "geometry": json.loads(s["g"])}
            for s in states]},
        "bbox": [row["w"], row["s"], row["e"], row["n"]],
        "parts": row["parts"],
        "source": row["source"], "source_version": row["source_version"], "license": row["license"], "pov": row["pov"],
        "states_source": STATES_SOURCE,
    }
