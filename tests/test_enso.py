"""Tests for the ENSO composite.

These are all offline. The point of the module is arithmetic on a table and a
daily series, so the tests hand it made-up tables and series whose right answer
is known in advance. The most important test in here is the detrending one:
that is the step that separates a real ENSO signal from the warming trend, and
it is the step that would fail silently if it broke.
"""

from __future__ import annotations

from datetime import date, timedelta

from climatelens import enso


def oni_row(season: str, year: int, anomaly: float) -> dict:
    return {"season": season, "year": year, "anomaly": anomaly}


def test_classify_uses_noaa_thresholds():
    assert enso.classify(0.5) == "el_nino"
    assert enso.classify(0.49) == "neutral"
    assert enso.classify(-0.5) == "la_nina"
    assert enso.classify(-0.49) == "neutral"
    assert enso.classify(None) == "unknown"


def test_strength_buckets():
    assert enso.strength(0.3) == "neutral"
    assert enso.strength(0.7) == "weak"
    assert enso.strength(1.2) == "moderate"
    assert enso.strength(1.7) == "strong"
    assert enso.strength(2.4) == "very strong"
    # La Nina is bucketed on magnitude, so the labels are symmetric.
    assert enso.strength(-1.7) == "strong"


def test_winters_takes_djf_only_and_keys_on_january():
    oni = [oni_row("NDJ", 1998, 2.2), oni_row("DJF", 1998, 2.4),
           oni_row("JFM", 1998, 2.0), oni_row("DJF", 1999, -1.4)]
    w = enso.winters(oni)
    assert set(w) == {1998, 1999}
    assert w[1998].state == "el_nino"
    assert w[1998].strength == "very strong"
    assert w[1999].state == "la_nina"


def daily_from(values: dict[int, tuple[float, float]]) -> dict:
    """Build a daily series where each winter has a known mean temp and total precip.

    Winter Y is Dec of Y-1 plus Jan and Feb of Y, which is exactly the boundary
    the bucketing has to get right.
    """
    times, temps, precip = [], [], []
    for winter, (temp, precip_per_day) in sorted(values.items()):
        day = date(winter - 1, 12, 1)
        end = date(winter, 3, 1)
        while day < end:
            times.append(day.isoformat())
            temps.append(temp)
            precip.append(precip_per_day)
            day += timedelta(days=1)
    return {"time": times, "temperature_2m_mean": temps, "precipitation_sum": precip}


def test_winter_series_buckets_december_into_the_following_winter():
    daily = daily_from({2000: (5.0, 1.0), 2001: (7.0, 2.0)})
    series = enso.winter_series(daily)
    assert set(series) == {2000, 2001}
    assert series[2000]["temp_c"] == 5.0
    assert series[2001]["temp_c"] == 7.0
    # 90 or 91 days of 1 mm, depending on the leap year.
    assert 89 <= series[2000]["precip_mm"] <= 92


def test_partial_winters_are_dropped_not_averaged():
    daily = daily_from({2000: (5.0, 1.0)})
    # Keep only January: a third of a winter must not count as one.
    keep = [i for i, t in enumerate(daily["time"]) if t.startswith("2000-01")]
    trimmed = {k: [v[i] for i in keep] for k, v in daily.items()}
    assert enso.winter_series(trimmed) == {}


def test_composite_removes_the_warming_trend():
    """A pure trend with no ENSO signal must composite to about zero.

    This is the failure the detrending exists to prevent. The El Nino winters
    here are deliberately stacked into the recent half of the record and given
    no ENSO signal at all -- only the trend. Composited raw they would look
    like a full degree of warming caused by El Nino; against the fitted trend
    they are nothing, which is the truth.
    """
    warming_per_year = 0.04
    values = {year: warming_per_year * year for year in range(1950, 2025)}
    late_years = [y for y in range(1995, 2025, 2)]

    stat = enso._composite("t", "C", values, late_years)
    assert abs(stat.anomaly) < 1e-6

    # What the naive version would have reported instead: most of a degree of
    # warming, misattributed to El Nino.
    raw = (sum(values[y] for y in late_years) / len(late_years)
           - sum(values.values()) / len(values))
    assert raw > 0.8


def test_composite_finds_a_real_signal_and_counts_hits():
    values = {}
    selected = []
    for i, year in enumerate(range(1950, 2025)):
        is_event = i % 3 == 0
        values[year] = 10.0 + (2.0 if is_event else 0.0)
        if is_event:
            selected.append(year)
    stat = enso._composite("t", "C", values, selected)
    assert stat.anomaly > 1.0
    assert stat.hits == stat.n          # every event on the same side
    assert stat.hit_rate == 1.0
    assert stat.p_value < 0.01


def test_permutation_p_is_high_when_the_groups_are_the_same():
    a = [1.0, -1.0, 0.5, -0.5, 0.2, -0.2, 0.8, -0.8]
    b = [0.9, -0.9, 0.4, -0.4, 0.1, -0.1, 0.7, -0.7]
    assert enso._permutation_p(a, b, permutations=2000) > 0.5


def test_permutation_p_is_never_zero_and_never_above_one():
    p = enso._permutation_p([10.0] * 8, [-10.0] * 8, permutations=2000)
    assert 0 < p <= 1


def test_permutation_p_declines_to_judge_tiny_groups():
    assert enso._permutation_p([1.0, 2.0], [5.0, 6.0]) is None


def test_composite_reports_n_but_no_statistics_when_too_few_winters():
    stat = enso._composite("t", "C", {2000: 1.0, 2001: 2.0}, [2000])
    assert stat.n == 1
    assert stat.anomaly is None
    assert stat.p_value is None


def test_current_state_reports_direction_and_run():
    oni = [oni_row("MAM", 2026, -0.4), oni_row("AMJ", 2026, 0.2),
           oni_row("MJJ", 2026, 0.9), oni_row("JJA", 2026, 1.8)]
    cur = enso.current_state(oni)
    assert cur["state"] == "el_nino"
    assert cur["strength"] == "strong"
    assert cur["direction"] == "strengthening"
    assert cur["seasons_at_this_state"] == 2  # MJJ and JJA are at threshold


def test_peak_season_note_requires_five_consecutive_seasons():
    # A three-season blip is not an event and must not be counted as one.
    blip = [oni_row(s, 2000, 0.8) for s in ("MAM", "AMJ", "MJJ")]
    assert enso._peak_season_note(blip)["events"] == 0

    seasons = ("JJA", "JAS", "ASO", "SON", "OND", "NDJ")
    event = [oni_row(s, 2000, 0.8 + (0.9 if s == "NDJ" else 0)) for s in seasons]
    note = enso._peak_season_note(event)
    assert note["events"] == 1
    assert note["peaks_by_season"][0][0] == "NDJ"
    assert note["winter_peaks"] == 1


def test_report_holds_together_on_a_synthetic_record():
    oni, values = [], {}
    for year in range(1950, 2025):
        anomaly = 1.6 if year % 4 == 0 else 0.0
        oni.append(oni_row("DJF", year, anomaly))
        values[year] = (2.0, 3.0) if anomaly else (5.0, 1.0)
    rep = enso.report(oni, daily_from(values))
    assert rep.winters_used > 60
    assert rep.counts["el_nino"] == rep.counts["strong_el_nino"] > 0
    nino = rep.composites["el_nino"]["temperature"]
    assert nino.anomaly < -2.0        # events are the cold ones here
    assert nino.hit_rate == 1.0
    assert rep.composites["el_nino"]["precipitation"].percent_of_normal > 100
