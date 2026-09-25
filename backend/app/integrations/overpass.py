"""OpenStreetMap Overpass client.

Design (fixes audit D1/D2/D6):
- Always sends a User-Agent (overpass-api.de answers 406 without one — verified 2026-09-25).
- Queries a bounded radius around an event, never a whole country.
- Polite: per-provider minimum interval, endpoint rotation on failure, results cached by caller.
- Tag taxonomy is explicit and conservative: `man_made=works` is a *factory*, not a refinery.

OSM coverage is incomplete and uneven; absence of a mapped facility is reported as
"not mapped", never as "no facility exists".
"""
import logging
import re
from dataclasses import dataclass

from app.core.config import settings
from app.integrations.http import ProviderError, ProviderMalformed, request

logger = logging.getLogger(__name__)
PROVIDER = "osm"


_NAME_HINTS = [
    (re.compile(r"refiner", re.I), "refinery"),
    (re.compile(r"\b(steel|ispat|sail)\b", re.I), "steel_plant"),
    (re.compile(r"cement", re.I), "cement_plant"),
    # "Thermal" in Indian plant names also covers gas (e.g. NTPC Kawas), so only unambiguous coal names map to coal.
    (re.compile(r"(super thermal|\bstps\b|coal|lignite)", re.I), "power_plant_coal"),
    (re.compile(r"(chemical|fertili[sz]er|petrochem)", re.I), "chemical_plant"),
    (re.compile(r"(colliery|coal mine|opencast)", re.I), "coal_mine"),
    (re.compile(r"brick", re.I), "factory"),
]


@dataclass
class OsmFeature:
    osm_type: str
    osm_id: int
    latitude: float
    longitude: float
    tags: dict
    bounds: dict | None = None

    @property
    def name(self) -> str | None:
        return self.tags.get("name:en") or self.tags.get("name")


def classify_facility(tags: dict) -> str | None:
    """Map OSM tags to the facility taxonomy. Returns None for non-facility features."""
    power = tags.get("power")
    industrial = (tags.get("industrial") or "").lower()
    man_made = tags.get("man_made")
    landuse = tags.get("landuse")
    name = tags.get("name:en") or tags.get("name") or ""

    if power == "plant":
        source = (tags.get("plant:source") or tags.get("generator:source") or "").lower()
        if "coal" in source or "lignite" in source:
            return "power_plant_coal"
        if "gas" in source or "oil" in source or "diesel" in source:
            return "power_plant_gas"
        for pattern, ftype in _NAME_HINTS:
            if ftype == "power_plant_coal" and pattern.search(name):
                return ftype
        return "power_plant_other"
    if man_made == "flare":
        return "flare_site"
    if man_made == "offshore_platform":
        return "oil_gas"
    if industrial in ("refinery", "oil_refinery") or man_made == "petroleum_well" or industrial in ("oil", "gas", "oil_gas"):
        return "refinery" if "refin" in industrial or "refin" in name.lower() else "oil_gas"
    if industrial in ("steel", "steelmaker", "steelworks", "metallurgy", "iron"):
        return "steel_plant"
    if industrial in ("cement", "concrete_plant"):
        return "cement_plant"
    if industrial in ("chemical", "fertilizer", "petrochemical"):
        return "chemical_plant"
    if industrial in ("mine", "mining") or man_made == "mineshaft" or landuse == "quarry":
        resource = (tags.get("resource") or "").lower()
        return "coal_mine" if resource == "coal" or re.search(r"coal|colliery", name, re.I) else "mine"
    if landuse == "landfill":
        return "landfill"
    if man_made in ("works", "kiln") or industrial:
        for pattern, ftype in _NAME_HINTS:
            if pattern.search(name):
                return ftype
        return "factory"
    if landuse == "industrial":
        for pattern, ftype in _NAME_HINTS:
            if pattern.search(name):
                return ftype
        return "industrial_area"
    return None


def classify_land(tags: dict) -> str | None:
    landuse, natural = tags.get("landuse"), tags.get("natural")
    if landuse in ("farmland", "orchard", "meadow"):
        return "cropland"
    if landuse == "forest" or natural == "wood":
        return "forest"
    if natural == "scrub":
        return "scrub"
    if landuse == "residential":
        return "residential"
    return None


# Combined regex selectors keep the query to 6 clauses (a key-only `industrial=*` filter or one
# clause per event point made public servers answer 504/timeouts — observed 2026-09-25).
_FACILITY_FILTERS = [
    '["power"="plant"]',
    '["man_made"~"^(works|flare|petroleum_well|offshore_platform|mineshaft|kiln)$"]',
    '["industrial"~"^(refinery|oil_refinery|oil|gas|oil_gas|steel|steelmaker|steelworks|metallurgy|iron|cement|'
    'concrete_plant|chemical|fertilizer|petrochemical|mine|mining|brickyard|kiln|power)$"]',
    '["landuse"~"^(industrial|quarry|landfill)$"]',
]
_LAND_FILTERS = ['["landuse"~"^(farmland|orchard|meadow|forest|residential)$"]', '["natural"~"^(wood|scrub)$"]']


def _wrap(parts: list[str], timeout_s: int) -> str:
    body = "\n  ".join(parts)
    # `bb` and `center` are mutually exclusive geometry modes; centres are derived from bounds.
    return f"[out:json][timeout:{timeout_s}][maxsize:67108864];\n(\n  {body}\n);\nout tags bb;"


