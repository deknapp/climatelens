"""The indicators are the product. They are tested against series we build by
hand, so a wrong answer is visible rather than plausible."""

from datetime import date, timedelta

import pytest

from climatelens import indicators


def series(start_year, end_year, tmax_fn, tmin_fn):
    """A complete daily series over whole years, no gaps."""
    times, tmax, tmin, tmean = [], [], [], []
    d = date(start_year, 1, 1)
    while d <= date(end_year, 12, 31):
        times.append(d.isoformat())
        hi, lo = tmax_fn(d), tmin_fn(d)
        tmax.append(hi); tmin.append(lo); tmean.append((hi + lo) / 2)
        d += timedelta(days=1)
    return {"time": times, "temperature_2m_max": tmax,
            "temperature_2m_min": tmin, "temperature_2m_mean": tmean}


def test_constant_series_gives_exact_normal():
    daily = series(1951, 1980, lambda d: 20.0, lambda d: 10.0)
    n = indicators.normal(daily, 1951, 1980)
    assert n.years_covered == 30
    assert n.mean_max_c == pytest.approx(20.0)
    assert n.mean_min_c == pytest.approx(10.0)
    assert n.mean_c == pytest.approx(15.0)
    assert n.hot_days == 0        # 20 C never reaches the 32 C threshold
    assert n.frost_days == 0      # 10 C never reaches freezing


def test_hot_and_frost_day_counts_are_days_per_year():
    # 40 C every July day, -5 C every January night; everything else mild.
    def hi(d): return 40.0 if d.month == 7 else 15.0
    def lo(d): return -5.0 if d.month == 1 else 5.0
    n = indicators.normal(series(1951, 1980, hi, lo), 1951, 1980)
    assert n.hot_days == pytest.approx(31)       # July has 31 days
    assert n.very_hot_days == pytest.approx(31)  # 40 C clears 35 C too
    assert n.frost_days == pytest.approx(31)     # January has 31


def test_warming_shows_up_as_the_delta_between_two_normals():
    base = indicators.normal(series(1951, 1980, lambda d: 20.0, lambda d: 10.0), 1951, 1980)
    recent = indicators.normal(series(1995, 2024, lambda d: 22.0, lambda d: 12.0), 1995, 2024)
    c = indicators.compare(base, recent, global_warming_c=1.28)
    assert c.warming_c == pytest.approx(2.0)
    assert c.deltas["mean_max_c"] == pytest.approx(2.0)
    assert c.global_warming_c == 1.28


def test_incomplete_years_are_excluded_rather_than_averaged_in():
    """A part-year would otherwise look like a downward trend in day counts."""
    daily = series(1951, 1951, lambda d: 40.0, lambda d: 5.0)
    for k in ("time", "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean"):
        daily[k] = daily[k][:100]          # keep only ~3 months
    n = indicators.normal(daily, 1951, 1951)
    assert n.years_covered == 0
    assert n.hot_days is None               # not zero -- unknown


def test_growing_season_is_last_spring_frost_to_first_autumn_frost():
    # Frost in January and December only -> a long season between them.
    def lo(d): return -2.0 if d.month in (1, 12) else 8.0
    n = indicators.normal(series(1951, 1980, lambda d: 20.0, lo), 1951, 1980)
    assert n.last_frost_doy == pytest.approx(31)    # 31 Jan
    assert n.first_frost_doy == pytest.approx(335, abs=1)  # 1 Dec
    assert n.growing_season_days == pytest.approx(304, abs=1)


def test_missing_values_are_dropped_not_treated_as_zero():
    daily = series(1951, 1980, lambda d: 20.0, lambda d: 10.0)
    daily["temperature_2m_max"][0] = None
    n = indicators.normal(daily, 1951, 1980)
    assert n.mean_max_c == pytest.approx(20.0)   # a zero would drag this down


def test_nulls_propagate_rather_than_inventing_a_delta():
    empty = indicators.normal({"time": [], "temperature_2m_max": [],
                               "temperature_2m_min": [], "temperature_2m_mean": []}, 1951, 1980)
    real = indicators.normal(series(1995, 2024, lambda d: 22.0, lambda d: 12.0), 1995, 2024)
    c = indicators.compare(empty, real)
    assert c.warming_c is None
    assert c.deltas["hot_days"] is None


