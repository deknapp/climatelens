"""Capture real computed output for a few points, once, into evals/fixtures/.

The evals must not depend on Open-Meteo being up, and must not re-pull a
30-year daily series every time they run. So the *inputs* to narration are
frozen here: whatever the app really computed for these points on the day this
was run. Re-run this only when the computation itself changes.

    python -m evals.capture_fixtures

No API key needed -- this half is all arithmetic.
"""

from __future__ import annotations

import calendar
import json
import sys
from pathlib import Path

from climatelens import data, enso, indicators
from climatelens.api import ENSO_START, PROJECTION, _last_complete_winter
from climatelens.config import BASELINE, GLOBAL_WARMING_C, RECENT

FIXTURES = Path(__file__).parent / "fixtures"

# Chosen because each one is a different kind of hard case, not because they
# are interesting places.
PLACES = {
    # Strong warming, a real frost/growing-season story, and an ENSO composite
    # that is famously *not* significant here (7 strong events, p=0.199) --
    # the textbook El Nino map says "wetter southwest" and the data does not.
    "santa-fe": ("Santa Fe, New Mexico", 35.687, -105.938),
    # Equatorial: no frost, no growing season (all None), and flat ENSO precip.
    # The right answer to "what does El Nino do here" is "not much".
    "jakarta": ("Jakarta, Indonesia", -6.2088, 106.8456),
    # Southern hemisphere: growing-season fields are deliberately withheld
    # because the northern-hemisphere frost arithmetic would run backwards.
    "hobart": ("Hobart, Tasmania", -42.8821, 147.3272),
}


def climate(lat: float, lon: float) -> dict:
    base = indicators.normal(data.era5_daily(lat, lon, *BASELINE), *BASELINE, latitude=lat)
    recent = indicators.normal(data.era5_daily(lat, lon, *RECENT), *RECENT, latitude=lat)
    try:
        proj = indicators.normal(data.cmip6_daily(lat, lon, *PROJECTION), *PROJECTION, latitude=lat)
        proj_base = indicators.normal(data.cmip6_daily(lat, lon, *BASELINE), *BASELINE, latitude=lat)
    except data.DataError as exc:
        print(f"  no projection: {exc}")
        proj = proj_base = None
    comparison = indicators.compare(base, recent, proj,
                                    global_warming_c=GLOBAL_WARMING_C,
                                    projection_baseline=proj_base)
    return {"latitude": lat, "longitude": lon,
            "grid_resolution_km": data.ERA5_GRID_KM,
            **comparison.to_dict()}


def enso_report(lat: float, lon: float) -> dict | None:
    end_year = _last_complete_winter()
    last_day = calendar.monthrange(end_year, 2)[1]
    try:
        oni = data.oni_index()
        daily = data.era5_range(lat, lon, ENSO_START,
                                f"{end_year}-02-{last_day:02d}",
                                variables=data.ENSO_VARS)
    except data.DataError as exc:
        print(f"  no enso: {exc}")
        return None
    return {"latitude": lat, "longitude": lon, **enso.report(oni, daily).to_dict()}


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[1:] or list(PLACES)
    for slug in wanted:
        label, lat, lon = PLACES[slug]
        print(f"{slug}: {label}")
        payload = {"label": label, "comparison": climate(lat, lon),
                   "enso": enso_report(lat, lon)}
        out = FIXTURES / f"{slug}.json"
        out.write_text(json.dumps(payload, indent=2, default=str))
        print(f"  wrote {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
