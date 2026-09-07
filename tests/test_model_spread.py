"""Tests for the multi-model projection spread.

A single model's projection is a number with no error bar, and it reads as far
more certain than it is. Reporting five models turns it into a range — but only
if the arithmetic is right, and there are two ways to get it quietly wrong:

* differencing one model's future against another's baseline, which reports the
  difference between models as warming;
* returning no spread at all when something is missing, which looks exactly
  like the models agreeing.

Both have a test here. The second one is not hypothetical — an earlier version
of this code read a misnamed field inside a `try: except AttributeError`, and
would have silently reported no disagreement forever.
"""

from __future__ import annotations

from climatelens.api import _model_spread
from climatelens.indicators import Normal


def normal(mean_c, start=2040, end=2049):
    return Normal(start_year=start, end_year=end, years_covered=end - start + 1,
                  mean_c=mean_c)


def pair(future_c, baseline_c):
    """(projection, baseline) for one model."""
    return (normal(future_c), normal(baseline_c, 1951, 1980))


# ------------------------------------------------------------- arithmetic


def test_each_model_is_differenced_against_its_own_baseline():
    """The bias-cancelling property the whole delta-change method rests on.

    Model A runs 5 degrees warm in absolute terms and model B runs 5 cold. Both
    warm by exactly 2. The spread must be zero-width, not ten degrees.
    """
    spread = _model_spread({
        "warm_biased": pair(22.0, 20.0),
        "cold_biased": pair(12.0, 10.0),
    })

    assert spread["warming_c_low"] == 2.0
    assert spread["warming_c_high"] == 2.0
    assert spread["warming_c_median"] == 2.0


def test_the_range_covers_the_models():
    spread = _model_spread({
        "a": pair(12.0, 10.0),   # +2.0
        "b": pair(13.5, 10.0),   # +3.5
        "c": pair(12.8, 10.0),   # +2.8
    })

    assert spread["warming_c_low"] == 2.0
    assert spread["warming_c_high"] == 3.5
    assert spread["warming_c_median"] == 2.8
    assert spread["n_models"] == 3


def test_the_median_of_an_even_count_is_the_midpoint():
    spread = _model_spread({
        "a": pair(12.0, 10.0),   # +2
        "b": pair(14.0, 10.0),   # +4
    })
    assert spread["warming_c_median"] == 3.0


def test_every_model_is_reported_individually():
    """A reader must be able to see which model said what."""
    spread = _model_spread({"a": pair(12.0, 10.0), "b": pair(13.0, 10.0)})
    assert spread["warming_c_by_model"] == {"a": 2.0, "b": 3.0}
    assert spread["models"] == ["a", "b"]


# -------------------------------------------------------------- agreement


def test_agreement_says_so_when_every_model_warms():
    spread = _model_spread({"a": pair(12.0, 10.0), "b": pair(13.0, 10.0)})
    assert spread["agreement"] == "all models warm"


def test_agreement_flags_a_disagreement_on_sign():
    """Where models disagree about direction, that is the finding."""
    spread = _model_spread({"a": pair(12.0, 10.0), "b": pair(9.5, 10.0)})
    assert spread["agreement"] == "models disagree on sign"


def test_agreement_says_so_when_every_model_cools():
    spread = _model_spread({"a": pair(9.0, 10.0), "b": pair(9.5, 10.0)})
    assert spread["agreement"] == "all models cool"


# ------------------------------------------------------- missing data


def test_a_model_with_no_mean_is_excluded_rather_than_counted_as_zero():
    spread = _model_spread({
        "good_a": pair(12.0, 10.0),
        "good_b": pair(13.0, 10.0),
        "broken": (normal(None), normal(10.0, 1951, 1980)),
    })

    assert spread["n_models"] == 2
    assert "broken" not in spread["warming_c_by_model"]


def test_a_missing_baseline_also_excludes_the_model():
    spread = _model_spread({
        "good_a": pair(12.0, 10.0),
        "good_b": pair(13.0, 10.0),
        "no_baseline": (normal(12.0), normal(None, 1951, 1980)),
    })
    assert spread["n_models"] == 2


def test_fewer_than_two_usable_models_reports_no_spread():
    """One model is not a spread, and pretending otherwise implies agreement."""
    assert _model_spread({"only": pair(12.0, 10.0)}) is None
    assert _model_spread({}) is None


def test_a_real_field_name_is_used():
    """Regression: this read `mean_temp_c`, which does not exist.

    The failure was invisible because the lookup sat inside an
    `except AttributeError: continue`, so every model was skipped and the
    function returned None — indistinguishable from a location where the
    models happened to agree.
    """
    spread = _model_spread({"a": pair(12.0, 10.0), "b": pair(13.0, 10.0)})
    assert spread is not None, "spread silently vanished; check the field name"
    assert spread["n_models"] == 2