def test_projection_delta_cancels_model_bias():
    """A model running 3 C warm than reanalysis but with 2 C of warming must
    report 2 C, not 5 C. This is the delta-change method."""
    obs_base = indicators.normal(series(1951, 1980, lambda d: 20.0, lambda d: 10.0), 1951, 1980)
    obs_recent = indicators.normal(series(1995, 2024, lambda d: 21.0, lambda d: 11.0), 1995, 2024)
    # Same model, both windows, carrying a +3 C warm bias throughout.
    mod_base = indicators.normal(series(1951, 1980, lambda d: 23.0, lambda d: 13.0), 1951, 1980)
    mod_future = indicators.normal(series(2040, 2049, lambda d: 25.0, lambda d: 15.0), 2040, 2049)

    c = indicators.compare(obs_base, obs_recent, mod_future,
                           projection_baseline=mod_base)
    assert c.deltas["mean_c"] == pytest.approx(1.0)        # observed warming
    assert c.deltas["mean_c_2050"] == pytest.approx(2.0)   # bias cancelled


def test_projection_delta_is_withheld_without_a_model_baseline():
    """No model baseline means we cannot debias, so we report nothing."""
    obs_base = indicators.normal(series(1951, 1980, lambda d: 20.0, lambda d: 10.0), 1951, 1980)
    obs_recent = indicators.normal(series(1995, 2024, lambda d: 21.0, lambda d: 11.0), 1995, 2024)
    mod_future = indicators.normal(series(2040, 2049, lambda d: 25.0, lambda d: 15.0), 2040, 2049)
    c = indicators.compare(obs_base, obs_recent, mod_future)
    assert "mean_c_2050" not in c.deltas


def test_southern_hemisphere_growing_season_is_withheld_not_reversed():
    """Below the equator the season straddles the new year, so the northern
    convention would return a season running backwards. Report nothing."""
    def lo(d): return -2.0 if d.month in (6, 7) else 8.0   # austral winter frost
    daily = series(1951, 1980, lambda d: 20.0, lo)
    south = indicators.normal(daily, 1951, 1980, latitude=-33.9)   # Sydney
    assert south.growing_season_days is None
    assert south.first_frost_doy is None
    assert south.frost_days is not None      # frost counts are still valid

    north = indicators.normal(daily, 1951, 1980, latitude=40.7)    # New York
    assert north.growing_season_days is not None


# --- the interval on the headline number ----------------------------------

def test_warming_interval_brackets_the_point_estimate():
    base = indicators.Normal(1951, 1980, 30, annual_means=[10.0 + (i % 5) * 0.2
                                                           for i in range(30)])
    recent = indicators.Normal(1995, 2024, 30, annual_means=[11.0 + (i % 5) * 0.2
                                                             for i in range(30)])
    lo, hi = indicators.warming_interval(base, recent, resamples=2000)
    assert lo < 1.0 < hi


def test_a_noisier_record_gets_a_wider_interval():
    """The interval has to respond to variability, or it is decoration."""
    quiet_b = indicators.Normal(1951, 1980, 30, annual_means=[10.0] * 30)
    quiet_r = indicators.Normal(1995, 2024, 30, annual_means=[11.0] * 30)
    noisy_b = indicators.Normal(1951, 1980, 30,
                                annual_means=[10.0 + (3.0 if i % 2 else -3.0)
                                              for i in range(30)])
    noisy_r = indicators.Normal(1995, 2024, 30,
                                annual_means=[11.0 + (3.0 if i % 2 else -3.0)
                                              for i in range(30)])
    q = indicators.warming_interval(quiet_b, quiet_r, resamples=2000)
    n = indicators.warming_interval(noisy_b, noisy_r, resamples=2000)
    assert (q[1] - q[0]) == 0.0          # no variability, no interval
    assert (n[1] - n[0]) > 1.0


def test_no_interval_without_enough_years():
    thin = indicators.Normal(2020, 2024, 5, annual_means=[10.0] * 5)
    full = indicators.Normal(1995, 2024, 30, annual_means=[11.0] * 30)
    assert indicators.warming_interval(thin, full) is None


def test_interval_is_reproducible():
    """A seeded bootstrap, so reloading a page does not move the number."""
    b = indicators.Normal(1951, 1980, 30, annual_means=[10.0 + i * 0.05 for i in range(30)])
    r = indicators.Normal(1995, 2024, 30, annual_means=[11.0 + i * 0.05 for i in range(30)])
    assert indicators.warming_interval(b, r) == indicators.warming_interval(b, r)
