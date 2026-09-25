"""Sentinel-2 search, metadata and previews.

- SatelliteSearchService: STAC search (Element84 Earth Search — keyless, public COGs and JPEG
  previews on AWS Open Data; CDSE STAC as a second catalogue).
- SatellitePreviewService: returns the provider's preview JPEG URL; with Copernicus OAuth
  credentials it can also render an AOI SWIR composite (B12/B8A/B4) via the Sentinel Hub
  Process API on CDSE — SWIR highlights active high-temperature pixels.
- SatelliteMetadataService: normalizes item properties shown alongside every image in the UI
  (acquisition time, platform, processing level, cloud %, source).

No raster is downloaded in full; the design is metadata-first (docs/GIS.md §Satellite).
"""
import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.integrations.http import ProviderAuthError, ProviderError, request

logger = logging.getLogger(__name__)


@dataclass
class SceneMetadata:
    provider: str
    source_id: str
    collection: str
    item_id: str
    platform: str | None
    acquired_at: datetime
    cloud_cover: float | None
    processing_level: str | None
    thumbnail_url: str | None
    item_url: str | None
    bbox: list | None
    assets: dict


class SatelliteMetadataService:
    @staticmethod
    def from_stac(feature: dict, provider: str, source_id: str, collection: str) -> SceneMetadata:
        props = feature.get("properties", {})
        assets = feature.get("assets", {})
        thumb = (assets.get("thumbnail") or assets.get("preview") or assets.get("QUICKLOOK") or {}).get("href")
        self_link = next((lnk["href"] for lnk in feature.get("links", []) if lnk.get("rel") == "self"), None)
        dt = props.get("datetime") or props.get("start_datetime")
        level = props.get("processing:level") or ("L2A" if "l2a" in collection.lower() else None)
        return SceneMetadata(
            provider=provider,
            source_id=source_id,
            collection=collection,
            item_id=feature["id"],
            platform=props.get("platform"),
            acquired_at=datetime.fromisoformat(dt.replace("Z", "+00:00")),
            cloud_cover=props.get("eo:cloud_cover"),
            processing_level=level,
            thumbnail_url=thumb,
            item_url=self_link,
            bbox=feature.get("bbox"),
            assets={
                k: {"href": v.get("href"), "type": v.get("type"), "title": v.get("title")}
                for k, v in assets.items()
                if k in ("thumbnail", "visual", "swir22", "swir16", "nir08", "red", "scl", "B12", "B11", "B8A", "TCI_10m")
            },
        )


class SatelliteSearchService:
    def search(
        self, lat: float, lon: float, start: datetime, end: datetime, max_cloud: float | None = None, limit: int = 20
    ) -> tuple[list[SceneMetadata], float]:
        """Earth Search first; raises ProviderError if the catalogue is unavailable."""
        max_cloud = settings.satellite_max_cloud if max_cloud is None else max_cloud
        body = {
            "collections": ["sentinel-2-l2a"],
            "intersects": {"type": "Point", "coordinates": [lon, lat]},
            "datetime": f"{start.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}/{end.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}",
            "query": {"eo:cloud_cover": {"lte": max_cloud}},
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
            "limit": limit,
        }
        res = request("earth_search", "POST", f"{settings.earth_search_url}/search", json=body, timeout=45)
        features = res.response.json().get("features", [])
        scenes = [SatelliteMetadataService.from_stac(f, "earth-search", "earth_search", "sentinel-2-l2a") for f in features]
        return _dedupe_reprocessed(scenes), res.latency_ms

    def search_cdse(self, lat: float, lon: float, start: datetime, end: datetime, limit: int = 10) -> list[SceneMetadata]:
        body = {
            "collections": ["sentinel-2-l2a"],
            "intersects": {"type": "Point", "coordinates": [lon, lat]},
            "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
            "limit": limit,
        }
        res = request("cdse", "POST", f"{settings.cdse_stac_url}/search", json=body, timeout=45)
        return [SatelliteMetadataService.from_stac(f, "cdse", "cdse", "sentinel-2-l2a") for f in res.response.json().get("features", [])]


def _dedupe_reprocessed(scenes: list[SceneMetadata]) -> list[SceneMetadata]:
    """Earth Search can hold several processing runs of one acquisition (…_0_L2A, …_1_L2A).
    Keep the highest run per (acquisition time, tile)."""
    best: dict[tuple, SceneMetadata] = {}
    for s in scenes:
        parts = s.item_id.split("_")
        tile = parts[1] if len(parts) > 1 else s.item_id
        key = (s.acquired_at, tile)
        if key not in best or s.item_id > best[key].item_id:
            best[key] = s
    return sorted(best.values(), key=lambda s: s.acquired_at, reverse=True)


class _CdseToken:
    _lock = threading.Lock()
    _token: str | None = None
    _expires: float = 0.0

    @classmethod
    def get(cls) -> str:
        if not (settings.copernicus_client_id and settings.copernicus_client_secret):
            raise ProviderAuthError("cdse", "COPERNICUS_CLIENT_ID / COPERNICUS_CLIENT_SECRET not configured")
        with cls._lock:
            if cls._token and time.time() < cls._expires - 60:
                return cls._token
            res = request(
                "cdse", "POST",
                "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
                data={"grant_type": "client_credentials", "client_id": settings.copernicus_client_id,
                      "client_secret": settings.copernicus_client_secret.get_secret_value()},
                timeout=20, max_attempts=2,
            )
            payload = res.response.json()
            cls._token = payload["access_token"]
            cls._expires = time.time() + int(payload.get("expires_in", 600))
            return cls._token


SWIR_EVALSCRIPT = """//VERSION=3
function setup(){return {input:["B12","B8A","B04","dataMask"],output:{bands:4}};}
function evaluatePixel(s){return [2.5*s.B12, 2.5*s.B8A, 2.5*s.B04, s.dataMask];}"""


class SatellitePreviewService:
    """Preview imagery. Provider JPEG previews are public; AOI SWIR renders need CDSE OAuth."""

    @staticmethod
    def swir_available() -> bool:
        return bool(settings.copernicus_client_id and settings.copernicus_client_secret)

    def render_swir(self, lat: float, lon: float, acquired_at: datetime, half_size_m: float = 2500, px: int = 512) -> bytes:
        token = _CdseToken.get()
        dlat = half_size_m / 111_320.0
        import math

        dlon = half_size_m / (111_320.0 * max(math.cos(math.radians(lat)), 0.1))
        body = {
            "input": {
                "bounds": {"bbox": [lon - dlon, lat - dlat, lon + dlon, lat + dlat],
                           "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
                "data": [{"type": "sentinel-2-l2a", "dataFilter": {"timeRange": {
                    "from": (acquired_at - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "to": (acquired_at + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}}}],
            },
            "output": {"width": px, "height": px, "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
            "evalscript": SWIR_EVALSCRIPT,
        }
        try:
            res = request("cdse", "POST", "https://sh.dataspace.copernicus.eu/api/v1/process", json=body,
                          headers={"Authorization": f"Bearer {token}"}, timeout=60, max_attempts=2)
        except ProviderError:
            raise
        return res.response.content
