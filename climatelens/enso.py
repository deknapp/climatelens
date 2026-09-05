"""El Nino and La Nina, for one place.

The question this module answers is the one people actually ask and almost
never get a local answer to: *an El Nino is underway -- what does that mean
where I live?* The usual answer is a continental map with a few arrows on it.
This computes the answer from the record instead.

The method is a composite, which is the standard way the question is asked of
data:

  1. NOAA's Oceanic Nino Index says which winters since 1950 were El Nino,
     which were La Nina, and which were neutral.
  2. ERA5 says what that winter was actually like at this exact point.
  3. Average the El Nino winters, average the rest, and look at the gap.

Three things keep this honest, and all three matter:

  * **Detrending.** El Nino winters are not spread evenly through the record,
    and the climate warmed underneath the whole thing. Without removing the
    warming trend first, a composite of recent-leaning events reports global
    warming as though it were an ENSO signal. Every anomaly here is measured
    against the fitted trend line, not against the raw mean.
  * **A hit rate, not just a mean.** One winter is coming, not twenty. The
    average shift matters far less than how often events actually landed on
    that side. Eleven of twenty is a coin flip however large the mean.
  * **A permutation test.** With twenty-odd events, a composite difference can
    look convincing and mean nothing. Shuffling the labels thousands of times
    and counting how often chance does as well is the cheapest honest check,
    and it needs no distribution tables and no dependencies.

Nothing in this module performs I/O and nothing asks a language model
anything. It is handed the ONI table and a daily series, and it returns
numbers.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Sequence

# NOAA's thresholds for the Oceanic Nino Index, in degrees C of sea-surface
# temperature anomaly in the Nino 3.4 region.
EL_NINO_C = 0.5
LA_NINA_C = -0.5

# A "strong" event. The composite is computed for these separately: a strong
# event is not just a bigger version of a weak one, and if a strong El Nino is
# building, weak events are the wrong comparison set.
STRONG_C = 1.5

# The three-month season used to name and rank events. ENSO peaks in northern
# winter and its effect on weather away from the tropics peaks with it.
PEAK_SEASON = "DJF"

# Dec + Jan + Feb. A winter is allowed to be a few days short of this -- ERA5
# has no real gaps, but a truncated final winter must not be silently averaged
# in as though it were whole.
WINTER_DAYS = 90
MIN_WINTER_DAYS = 85

PERMUTATIONS = 10_000
SEED = 20260905  # fixed, so the same page reloads to the same p-value


@dataclass
class Event:
    """One winter, classified."""

    year: int
    anomaly: float
    state: str
    strength: str


@dataclass
class CompositeStat:
    """What one group of winters did to one variable, against the trend."""

    variable: str
    unit: str
    n: int
    anomaly: float | None = None
    spread: float | None = None
    hit_rate: float | None = None
    hits: int | None = None
    normal: float | None = None
    percent_of_normal: float | None = None
    p_value: float | None = None

    def to_dict(self) -> dict:
        return dict(asdict(self))


@dataclass
class EnsoReport:
    current: dict = field(default_factory=dict)
    winters_used: int = 0
    first_winter: int | None = None
    last_winter: int | None = None
    counts: dict = field(default_factory=dict)
    composites: dict = field(default_factory=dict)
    trend_c_per_decade: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "current": self.current,
            "winters_used": self.winters_used,
            "first_winter": self.first_winter,
            "last_winter": self.last_winter,
            "counts": self.counts,
            "composites": {
                group: {name: stat.to_dict() for name, stat in stats.items()}
                for group, stats in self.composites.items()
            },
            "trend_c_per_decade": self.trend_c_per_decade,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------
# Classifying the ocean
# --------------------------------------------------------------------------

def classify(anomaly: float | None) -> str:
    if anomaly is None:
        return "unknown"
    if anomaly >= EL_NINO_C:
        return "el_nino"
    if anomaly <= LA_NINA_C:
        return "la_nina"
    return "neutral"


def strength(anomaly: float | None) -> str:
    """NOAA's usual verbal buckets, applied to the absolute anomaly."""
    if anomaly is None:
        return "unknown"
    a = abs(anomaly)
    if a < EL_NINO_C:
        return "neutral"
    if a < 1.0:
        return "weak"
    if a < STRONG_C:
        return "moderate"
    if a < 2.0:
        return "strong"
    return "very strong"


