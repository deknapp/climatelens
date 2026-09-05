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
from typing import Any, Sequence

import httpx

from .config import CACHE_DIR

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
CLIMATE_URL = "https://climate-api.open-meteo.com/v1/climate"

# NOAA CPC's Oceanic Nino Index: the official ENSO yardstick. A plain text
# table, no key, updated monthly, back to 1950. Each row is a three-month
# season and its sea-surface temperature anomaly in the Nino 3.4 region.
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"

# ERA5 is a gridded reanalysis, not a weather station. Roughly 25 km per cell.
ERA5_GRID_KM = 25

DAILY_VARS = ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean"]

# The ENSO composite needs precipitation as well as temperature: for most
# places the El Nino signal shows up in how wet the winter is long before it
# shows up in how warm it is.
ENSO_VARS = ["temperature_2m_mean", "precipitation_sum"]

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


def _get_text(url: str, *, cache: str, ttl_hours: float = 24.0,
              timeout: float = 60.0, retries: int = 3) -> str:
    """GET a plain text file, cached on disk with an expiry.

    Unlike the climate archives, this one does change: NOAA appends a row each
    month. So the cache has a time to live rather than living forever.
    """
    path = _cache_path(cache, url)
    if path.exists():
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        if age_hours < ttl_hours:
            try:
                return json.loads(path.read_text())["text"]
            except (json.JSONDecodeError, KeyError):
                path.unlink(missing_ok=True)

    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = httpx.get(url, timeout=timeout)
            resp.raise_for_status()
            path.write_text(json.dumps({"text": resp.text}))
            return resp.text
        except httpx.HTTPError as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))

    # A stale copy beats no answer at all -- the index only moves once a month.
    if path.exists():
        try:
            return json.loads(path.read_text())["text"]
        except (json.JSONDecodeError, KeyError):
            pass
    raise DataError(f"could not reach {url}: {last}")


def oni_index() -> list[dict[str, Any]]:
    """The full ONI record: one row per overlapping three-month season.

    Returns ``[{"season": "DJF", "year": 1950, "anomaly": -1.32}, ...]`` in
    chronological order. The year on a DJF row is the year of its January --
    NOAA's convention, and the one every El Nino event is named after.
    """
    text = _get_text(ONI_URL, cache="oni")
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[0] == "SEAS":
            continue
        season, year, _total, anomaly = parts
        try:
            rows.append({"season": season, "year": int(year),
                         "anomaly": float(anomaly)})
        except ValueError:
            continue
    if not rows:
        raise DataError("the ONI table came back in a shape we do not recognise")
    return rows


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


def era5_daily(lat: float, lon: float, start_year: int, end_year: int,
               variables: Sequence[str] | None = None) -> dict[str, list]:
    """Observed daily weather from ERA5 for a span of whole years."""
    return era5_range(lat, lon, f"{start_year}-01-01", f"{end_year}-12-31",
                      variables=variables)


def era5_range(lat: float, lon: float, start_date: str, end_date: str,
               variables: Sequence[str] | None = None) -> dict[str, list]:
    """Observed daily weather from ERA5 between two explicit dates.

    The ENSO composite needs to start in December of the year before its first
    winter, which whole-year bounds cannot express.
    """
    payload = _get(ARCHIVE_URL, {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "start_date": start_date,
        "end_date": end_date,
        "daily": ",".join(variables or DAILY_VARS),
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
