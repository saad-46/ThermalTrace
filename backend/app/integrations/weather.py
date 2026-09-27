"""Open-Meteo weather (no key). Ported contract from sih-fire-backend: a failed lookup raises —
it never substitutes placeholder values (audit R1 strength).

- Conditions at detection time: Archive API (ERA5 reanalysis, ~5-day latency) for older
  timestamps, Forecast API `past_days` hourly for recent ones.
- The provider answering without a value for the requested hour is *no data* (WeatherNoData), which is
  not a provider failure: the service worked, it has no observation for that time and place. ERA5 lags
  ~5 days, so an archive hole is retried against the Forecast API's recent hours (up to 92 days back).
- Wind direction is meteorological (direction the wind blows FROM). The *potential dispersion
  direction* is therefore (wind_direction + 180) % 360.
"""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.integrations.http import ProviderMalformed, request

PROVIDER = "open_meteo"
FORECAST_MAX_PAST_DAYS = 92  # Open-Meteo Forecast API limit for `past_days`


class WeatherNoData(Exception):
    """The provider responded, but has no observation for the requested hour and place."""

    def __init__(self, message: str, latency_ms: float | None = None):
        super().__init__(message)
        self.latency_ms = latency_ms
HOURLY_VARS = "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,precipitation,surface_pressure,weather_code"

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers", 81: "Rain showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, heavy hail",
}


@dataclass
class WeatherSample:
    observed_at: datetime
    dataset: str
    temperature_c: float | None
    humidity_pct: float | None
    wind_speed_ms: float | None
    wind_direction_deg: float | None
    precipitation_mm: float | None
    pressure_hpa: float | None
    weather_code: int | None
    raw: dict
    latency_ms: float

    @property
    def condition(self) -> str | None:
        return WMO_CODES.get(self.weather_code) if self.weather_code is not None else None

    @property
    def dispersion_bearing_deg(self) -> float | None:
        return None if self.wind_direction_deg is None else (self.wind_direction_deg + 180.0) % 360.0


def _pick_hour(payload: dict, target: datetime, dataset: str, latency: float) -> WeatherSample:
    hourly = payload.get("hourly")
    if not hourly or "time" not in hourly:
        raise ProviderMalformed(PROVIDER, "response missing hourly block")
    times = hourly["time"]
    target_key = target.astimezone(UTC).strftime("%Y-%m-%dT%H:00")
    try:
        idx = times.index(target_key)
    except ValueError:
        raise WeatherNoData(f"{dataset}: hour {target_key} not in the response", latency) from None

    def val(name: str):
        series = hourly.get(name) or []
        return series[idx] if idx < len(series) else None

    ws_kmh = val("wind_speed_10m")
    sample = WeatherSample(
        observed_at=datetime.fromisoformat(times[idx]).replace(tzinfo=UTC),
        dataset=dataset,
        temperature_c=val("temperature_2m"),
        humidity_pct=val("relative_humidity_2m"),
        wind_speed_ms=round(ws_kmh / 3.6, 2) if ws_kmh is not None else None,
        wind_direction_deg=val("wind_direction_10m"),
        precipitation_mm=val("precipitation"),
        pressure_hpa=val("surface_pressure"),
        weather_code=val("weather_code"),
        raw={"hour": times[idx], **{k: val(k) for k in HOURLY_VARS.split(",")}, "units": payload.get("hourly_units")},
        latency_ms=latency,
    )
    if sample.wind_speed_ms is None and sample.temperature_c is None:
        raise WeatherNoData(f"{dataset}: no values for {target_key}", latency)
    return sample


class WeatherClient:
    def conditions_at(self, lat: float, lon: float, when: datetime) -> WeatherSample:
        when = when.astimezone(UTC)
        age = datetime.now(UTC) - when
        day = when.date().isoformat()
        if age > timedelta(days=6):
            res = request(
                PROVIDER, "GET", settings.open_meteo_archive_url,
                params={"latitude": lat, "longitude": lon, "start_date": day, "end_date": day,
                        "hourly": HOURLY_VARS, "timezone": "UTC"},
                timeout=20,
            )
            try:
                return _pick_hour(res.response.json(), when, "Open-Meteo Archive (ERA5 reanalysis)", res.latency_ms)
            except WeatherNoData:
                if age > timedelta(days=FORECAST_MAX_PAST_DAYS):
                    raise  # older than the Forecast API keeps: the archive is the only source
        past_days = min(max(age.days + 1, 1), FORECAST_MAX_PAST_DAYS)
        res = request(
            PROVIDER, "GET", settings.open_meteo_forecast_url,
            params={"latitude": lat, "longitude": lon, "hourly": HOURLY_VARS, "past_days": past_days,
                    "forecast_days": 1, "timezone": "UTC"},
            timeout=20,
        )
        return _pick_hour(res.response.json(), when, "Open-Meteo Forecast (recent hourly model)", res.latency_ms)

    def current(self, lat: float, lon: float) -> WeatherSample:
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        return self.conditions_at(lat, lon, now)