def _bbox_str(south: float, west: float, north: float, east: float) -> str:
    return f"{south:.5f},{west:.5f},{north:.5f},{east:.5f}"


def land_bbox(points: list[tuple[float, float]], pad_m: int) -> tuple[float, float, float, float]:
    """(south, west, north, east) covering `points` padded by `pad_m` metres."""
    import math

    lat0 = sum(p[0] for p in points) / len(points)
    pad_lat = pad_m / 111_320.0
    pad_lon = pad_m / (111_320.0 * max(math.cos(math.radians(lat0)), 0.1))
    return (min(p[0] for p in points) - pad_lat, min(p[1] for p in points) - pad_lon,
            max(p[0] for p in points) + pad_lat, max(p[1] for p in points) + pad_lon)


def build_query(lat: float, lon: float, facility_radius_m: int, land_radius_m: int, timeout_s: int = 45,
                land_points: list[tuple[float, float]] | None = None) -> str:
    """Facilities within `facility_radius_m` of (lat, lon) plus land use around `land_points`.
    Used only where the local facility index does not yet cover the area."""
    around = f"around:{facility_radius_m},{lat:.5f},{lon:.5f}"
    bbox = _bbox_str(*land_bbox(land_points or [(lat, lon)], land_radius_m))
    return _wrap([f"nwr{f}({around});" for f in _FACILITY_FILTERS] + [f"nwr{f}({bbox});" for f in _LAND_FILTERS], timeout_s)


def build_land_query(points: list[tuple[float, float]], land_radius_m: int, timeout_s: int = 30) -> str:
    """Land use only (2 clauses) — the per-event query once facilities come from the local index."""
    bbox = _bbox_str(*land_bbox(points, land_radius_m))
    return _wrap([f"nwr{f}({bbox});" for f in _LAND_FILTERS], timeout_s)


def build_facility_tile_query(south: float, west: float, north: float, east: float, timeout_s: int = 120) -> str:
    """All facility candidates in a tile — the scheduled local-index sync query."""
    bbox = _bbox_str(south, west, north, east)
    return _wrap([f"nwr{f}({bbox});" for f in _FACILITY_FILTERS], timeout_s)


class OverpassClient:
    def __init__(self, endpoints: list[str] | None = None):
        self.endpoints = endpoints or settings.overpass_url_list

    def query_around(self, lat: float, lon: float, facility_radius_m: int = 10000, land_radius_m: int = 1500,
                     land_points: list[tuple[float, float]] | None = None) -> tuple[list[OsmFeature], str, float]:
        """Facilities + land use around a point. Returns (features, endpoint_used, latency_ms)."""
        return self.run(build_query(lat, lon, facility_radius_m, land_radius_m, land_points=land_points))

    def query_land(self, points: list[tuple[float, float]], land_radius_m: int = 1500) -> tuple[list[OsmFeature], str, float]:
        return self.run(build_land_query(points, land_radius_m))

    def query_facility_tile(self, south: float, west: float, north: float, east: float) -> tuple[list[OsmFeature], str, float]:
        return self.run(build_facility_tile_query(south, west, north, east), timeout=150)

    def run(self, query: str, timeout: float = 75) -> tuple[list[OsmFeature], str, float]:
        """Execute a query, trying each endpoint once (rotating the start). Raises the last ProviderError."""
        last: ProviderError | None = None
        # Rotate the starting endpoint so load spreads across public mirrors.
        OverpassClient._rr = (getattr(OverpassClient, "_rr", -1) + 1) % len(self.endpoints)
        ordered = self.endpoints[OverpassClient._rr:] + self.endpoints[:OverpassClient._rr]
        for endpoint in ordered:
            try:
                res = request(
                    PROVIDER, "POST", endpoint, data={"data": query}, timeout=timeout, max_attempts=1,
                    min_interval_s=settings.overpass_min_interval_s,
                    headers={"Accept": "application/json"},
                )
                payload = res.response.json()
            except ProviderError as exc:
                logger.warning("overpass endpoint %s failed: %s", endpoint, exc)
                last = exc
                continue
            except ValueError:
                last = ProviderMalformed(PROVIDER, f"non-JSON response from {endpoint}")
                continue
            if "elements" not in payload:
                last = ProviderMalformed(PROVIDER, f"response missing 'elements' from {endpoint}")
                continue
            remark = payload.get("remark") or ""
            if "runtime error" in remark.lower():
                last = ProviderMalformed(PROVIDER, f"overpass runtime error: {remark[:160]}")
                continue
            return self._parse(payload["elements"]), endpoint, res.latency_ms
        assert last is not None
        raise last

    @staticmethod
    def _parse(elements: list[dict]) -> list[OsmFeature]:
        out: list[OsmFeature] = []
        for el in elements:
            tags = el.get("tags") or {}
            if el.get("type") == "node":
                lat, lon = el.get("lat"), el.get("lon")
            elif el.get("bounds"):
                b = el["bounds"]
                lat, lon = (b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2
            else:
                center = el.get("center") or {}
                lat, lon = center.get("lat"), center.get("lon")
            if lat is None or lon is None or not tags:
                continue
            out.append(OsmFeature(el["type"], int(el["id"]), float(lat), float(lon), tags, el.get("bounds")))
        return out