def winters(oni: Sequence[dict]) -> dict[int, Event]:
    """One entry per winter, keyed by the year of its January.

    The DJF row of the index *is* the winter: NOAA labels it with the year its
    January falls in, which is why the 1998 El Nino is called that even though
    it began in 1997.
    """
    out: dict[int, Event] = {}
    for row in oni:
        if row.get("season") != PEAK_SEASON:
            continue
        anomaly = float(row["anomaly"])
        out[int(row["year"])] = Event(
            year=int(row["year"]),
            anomaly=anomaly,
            state=classify(anomaly),
            strength=strength(anomaly),
        )
    return out


def current_state(oni: Sequence[dict], *, recent: int = 12) -> dict:
    """Where the ocean is right now, straight off the end of the index.

    This deliberately reports rather than predicts. It says what the most
    recent observed season was and which way the last few have moved. Whether
    the coming winter is an El Nino winter is not yet an observed fact, and
    this app does not assert things that are not.
    """
    if not oni:
        return {}
    tail = list(oni)[-recent:]
    latest = tail[-1]
    anomaly = float(latest["anomaly"])

    # Rising or falling, measured over the last three seasons of the index.
    direction = None
    if len(tail) >= 4:
        change = anomaly - float(tail[-4]["anomaly"])
        if abs(change) < 0.15:
            direction = "steady"
        else:
            direction = "strengthening" if change > 0 else "weakening"

    # How many seasons the current sign has held, at threshold.
    state = classify(anomaly)
    run = 0
    for row in reversed(oni):
        if classify(float(row["anomaly"])) != state:
            break
        run += 1

    return {
        "season": latest["season"],
        "year": int(latest["year"]),
        "anomaly": anomaly,
        "state": state,
        "strength": strength(anomaly),
        "direction": direction,
        "seasons_at_this_state": run,
        "recent": [
            {"season": r["season"], "year": int(r["year"]),
             "anomaly": float(r["anomaly"])} for r in tail
        ],
        "peak_season_note": _peak_season_note(oni),
    }


def _peak_season_note(oni: Sequence[dict]) -> dict:
    """Which season past El Nino events actually peaked in -- computed, not recalled.

    Events are contiguous runs of seasons at or above the threshold; for each
    run we take the season holding its maximum. The point is to say *when* a
    building event would be expected to matter, from the record itself.
    """
    peaks: dict[str, int] = {}
    run: list[dict] = []
    total = 0
    for row in list(oni) + [{"season": "", "year": 0, "anomaly": -99.0}]:
        if float(row["anomaly"]) >= EL_NINO_C:
            run.append(row)
            continue
        if len(run) >= 5:  # NOAA requires five consecutive seasons for an event
            best = max(run, key=lambda r: float(r["anomaly"]))
            peaks[best["season"]] = peaks.get(best["season"], 0) + 1
            total += 1
        run = []
    ordered = sorted(peaks.items(), key=lambda kv: -kv[1])
    return {"events": total, "peaks_by_season": ordered,
            "winter_peaks": sum(n for s, n in peaks.items()
                                if s in ("OND", "NDJ", "DJF", "JFM"))}


# --------------------------------------------------------------------------
# What the winter was actually like here
# --------------------------------------------------------------------------

def winter_series(daily: dict) -> dict[int, dict]:
    """Collapse a daily series into one record per DJF winter.

    A winter is December of the previous year plus January and February of the
    named year, so that the three months are contiguous in time rather than
    split across a calendar boundary.
    """
    times = daily.get("time") or []
    temps = daily.get("temperature_2m_mean") or []
    precip = daily.get("precipitation_sum") or []

    buckets: dict[int, dict[str, list[float]]] = {}
    for i, stamp in enumerate(times):
        try:
            day = date.fromisoformat(stamp)
        except (TypeError, ValueError):
            continue
        if day.month == 12:
            winter = day.year + 1
        elif day.month in (1, 2):
            winter = day.year
        else:
            continue
        bucket = buckets.setdefault(winter, {"t": [], "p": [], "days": []})
        bucket["days"].append(1.0)
        t = temps[i] if i < len(temps) else None
        p = precip[i] if i < len(precip) else None
        if t is not None:
            bucket["t"].append(float(t))
        if p is not None:
            bucket["p"].append(float(p))

    out: dict[int, dict] = {}
    for winter, bucket in buckets.items():
        days = len(bucket["days"])
        if days < MIN_WINTER_DAYS:
            continue  # a partial winter is not a winter
        record: dict = {"days": days}
        if len(bucket["t"]) >= MIN_WINTER_DAYS:
            record["temp_c"] = sum(bucket["t"]) / len(bucket["t"])
        if len(bucket["p"]) >= MIN_WINTER_DAYS:
            record["precip_mm"] = sum(bucket["p"])
        out[winter] = record
    return out


