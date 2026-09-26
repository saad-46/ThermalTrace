"""Deterministic rule cascade (event level). Grew out of an earlier
detection-level cascade (rule-cascade-v0.1), extended with the full taxonomy, land context and FRP steadiness.

It encodes published domain knowledge (see docs/ML.md §Rules): flares are persistent,
night-visible and co-located with oil/gas infrastructure; process heat is recurring at heavy
industry; coal-seam fires recur at mines over months; crop-residue burns are short-lived on
cropland in known seasons; wildfires occur in forest/scrub away from industry.

Probabilities are *calibrated guesses by rule*, capped deliberately where the literature says
the boundary is hard (flare vs. process heat). They are not frequencies learned from data.
"""
import math

from app.ml.base import SOURCE_CLASSES, BaseClassifier, Contribution, Prediction

MODEL_ID = "rule-cascade-v1.1"

NEAR_OIL_KM = 2.0
NEAR_INDUSTRY_KM = 2.0
NEAR_MINE_KM = 3.0
AGRI_MONTHS = {3, 4, 5, 10, 11, 12}
# Raster land-cover fallback (ESA WorldCover, 750 m around the event) used only when OSM land use has
# not been retrieved. It needs a clear majority and little built-up area, and its probabilities are
# capped below the OSM path: the product is from 2021 and a 1.5 km window can mix land uses.
RASTER_MAJORITY = 0.5
RASTER_MAX_BUILT_UP = 0.2
RASTER_P_CAP = 0.6


def _isnan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def _within(v, km: float) -> bool:
    return not _isnan(v) and v <= km


