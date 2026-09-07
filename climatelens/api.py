"""HTTP layer.

The browser talks only to these routes. It never holds an API key and never
calls Anthropic or Open-Meteo directly -- which is the point: the key lives in
the server process and nowhere else.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import data, enso, indicators, llm
from .config import BASELINE, GLOBAL_WARMING_C, RECENT, load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("climatelens")

PROJECTION = (2040, 2049)

# The ENSO composite needs every winter NOAA's index covers. Its first is DJF
# 1950, which begins in December 1949 -- hence the explicit date rather than a
# year bound.
ENSO_START = "1949-12-01"

app = FastAPI(
    title="climatelens",
    description="What climate change has already done to one place on Earth.",
    version="0.1.0",
)

STATIC = __import__("pathlib").Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    """Whether narration is available. Never reveals the key itself."""
    return {"ok": True, "narration_available": llm.available()}


@app.get("/api/geocode")
def api_geocode(q: str = Query(..., min_length=1, max_length=120)) -> dict:
    """Search for a place. Returns every match -- the caller disambiguates."""
    try:
        places = data.geocode(q)
    except data.DataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"results": [p.to_dict() for p in places]}


@app.get("/api/climate")
def api_climate(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    projection: bool = Query(True),
) -> dict:
    """The whole computation for one point: two normals, deltas, projection."""
    try:
        base_daily = data.era5_daily(latitude, longitude, *BASELINE)
        recent_daily = data.era5_daily(latitude, longitude, *RECENT)
    except data.DataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    base = indicators.normal(base_daily, *BASELINE, latitude=latitude)
    recent = indicators.normal(recent_daily, *RECENT, latitude=latitude)

    proj = proj_base = None
    spread = None
    if projection:
        try:
            # Every model, in two requests. Each model is differenced against
            # its *own* baseline so its systematic bias cancels -- see
            # indicators.compare(). Crossing models here would report the
            # difference between models as warming.
            future_by_model = data.cmip6_daily_by_model(
                latitude, longitude, *PROJECTION)
            base_by_model = data.cmip6_daily_by_model(
                latitude, longitude, *BASELINE)

            per_model = {}
            for model, future in future_by_model.items():
                baseline = base_by_model.get(model)
                if baseline is None:
                    continue
                per_model[model] = (
                    indicators.normal(future, *PROJECTION, latitude=latitude),
                    indicators.normal(baseline, *BASELINE, latitude=latitude),
                )

            spread = _model_spread(per_model)

            # The headline still comes from one named model, so the numbers in
            # the narration stay traceable to a single coherent simulation
            # rather than being an average no model actually produced.
            headline = data.CMIP6_MODEL if data.CMIP6_MODEL in per_model else next(
                iter(per_model))
            proj, proj_base = per_model[headline]
        except data.DataError as exc:
            # A missing projection is not fatal -- the observed record is the
            # headline and stands on its own.
            log.warning("projection unavailable for %s,%s: %s", latitude, longitude, exc)
            proj = proj_base = None
            spread = None

    comparison = indicators.compare(base, recent, proj,
                                    global_warming_c=GLOBAL_WARMING_C,
                                    projection_baseline=proj_base)
    result = {
        "latitude": latitude,
        "longitude": longitude,
        "grid_resolution_km": data.ERA5_GRID_KM,
        "sources": {
            "observed": "ERA5 reanalysis (ECMWF), via Open-Meteo",
            "projected": f"CMIP6 {data.CMIP6_MODEL} downscaled, via Open-Meteo",
        },
        **comparison.to_dict(),
    }
    if spread:
        result["model_spread"] = spread
        result["sources"]["projection_spread"] = (
            f"{spread['n_models']} CMIP6 models: {', '.join(spread['models'])}"
        )
    return result


def _model_spread(per_model: dict) -> dict | None:
    """How much the models disagree about the warming at this point.

    Each model is differenced against its own baseline first, so what is
    compared across models is the *change* each one projects, not its absolute
    temperature. Absolute temperatures differ between models mostly because of
    their own biases, and comparing those would be measuring the models rather
    than the climate.

    The spread is reported as a range, not a standard deviation. Five models is
    far too few for a distribution to mean anything, and quoting a sigma over
    five numbers implies a precision that is not there.
    """
    deltas = {}
    for model, (future, baseline) in per_model.items():
        # A model missing either mean is skipped, but never silently: an
        # earlier version caught AttributeError here and returned no spread at
        # all when the field had simply been misnamed, which looked exactly
        # like "the models agree" and was not.
        if future.mean_c is None or baseline.mean_c is None:
            log.warning("CMIP6 model %s has no mean temperature; excluded", model)
            continue
        deltas[model] = future.mean_c - baseline.mean_c

    if len(deltas) < 2:
        return None

    values = sorted(deltas.values())
    middle = len(values) // 2
    median = (values[middle] if len(values) % 2
              else (values[middle - 1] + values[middle]) / 2)

    return {
        "n_models": len(deltas),
        "models": sorted(deltas),
        "warming_c_by_model": {m: round(v, 2) for m, v in sorted(deltas.items())},
        "warming_c_median": round(median, 2),
        "warming_c_low": round(values[0], 2),
        "warming_c_high": round(values[-1], 2),
        "agreement": (
            "all models warm" if values[0] > 0
            else "models disagree on sign" if values[-1] > 0
            else "all models cool"
        ),
    }


def _last_complete_winter() -> int:
    """The most recent year whose December-January-February has fully elapsed.

    Pinned to a whole winter rather than to today so that the cache key moves
    once a year instead of once a day.
    """
    import datetime

    today = datetime.date.today()
    return today.year if today.month >= 3 else today.year - 1


@app.get("/api/enso")
def api_enso(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
) -> dict:
    """What El Nino and La Nina winters have actually done at this point.

    Deliberately a separate route from /api/climate: it is a different
    question over a different record, it is slower, and the page should render
    the warming numbers without waiting on it.
    """
    import calendar

    end_year = _last_complete_winter()
    last_day = calendar.monthrange(end_year, 2)[1]
    try:
        oni = data.oni_index()
        daily = data.era5_range(latitude, longitude, ENSO_START,
                                f"{end_year}-02-{last_day:02d}",
                                variables=data.ENSO_VARS)
    except data.DataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    report = enso.report(oni, daily)
    return {
        "latitude": latitude,
        "longitude": longitude,
        "sources": {
            "index": "Oceanic Nino Index, NOAA Climate Prediction Center",
            "observed": "ERA5 reanalysis (ECMWF), via Open-Meteo",
        },
        "thresholds": {
            "el_nino_c": enso.EL_NINO_C,
            "la_nina_c": enso.LA_NINA_C,
            "strong_c": enso.STRONG_C,
        },
        **report.to_dict(),
    }


@app.post("/api/explain")
def api_explain(body: dict) -> JSONResponse:
    """Narrate a comparison the client already has. Server-side key only."""
    label = str(body.get("label") or "this location")[:200]
    comparison = body.get("comparison")
    if not isinstance(comparison, dict):
        raise HTTPException(status_code=400, detail="comparison object required")
    enso_report = body.get("enso")
    if not isinstance(enso_report, dict):
        enso_report = None
    try:
        return JSONResponse({"text": llm.explain(label, comparison, enso=enso_report)})
    except llm.LLMUnavailable as exc:
        return JSONResponse({"text": None, "reason": str(exc)}, status_code=503)
    except Exception as exc:  # noqa: BLE001 - surface upstream failure, not a key
        log.exception("narration failed")
        raise HTTPException(status_code=502, detail=f"narration failed: {type(exc).__name__}") from exc


def main() -> None:
    import uvicorn

    from .config import PORT

    uvicorn.run(app, host="127.0.0.1", port=PORT)