def _linfit(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    """Least-squares slope and intercept. Slope is zero if x never varies."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0, my
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    return slope, my - slope * mx


def _stdev(values: Sequence[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    return (sum((v - mean) ** 2 for v in values) / (n - 1)) ** 0.5


def _permutation_p(group: Sequence[float], rest: Sequence[float],
                   *, permutations: int = PERMUTATIONS) -> float | None:
    """Two-sided p for the gap between two groups, by shuffling the labels.

    No distribution assumed and no dependency needed: pool the values, deal
    them back out at random many times, and count how often chance produces a
    gap at least as large as the one observed.
    """
    if len(group) < 3 or len(rest) < 3:
        return None
    observed = abs(sum(group) / len(group) - sum(rest) / len(rest))
    pool = list(group) + list(rest)
    k = len(group)
    rng = random.Random(SEED)
    at_least = 0
    for _ in range(permutations):
        rng.shuffle(pool)
        a = pool[:k]
        b = pool[k:]
        if abs(sum(a) / k - sum(b) / len(b)) >= observed - 1e-12:
            at_least += 1
    # The observed arrangement is itself one of the possibilities, which is why
    # both counts start at one -- it keeps p from ever being reported as zero.
    return (at_least + 1) / (permutations + 1)


def _composite(variable: str, unit: str, values: dict[int, float],
               selected: Sequence[int], *, percent: bool = False) -> CompositeStat:
    """Detrend every winter, then describe the selected ones against the rest."""
    years = sorted(values)
    if len(years) < 10 or not selected:
        return CompositeStat(variable=variable, unit=unit, n=len(selected))

    slope, intercept = _linfit([float(y) for y in years], [values[y] for y in years])
    residual = {y: values[y] - (intercept + slope * y) for y in years}

    inside = [residual[y] for y in selected if y in residual]
    outside = [residual[y] for y in years if y not in set(selected)]
    if len(inside) < 3:
        return CompositeStat(variable=variable, unit=unit, n=len(inside))

    anomaly = sum(inside) / len(inside)
    hits = sum(1 for r in inside if (r > 0) == (anomaly > 0) and r != 0)
    normal = sum(values[y] for y in years) / len(years)

    stat = CompositeStat(
        variable=variable,
        unit=unit,
        n=len(inside),
        anomaly=anomaly,
        spread=_stdev(inside),
        hits=hits,
        hit_rate=hits / len(inside),
        normal=normal,
        p_value=_permutation_p(inside, outside),
    )
    if percent and normal:
        stat.percent_of_normal = 100.0 * (normal + anomaly) / normal
    return stat


def report(oni: Sequence[dict], daily: dict) -> EnsoReport:
    """The whole ENSO picture for one point: where the ocean is, what it has meant here."""
    events = winters(oni)
    series = winter_series(daily)

    usable = sorted(set(events) & set(series))
    temps = {y: series[y]["temp_c"] for y in usable if "temp_c" in series[y]}
    precips = {y: series[y]["precip_mm"] for y in usable if "precip_mm" in series[y]}

    groups = {
        "el_nino": [y for y in usable if events[y].state == "el_nino"],
        "la_nina": [y for y in usable if events[y].state == "la_nina"],
        "neutral": [y for y in usable if events[y].state == "neutral"],
        "strong_el_nino": [y for y in usable
                           if events[y].anomaly >= STRONG_C],
    }

    composites: dict[str, dict[str, CompositeStat]] = {}
    for name, years in groups.items():
        composites[name] = {
            "temperature": _composite("winter mean temperature", "C", temps, years),
            "precipitation": _composite("winter total precipitation", "mm", precips,
                                        years, percent=True),
        }

    trend = None
    if len(temps) >= 10:
        slope, _ = _linfit([float(y) for y in sorted(temps)],
                           [temps[y] for y in sorted(temps)])
        trend = slope * 10

    notes = [
        "A winter here is December, January and February, named for the year "
        "its January falls in -- NOAA's convention.",
        "Every anomaly is measured against the fitted linear trend across all "
        "winters, so the warming trend is not double-counted as an ENSO signal.",
        "The hit rate is what matters for one coming winter. A large average "
        "shift that only half the events shared is not a useful expectation.",
        "ERA5 precipitation is a model-assimilated field, not a rain gauge. Its "
        "totals are less trustworthy than its temperatures, especially in "
        "mountainous terrain.",
    ]

    return EnsoReport(
        current=current_state(oni),
        winters_used=len(usable),
        first_winter=usable[0] if usable else None,
        last_winter=usable[-1] if usable else None,
        counts={name: len(years) for name, years in groups.items()},
        composites=composites,
        trend_c_per_decade=trend,
        notes=notes,
    )