class RuleCascadeClassifier(BaseClassifier):
    model_id = MODEL_ID
    kind = "rule"

    def predict(self, f: dict[str, float], context: dict) -> Prediction:
        trace: list[str] = []
        contrib: list[Contribution] = []
        persistence = context.get("persistence_class", "transient")
        month = context.get("month")
        night = f.get("night_fraction")
        frp_max = math.expm1(f["frp_max_log"]) if not _isnan(f.get("frp_max_log")) else None
        obs = round(math.expm1(f["observation_count_log"])) if not _isnan(f.get("observation_count_log")) else 0
        osm_checked = context.get("osm_checked", False)

        def done(label: str, p: float, notes: list[str] | None = None) -> Prediction:
            p = round(min(max(p, 0.05), 0.95), 3)
            rest = [c for c in SOURCE_CLASSES if c != label]
            share = (1 - p) / len(rest)
            probs = {c: round(share, 4) for c in rest}
            probs[label] = p
            return Prediction(self.model_id, label, p, probs, "rule_trace", contrib, trace, notes or [])

        # Gate 0: too little signal to say anything.
        if obs <= 1 and (frp_max is None or frp_max < 5):
            trace.append(f"Single low-intensity detection (FRP {frp_max or 0:.1f} MW): insufficient signal.")
            contrib.append(Contribution("observation_count_log", obs, -1.0))
            return done("unknown", 0.3, ["Gate 0 — insufficient signal"])

        d_oil, d_heavy, d_mine = f.get("dist_oil_gas_km"), f.get("dist_heavy_industry_km"), f.get("dist_mine_km")

        # 1. Flare: oil/gas infrastructure + persistence + night visibility.
        if _within(d_oil, NEAR_OIL_KM):
            contrib.append(Contribution("dist_oil_gas_km", d_oil, +1.0))
            trace.append(f"{d_oil:.2f} km from mapped oil/gas infrastructure ({context.get('oil_name') or 'unnamed'}).")
            if persistence in ("persistent", "recurring") and not _isnan(night) and night >= 0.4:
                contrib += [Contribution("persistence_score", f.get("persistence_score"), +0.8),
                            Contribution("night_fraction", night, +0.6)]
                trace.append(f"{persistence.title()} activity with {night:.0%} night detections — flare-like signature.")
                p = 0.62 + 0.15 * min(f.get("persistence_score") or 0, 1) + (0.08 if (f.get("frp_cv") or 1) < 0.6 else 0)
                return done("flare", min(p, 0.88))
            if persistence != "transient":
                trace.append("Recurring near oil/gas but without strong night dominance: flare vs process heat is ambiguous.")
                return done("process_heat", 0.5, ["Flare/process-heat boundary — capped"])

        # 2. Heavy industry: steady recurring heat = process heat; transient intense = possible fire.
        if _within(d_heavy, NEAR_INDUSTRY_KM):
            contrib.append(Contribution("dist_heavy_industry_km", d_heavy, +1.0))
            trace.append(f"{d_heavy:.2f} km from mapped heavy industry ({context.get('heavy_name') or 'unnamed'}).")
            if persistence in ("persistent", "recurring"):
                contrib.append(Contribution("persistence_score", f.get("persistence_score"), +0.7))
                trace.append(f"{persistence.title()} activity at an industrial site — consistent with process heat.")
                return done("process_heat", min(0.5 + 0.25 * (f.get("persistence_score") or 0) + 0.05 * min(f.get("sensor_count") or 0, 3), 0.75),
                            ["Capped at 0.75: furnace/kiln vs flare vs accidental fire cannot be separated by FIRMS alone"])
            if frp_max is not None and frp_max >= 40 and _within(d_heavy, 1.0):
                contrib.append(Contribution("frp_max_log", f.get("frp_max_log"), +0.6))
                trace.append(f"Transient, high-intensity ({frp_max:.0f} MW) detection inside/near an industrial site.")
                return done("industrial_fire", 0.45, ["Possible accident — requires analyst review; never auto-confirmed"])

        # 3. Mines: multi-day recurrence near a mine → coal-seam/mine fire.
        if _within(d_mine, NEAR_MINE_KM):
            contrib.append(Contribution("dist_mine_km", d_mine, +1.0))
            trace.append(f"{d_mine:.2f} km from a mapped mine ({context.get('mine_name') or 'unnamed'}).")
            if persistence in ("persistent", "recurring") or (f.get("recurrence_count") or 0) >= 1:
                contrib.append(Contribution("recurrence_count", f.get("recurrence_count"), +0.7))
                trace.append("Repeated activity at a mining site — consistent with coal-seam / mine fire.")
                return done("coal_seam_fire", 0.55 + 0.2 * min(f.get("persistence_score") or 0, 1))

        # 4. No industrial context: land cover + seasonality.
        crop, forest = f.get("land_cropland"), f.get("land_forest")
        raster = False
        if not osm_checked:
            lc_crop, lc_veg, lc_built = f.get("lc_cropland_frac"), f.get("lc_vegetation_frac"), f.get("lc_built_up_frac")
            if not _isnan(lc_crop) and (_isnan(lc_built) or lc_built <= RASTER_MAX_BUILT_UP):
                raster = True
                crop = 1.0 if lc_crop >= RASTER_MAJORITY else 0.0
                forest = 1.0 if not _isnan(lc_veg) and lc_veg >= RASTER_MAJORITY else 0.0
                trace.append(f"OSM land use not retrieved; using ESA WorldCover 2021 within 750 m (cropland {lc_crop:.0%}, "
                             f"natural vegetation {lc_veg if not _isnan(lc_veg) else 0:.0%}, built-up {lc_built if not _isnan(lc_built) else 0:.0%}).")
            elif not _isnan(lc_crop):
                trace.append(f"OSM land use not retrieved; raster land cover is {lc_built:.0%} built-up within 750 m, "
                             "too mixed to separate vegetation classes.")
            else:
                trace.append("Land context not yet retrieved from OSM or raster land cover — vegetation classes cannot be separated.")
        if crop == 1.0 and persistence != "persistent" and (forest != 1.0 or (month in AGRI_MONTHS)):
            if raster:
                contrib.append(Contribution("lc_cropland_frac", f.get("lc_cropland_frac"), +1.0))
                trace.append("Cropland is the majority land cover and no industrial facility is mapped within 2 km.")
            else:
                contrib.append(Contribution("land_cropland", crop, +1.0))
                trace.append("Mapped cropland within 1.5 km and no industrial facility within 2 km.")
            p = 0.55 + (0.12 if month in AGRI_MONTHS else 0) + (0.05 if persistence == "transient" else 0)
            if month in AGRI_MONTHS:
                contrib.append(Contribution("month_sin", f.get("month_sin"), +0.4))
                trace.append(f"Month {month} is within the documented crop-residue burning seasons (Mar–May, Oct–Dec).")
            if raster:
                return done("agricultural_burn", min(p, RASTER_P_CAP), ["Land context from raster land cover (capped)"])
            return done("agricultural_burn", p)
        if forest == 1.0:
            if raster:
                contrib.append(Contribution("lc_vegetation_frac", f.get("lc_vegetation_frac"), +1.0))
                trace.append("Natural vegetation is the majority land cover and no industrial facility is mapped within 2 km.")
                return done("wildfire", min(0.55 + (0.1 if persistence == "transient" else 0), RASTER_P_CAP),
                            ["Land context from raster land cover (capped)"])
            contrib.append(Contribution("land_forest", forest, +1.0))
            trace.append("Mapped forest/scrub within 1.5 km and no industrial facility within 2 km.")
            return done("wildfire", 0.55 + (0.1 if persistence == "transient" else 0))

        if persistence == "persistent":
            trace.append("Persistent source with no mapped facility or land context: likely an unmapped industrial site.")
            contrib.append(Contribution("persistence_score", f.get("persistence_score"), +0.5))
            return done("other", 0.4, ["Candidate unmapped industrial source — check imagery"])
        trace.append("No facility, land-use or persistence signal strong enough to discriminate.")
        return done("unknown", 0.35)
