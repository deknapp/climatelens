"""Clients for the three Open-Meteo services this app is built on.

None of them need an API key. All three are thin wrappers over real scientific
products:

  * ERA5 (archive-api)  -- ECMWF's reanalysis, the standard record of what the
    weather actually was, 1940 to present, on a ~25 km grid.
  * CMIP6 (climate-api) -- downscaled projections from the model intercomparison
    that underpins the IPCC assessment reports.
  * Geocoding           -- place name to coordinates.

Everything is cached to disk. A thirty-year daily pull is slow and the answer
does not change.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .config import CACHE_DIR

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
CLIMATE_URL = "https://climate-api.open-meteo.com/v1/climate"

# ERA5 is a gridded reanalysis, not a weather station. Roughly 25 km per cell.
ERA5_GRID_KM = 25

DAILY_VARS = ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean"]

# One CMIP6 model, chosen because Open-Meteo downscales it to 5 km and it covers
# the full 1950-2050 span. Named in the UI so the choice is visible, not hidden.
CMIP6_MODEL = "MRI_AGCM3_2_S"


class DataError(RuntimeError):
    """A climate data source failed in a way the user should be told about."""


@dataclass(frozen=True)
class Place:
    name: str
    country: str
    admin1: str
    latitude: float
    longitude: float
    timezone: str
    elevation: float | None = None

    @property
    def label(self) -> str:
        bits = [self.name]
        if self.admin1 and self.admin1 != self.name:
            bits.append(self.admin1)
        if self.country:
            bits.append(self.country)
        return ", ".join(bits)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["label"] = self.label
        return d


def _cache_path(kind: str, key: str) -> Any:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{kind}-{digest}.json"


def _get(url: str, params: dict[str, Any], *, cache: str | None = None,
         timeout: float = 90.0, retries: int = 3) -> dict[str, Any]:
    """GET with a disk cache and a few polite retries."""
    key = url + json.dumps(params, sort_keys=True)
    path = _cache_path(cache, key) if cache else None

    if path is not None and path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            path.unlink(missing_ok=True)

    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = httpx.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            resp.raise_for_status()
            payload = resp.json()
            if "error" in payload and payload.get("error"):
                raise DataError(payload.get("reason", "upstream error"))
            if path is not None:
                path.write_text(json.dumps(payload))
            return payload
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise DataError(f"could not reach {url}: {last}")


def geocode(name: str, count: int = 8) -> list[Place]:
    """Search for a place by name.

    Returns every match rather than guessing. "Santa Fe" resolves to Argentina
    before New Mexico, so the caller must let a human choose.
    """
    name = (name or "").strip()
    if not name:
        return []
    payload = _get(GEOCODE_URL, {"name": name, "count": count, "language": "en",
                                 "format": "json"}, cache="geo")
    out = []
    for r in payload.get("results") or []:
        out.append(Place(
            name=r.get("name", ""),
            country=r.get("country", ""),
            admin1=r.get("admin1", "") or "",
            latitude=float(r["latitude"]),
            longitude=float(r["longitude"]),
            timezone=r.get("timezone", "UTC"),
            elevation=r.get("elevation"),
        ))
    return out


def era5_daily(lat: float, lon: float, start_year: int, end_year: int) -> dict[str, list]:
    """Observed daily temperature from ERA5 for a span of whole years."""
    payload = _get(ARCHIVE_URL, {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "start_date": f"{start_year}-01-01",
        "end_date": f"{end_year}-12-31",
        "daily": ",".join(DAILY_VARS),
        "timezone": "UTC",
    }, cache="era5")
    return payload.get("daily", {})


def cmip6_daily(lat: float, lon: float, start_year: int, end_year: int,
                model: str = CMIP6_MODEL) -> dict[str, list]:
    """Projected daily temperature from a downscaled CMIP6 model."""
    payload = _get(CLIMATE_URL, {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "start_date": f"{start_year}-01-01",
        "end_date": f"{end_year}-12-31",
        "models": model,
        "daily": ",".join(DAILY_VARS),
    }, cache="cmip6")
    daily = payload.get("daily", {})
    # The climate API suffixes each variable with the model name; strip it so
    # callers see the same keys they get from ERA5.
    return {k.replace(f"_{model}", ""): v for k, v in daily.items()}
