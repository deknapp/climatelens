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

from . import data, indicators, llm
from .config import BASELINE, GLOBAL_WARMING_C, RECENT, load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("climatelens")

PROJECTION = (2040, 2049)

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

    base = indicators.normal(base_daily, *BASELINE)
    recent = indicators.normal(recent_daily, *RECENT)

    proj = proj_base = None
    if projection:
        try:
            # Both windows come from the same model so its systematic bias
            # cancels in the difference -- see indicators.compare().
            proj = indicators.normal(
                data.cmip6_daily(latitude, longitude, *PROJECTION), *PROJECTION)
            proj_base = indicators.normal(
                data.cmip6_daily(latitude, longitude, *BASELINE), *BASELINE)
        except data.DataError as exc:
            # A missing projection is not fatal -- the observed record is the
            # headline and stands on its own.
            log.warning("projection unavailable for %s,%s: %s", latitude, longitude, exc)
            proj = proj_base = None

    comparison = indicators.compare(base, recent, proj,
                                    global_warming_c=GLOBAL_WARMING_C,
                                    projection_baseline=proj_base)
    return {
        "latitude": latitude,
        "longitude": longitude,
        "grid_resolution_km": data.ERA5_GRID_KM,
        "sources": {
            "observed": "ERA5 reanalysis (ECMWF), via Open-Meteo",
            "projected": f"CMIP6 {data.CMIP6_MODEL} downscaled, via Open-Meteo",
        },
        **comparison.to_dict(),
    }


@app.post("/api/explain")
def api_explain(body: dict) -> JSONResponse:
    """Narrate a comparison the client already has. Server-side key only."""
    label = str(body.get("label") or "this location")[:200]
    comparison = body.get("comparison")
    if not isinstance(comparison, dict):
        raise HTTPException(status_code=400, detail="comparison object required")
    try:
        return JSONResponse({"text": llm.explain(label, comparison)})
    except llm.LLMUnavailable as exc:
        return JSONResponse({"text": None, "reason": str(exc)}, status_code=503)
    except Exception as exc:  # noqa: BLE001 - surface upstream failure, not a key
        log.exception("narration failed")
        raise HTTPException(status_code=502, detail=f"narration failed: {type(exc).__name__}") from exc


def main() -> None:
    import uvicorn

    from .config import PORT

    uvicorn.run(app, host="127.0.0.1", port=PORT)
