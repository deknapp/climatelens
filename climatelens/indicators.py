"""The numbers on the page.

Every figure the app displays is computed here, from daily temperature series,
in plain Python. Nothing in this module asks a language model anything. That
separation is deliberate: the model narrates these numbers, it never produces
them.

A "climate normal" is a thirty-year statistic. Comparing two of them -- 1951-1980
against 1995-2024 -- is what makes a difference a climate signal rather than
weather.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Sequence

# Thresholds. Chosen to be recognisable rather than clever:
HOT_C = 32.0        # ~90 F, the point where heat advisories start to appear
VERY_HOT_C = 35.0   # ~95 F, dangerous for outdoor work
WARM_NIGHT_C = 20.0 # ~68 F, the night-time floor above which sleep degrades
FROST_C = 0.0


@dataclass
class Normal:
    """One thirty-year climate normal at one point."""

    start_year: int
    end_year: int
    years_covered: int
    mean_c: float | None = None
    mean_max_c: float | None = None
    mean_min_c: float | None = None
    hot_days: float | None = None
    very_hot_days: float | None = None
    warm_nights: float | None = None
    frost_days: float | None = None
    growing_season_days: float | None = None
    first_frost_doy: float | None = None
    last_frost_doy: float | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Comparison:
    """Baseline vs recent, plus the deltas that are the actual story."""

    baseline: Normal
    recent: Normal
    projection: Normal | None = None
    warming_c: float | None = None
    global_warming_c: float | None = None
    deltas: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline.to_dict(),
            "recent": self.recent.to_dict(),
            "projection": self.projection.to_dict() if self.projection else None,
            "warming_c": self.warming_c,
            "global_warming_c": self.global_warming_c,
            "deltas": self.deltas,
        }


def _mean(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _by_year(times: Sequence[str], values: Sequence[float | None]
             ) -> dict[int, list[tuple[date, float]]]:
    """Group a daily series into {year: [(date, value), ...]}, dropping gaps."""
    out: dict[int, list[tuple[date, float]]] = {}
    for t, v in zip(times, values):
        if v is None:
            continue
        d = date.fromisoformat(t)
        out.setdefault(d.year, []).append((d, float(v)))
    return out


def _days_per_year(grouped: dict[int, list[tuple[date, float]]],
                   predicate) -> float | None:
    """Average count of days per year satisfying a predicate.

    Only years with near-complete coverage count; a year missing half its days
    would otherwise drag the average down and look like a trend.
    """
    counts = [sum(1 for _, v in days if predicate(v))
              for days in grouped.values() if len(days) >= 350]
    return sum(counts) / len(counts) if counts else None


def _frost_dates(grouped: dict[int, list[tuple[date, float]]]
                 ) -> tuple[float | None, float | None, float | None]:
    """Mean last-spring-frost, first-autumn-frost, and growing-season length.

    Defined for the northern hemisphere convention: last frost before midsummer,
    first frost after it. Returns (last_frost_doy, first_frost_doy, season_days).
    """
    lasts, firsts, seasons = [], [], []
    for days in grouped.values():
        if len(days) < 350:
            continue
        frosts = [d for d, v in days if v <= FROST_C]
        if not frosts:
            continue
        mid = date(days[0][0].year, 7, 1)
        spring = [d for d in frosts if d < mid]
        autumn = [d for d in frosts if d >= mid]
        if spring and autumn:
            last, first = max(spring), min(autumn)
            lasts.append(last.timetuple().tm_yday)
            firsts.append(first.timetuple().tm_yday)
            seasons.append((first - last).days)
    return (_mean(lasts), _mean(firsts), _mean(seasons))


def normal(daily: dict, start_year: int, end_year: int) -> Normal:
    """Reduce a daily series to one thirty-year normal."""
    times = daily.get("time") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    tmean = daily.get("temperature_2m_mean") or []

    g_max = _by_year(times, tmax)
    g_min = _by_year(times, tmin)

    last_f, first_f, season = _frost_dates(_by_year(times, tmin))

    return Normal(
        start_year=start_year,
        end_year=end_year,
        years_covered=len([y for y, d in g_max.items() if len(d) >= 350]),
        mean_c=_mean(tmean),
        mean_max_c=_mean(tmax),
        mean_min_c=_mean(tmin),
        hot_days=_days_per_year(g_max, lambda v: v >= HOT_C),
        very_hot_days=_days_per_year(g_max, lambda v: v >= VERY_HOT_C),
        warm_nights=_days_per_year(g_min, lambda v: v >= WARM_NIGHT_C),
        frost_days=_days_per_year(g_min, lambda v: v <= FROST_C),
        growing_season_days=season,
        first_frost_doy=first_f,
        last_frost_doy=last_f,
    )


def _delta(a: float | None, b: float | None) -> float | None:
    return None if (a is None or b is None) else b - a


def compare(baseline: Normal, recent: Normal, projection: Normal | None = None,
            global_warming_c: float | None = None) -> Comparison:
    """Baseline vs recent (vs projection), with the deltas spelled out."""
    fields = ["mean_c", "mean_max_c", "mean_min_c", "hot_days", "very_hot_days",
              "warm_nights", "frost_days", "growing_season_days"]
    deltas = {f: _delta(getattr(baseline, f), getattr(recent, f)) for f in fields}
    if projection is not None:
        for f in fields:
            deltas[f"{f}_2050"] = _delta(getattr(baseline, f), getattr(projection, f))
    return Comparison(
        baseline=baseline,
        recent=recent,
        projection=projection,
        warming_c=deltas.get("mean_c"),
        global_warming_c=global_warming_c,
        deltas=deltas,
    )
