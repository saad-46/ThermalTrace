"""Windowed reads of public cloud-optimised GeoTIFFs (ESA WorldCover, Sentinel-2 L2A bands).

Only a small window around a point is fetched (HTTP range requests), never a whole scene. Every
failure is raised as a typed `ProviderError`, so callers record source health and show
"unavailable" instead of substituting a value. Pure numeric helpers are separate so they can be
tested without network access.
"""
import math

import numpy as np

from app.integrations.http import ProviderError, ProviderMalformed, ProviderNetworkError, ProviderNotFound, ProviderTimeout

WORLDCOVER_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
WORLDCOVER_PRODUCT = "ESA WorldCover 10 m 2021 v200"
# ESA WorldCover legend (class code → name). Grouped for evidence and features below.
WORLDCOVER_CLASSES = {
    10: "tree_cover", 20: "shrubland", 30: "grassland", 40: "cropland", 50: "built_up", 60: "bare_sparse",
    70: "snow_ice", 80: "water", 90: "herbaceous_wetland", 95: "mangroves", 100: "moss_lichen",
}
VEGETATION = ("tree_cover", "shrubland", "grassland", "herbaceous_wetland", "mangroves", "moss_lichen")

# Sentinel-2 L2A scene-classification (SCL) values that are usable for surface reflectance.
SCL_VALID = (4, 5, 7)  # vegetation, not vegetated, unclassified. Cloud, shadow, cirrus, water, snow are excluded.
_TIMEOUT_S = 30
_METRES_PER_DEGREE = 111_320.0


def worldcover_tile_url(lat: float, lon: float) -> str:
    """WorldCover tiles are 3° × 3°, named by their south-west corner."""
    lat0, lon0 = math.floor(lat / 3) * 3, math.floor(lon / 3) * 3
    ns, ew = ("N" if lat0 >= 0 else "S"), ("E" if lon0 >= 0 else "W")
    return f"{WORLDCOVER_BASE}/ESA_WorldCover_10m_2021_v200_{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}_Map.tif"


def read_window(href: str, lat: float, lon: float, half_m: float, out_px: int) -> np.ndarray:
    """Read a square window (side 2*half_m) centred on (lat, lon) as a float32 array of out_px × out_px.

    `href` may be an https URL or a local path. Pixels outside the raster or equal to nodata are
    returned as the dataset's raw values; callers apply their own masks.
    """
    import rasterio
    from rasterio.errors import RasterioIOError
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    dlat = half_m / _METRES_PER_DEGREE
    dlon = half_m / (_METRES_PER_DEGREE * max(math.cos(math.radians(lat)), 0.01))
    try:
        with rasterio.Env(GDAL_HTTP_TIMEOUT=_TIMEOUT_S, GDAL_HTTP_MAX_RETRY=2, GDAL_HTTP_RETRY_DELAY=1,
                          GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST="YES"):
            with rasterio.open(href) as ds:
                left, bottom, right, top = transform_bounds("EPSG:4326", ds.crs, lon - dlon, lat - dlat, lon + dlon, lat + dlat)
                window = from_bounds(left, bottom, right, top, ds.transform)
                if window.width < 1 or window.height < 1:
                    raise ProviderMalformed("window smaller than one pixel")
                return ds.read(1, window=window, out_shape=(out_px, out_px), boundless=True, fill_value=0).astype("float32")
    except ProviderError:
        raise
    except RasterioIOError as exc:
        msg = str(exc)
        if "404" in msg or "not exist" in msg or "No such file" in msg:
            raise ProviderNotFound(msg) from exc
        if "timed out" in msg.lower() or "timeout" in msg.lower():
            raise ProviderTimeout(msg) from exc
        raise ProviderNetworkError(msg) from exc


def landcover_fractions(window: np.ndarray) -> dict:
    """Class shares of a WorldCover window. Code 0 (no data) is excluded from the denominator."""
    valid = window[window > 0]
    if valid.size == 0:
        return {"fractions": {}, "dominant": None, "valid_fraction": 0.0}
    codes, counts = np.unique(valid.astype(int), return_counts=True)
    fractions = {WORLDCOVER_CLASSES.get(int(c), f"class_{int(c)}"): round(float(n) / valid.size, 4) for c, n in zip(codes, counts, strict=True)}
    dominant = max(fractions, key=fractions.get)
    return {"fractions": fractions, "dominant": dominant, "valid_fraction": round(valid.size / window.size, 4)}


def sample_worldcover(lat: float, lon: float, half_m: float = 750.0, href: str | None = None) -> dict:
    """Land-cover class shares in a square of side 2*half_m around the point."""
    window = read_window(href or worldcover_tile_url(lat, lon), lat, lon, half_m, out_px=30)
    return {**landcover_fractions(window), "product": WORLDCOVER_PRODUCT, "window_m": half_m * 2,
            "source_ref": href or worldcover_tile_url(lat, lon)}


def reflectance(dn: np.ndarray, baseline: float | None) -> np.ndarray:
    """Sentinel-2 L2A digital numbers → surface reflectance. Processing baseline ≥ 04.00 carries a
    −1000 DN offset (BOA_ADD_OFFSET). DN 0 is nodata and becomes NaN."""
    out = dn.astype("float32")
    out[dn == 0] = np.nan
    offset = 1000.0 if baseline is not None and baseline >= 4.0 else 0.0
    return np.clip((out - offset) / 10000.0, 0.0, None)


def normalised_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a − b) / (a + b); undefined (NaN) where the sum is zero."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (a - b) / (a + b)
    out[~np.isfinite(out)] = np.nan
    return out


def masked_mean(index: np.ndarray, scl: np.ndarray) -> tuple[float | None, float]:
    """Mean of `index` over pixels the scene classification marks usable. Returns (mean, valid share)."""
    usable = np.isin(scl.astype(int), SCL_VALID) & np.isfinite(index)
    share = float(usable.sum()) / index.size if index.size else 0.0
    return (round(float(index[usable].mean()), 4) if usable.any() else None), round(share, 4)


def group_fractions(fractions: dict | None) -> dict:
    """Coarse groups used by evidence and features: vegetation, cropland, built_up, bare, water."""
    f = fractions or {}
    return {
        "vegetation": round(sum(f.get(k, 0.0) for k in VEGETATION), 4),
        "cropland": f.get("cropland", 0.0),
        "built_up": f.get("built_up", 0.0),
        "bare": f.get("bare_sparse", 0.0),
        "water": f.get("water", 0.0),
    }
