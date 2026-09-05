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

import random
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
    # One mean per year in the window. Kept because the headline number is a
    # difference of two thirty-year means, and thirty is a small enough sample
    # that the difference deserves an interval around it.
    annual_means: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        # The annual series is an input to the interval, not a figure anyone
        # reads, and it would triple the size of every response.
        return {k: v for k, v in self.__dict__.items() if k != "annual_means"}


@dataclass
class Comparison:
    """Baseline vs recent, plus the deltas that are the actual story."""

    baseline: Normal
    recent: Normal
    projection: Normal | None = None
    warming_c: float | None = None
    warming_ci: tuple[float, float] | None = None
    global_warming_c: float | None = None
    deltas: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline.to_dict(),
            "recent": self.recent.to_dict(),
            "projection": self.projection.to_dict() if self.projection else None,
            "warming_c": self.warming_c,
            "warming_ci": list(self.warming_ci) if self.warming_ci else None,
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


def _frost_dates(grouped: dict[int, list[tuple[date, float]]],
                 southern: bool = False
                 ) -> tuple[float | None, float | None, float | None]:
    """Mean last-spring-frost, first-autumn-frost, and growing-season length.

    This uses the northern-hemisphere convention -- last frost before midsummer,
    first frost after it -- which is only meaningful when the growing season sits
    inside one calendar year. South of the equator it straddles the new year, so
    the same arithmetic would return a season running backwards. Rather than
    report a wrong number we return nothing there; see the module docstring on
    why an absent number beats a plausible one.

    Returns (last_frost_doy, first_frost_doy, season_days).
    """
    if southern:
        return (None, None, None)
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


def normal(daily: dict, start_year: int, end_year: int,
           latitude: float | None = None) -> Normal:
    """Reduce a daily series to one thirty-year normal.

    `latitude` is needed only to know which hemisphere's growing-season
    convention applies; every other indicator is latitude-independent.
    """
    times = daily.get("time") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    tmean = daily.get("temperature_2m_mean") or []

    g_max = _by_year(times, tmax)
    g_min = _by_year(times, tmin)
    g_mean = _by_year(times, tmean)

    southern = latitude is not None and latitude < 0
    last_f, first_f, season = _frost_dates(_by_year(times, tmin), southern)

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
        annual_means=[sum(v for _, v in days) / len(days)
                      for _, days in sorted(g_mean.items())
                      if len(days) >= 350],
    )


BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20260905  # fixed, so the same place reloads to the same interval


def warming_interval(baseline: Normal, recent: Normal, *,
                     confidence: float = 0.95,
                     resamples: int = BOOTSTRAP_RESAMPLES
                     ) -> tuple[float, float] | None:
    """A 95% interval on the headline warming number, by bootstrap.

    The headline is a difference between two thirty-year means, and thirty is
    a small sample. Reporting it as a bare point estimate implies a precision
    the record does not carry, next to an ENSO panel that puts a p-value on
    everything -- so it gets an interval, computed the same dependency-free
    way: resample each window's annual means with replacement, recompute the
    difference, and read the percentiles off the resulting distribution.

    What this covers is the year-to-year variability of the two windows. It
    does NOT cover ERA5's own observational uncertainty, and it treats the
    warming trend inside each window as though it were noise, which widens the
    interval slightly. Both directions are stated on the page rather than
    buried here.
    """
    a, b = baseline.annual_means, recent.annual_means
    if len(a) < 10 or len(b) < 10:
        return None

    rng = random.Random(BOOTSTRAP_SEED)
    na, nb = len(a), len(b)
    diffs = []
    for _ in range(resamples):
        sa = sum(a[rng.randrange(na)] for _ in range(na)) / na
        sb = sum(b[rng.randrange(nb)] for _ in range(nb)) / nb
        diffs.append(sb - sa)
    diffs.sort()

    tail = (1.0 - confidence) / 2.0
    lo = diffs[max(0, int(tail * resamples) - 1)]
    hi = diffs[min(resamples - 1, int((1.0 - tail) * resamples))]
    return (lo, hi)


def _delta(a: float | None, b: float | None) -> float | None:
    return None if (a is None or b is None) else b - a


def compare(baseline: Normal, recent: Normal, projection: Normal | None = None,
            global_warming_c: float | None = None,
            projection_baseline: Normal | None = None) -> Comparison:
    """Baseline vs recent (vs projection), with the deltas spelled out.

    The projection deltas need care. A climate model's *absolute* temperature
    carries its own systematic bias, so subtracting an ERA5 baseline from a
    CMIP6 future would report that bias as though it were warming. The standard
    fix is the delta-change method: take the model's future minus the *model's
    own* baseline, so the bias cancels.

    `projection_baseline` is that model baseline. Without it, no projection
    delta is reported at all -- an absent number beats a wrong one.
    """
    fields = ["mean_c", "mean_max_c", "mean_min_c", "hot_days", "very_hot_days",
              "warm_nights", "frost_days", "growing_season_days"]
    deltas = {f: _delta(getattr(baseline, f), getattr(recent, f)) for f in fields}
    if projection is not None and projection_baseline is not None:
        for f in fields:
            deltas[f"{f}_2050"] = _delta(getattr(projection_baseline, f),
                                         getattr(projection, f))
    return Comparison(
        baseline=baseline,
        recent=recent,
        projection=projection,
        warming_c=deltas.get("mean_c"),
        warming_ci=warming_interval(baseline, recent),
        global_warming_c=global_warming_c,
        deltas=deltas,
    )
