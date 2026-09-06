"""The eval harness's own checker, tested offline.

`evals/` needs a live API key and costs money, so CI cannot run it. But the
part of it that decides whether a number is a hallucination is pure arithmetic,
and if *that* is wrong the harness is worse than useless -- it would report a
clean bill of health on invented figures. So it is tested here, in the suite
that does run on every push.

The two cases at the bottom are regressions for real bugs in earlier versions
of the checker, both of which made it pass fabricated numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.numbers import Mention, Traceability, extract, vocabulary_for

FIXTURE = Path(__file__).parent.parent / "evals" / "fixtures" / "santa-fe.json"


@pytest.fixture(scope="module")
def payload() -> dict:
    if not FIXTURE.exists():
        pytest.skip("fixtures not captured; run python -m evals.capture_fixtures")
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def trace(payload: dict) -> Traceability:
    return Traceability(payload)


def test_extracts_digits_and_words():
    found = {m.text for m in extract("It warmed 1.7 C over thirty years, 17 of 25 winters.")}
    assert {"1.7", "thirty", "17", "25"} <= found


def test_extracts_thousands_separator():
    assert any(m.value == 2194.0 for m in extract("The city sits at 2,194 metres."))


def test_does_not_read_numbers_out_of_words():
    # "COVID19" or "ERA5" are names, not measurements.
    assert extract("ERA5 reanalysis, CMIP6 projection") == []


def test_headline_number_is_supported(trace: Traceability, payload: dict):
    warming = payload["comparison"]["warming_c"]
    assert trace.supported(Mention(round(warming, 1), str(round(warming, 1)),
                                   "warmed by that much"))


def test_rounded_and_truncated_forms_are_supported(trace: Traceability, payload: dict):
    frost = abs(payload["comparison"]["deltas"]["frost_days"])   # 19.47
    for form in (round(frost, 1), float(int(frost)), round(frost)):
        assert trace.supported(Mention(form, str(form), "fewer frost days a year")), form


def test_prompt_constants_are_supported(trace: Traceability):
    for value, context in ((95.0, "a 95% interval"), (25.0, "a 25 km grid"),
                           (32.0, "days above 32 C")):
        assert trace.supported(Mention(value, str(value), context))


def test_years_near_the_named_periods_are_supported(trace: Traceability):
    assert trace.supported(Mention(1970.0, "1970", "since the 1970s"))


def test_a_number_from_nowhere_is_caught(trace: Traceability):
    prose = "Santa Fe sits at 2,194 metres above sea level."
    assert [m.text for m in trace.unsupported(prose)] == ["2,194"]


def test_clean_narration_has_nothing_unsupported(trace: Traceability, payload: dict):
    warming = round(payload["comparison"]["warming_c"], 1)
    lo, hi = (round(x, 1) for x in payload["comparison"]["warming_ci"])
    prose = (f"Santa Fe has warmed {warming} C since the 1951-1980 baseline, "
             f"with a 95% interval of {lo} to {hi} C. The grid is about 25 km across.")
    assert trace.unsupported(prose) == []


# --- regressions -----------------------------------------------------------

def test_all_pairs_differences_do_not_license_everything(trace: Traceability):
    """The first checker allowed a difference between any two payload numbers.

    With ~126 numbers that is ~8,000 differences, which cover the small-number
    range so densely that everything passed. A fabricated warming figure must
    still be caught.
    """
    assert trace.unsupported("Santa Fe has warmed 3.4 C since 1951.")


def test_a_day_of_year_cannot_underwrite_a_temperature(trace: Traceability):
    """The second checker matched magnitudes with no regard for units.

    `first_frost_doy` moves from day 290.5 to 293.9 -- a difference of 3.4,
    which was being accepted as support for "warmed 3.4 C". A derived number
    now has to be discussed in the vocabulary of the field it came from.
    """
    assert trace.unsupported("The city has warmed 3.4 C.")
    # ...but the same figure *is* fine when the sentence is actually about frost.
    assert not trace.unsupported("The first autumn frost arrives 3.4 days later.")


def test_vocabulary_ignores_generic_tokens():
    assert "frost" in vocabulary_for("first_frost_doy")
    assert "growing" in vocabulary_for("growing_season_days")
    # "days" and "c" say nothing about what is being measured on their own.
    assert "days" not in vocabulary_for("hot_days")
    assert "hot" in vocabulary_for("hot_days")


def test_temperature_fields_get_a_vocabulary():
    """`mean_c` tokenises to nothing but generics.

    That left it with an empty vocabulary, so no derived temperature could ever
    be supported -- Hobart's "1.5 C above the baseline and about 1.1 above the
    present normal" was scored a hallucination when it is plain subtraction of
    two numbers in the payload.
    """
    assert "warming" in vocabulary_for("mean_c")
    assert "temperature" in vocabulary_for("mean_c_2050")
    # But a day-of-year still does not get to talk about temperature.
    assert "temperature" not in vocabulary_for("first_frost_doy")


def test_projection_window_is_the_same_field(trace: Traceability):
    """`mean_c` and `mean_c_2050` are one field over two windows."""
    assert "mean_c" in trace.by_key
    assert trace.by_key["mean_c"] & trace.by_key["mean_c_2050"] != trace.by_key["mean_c"]


def test_one_decimal_truncation_is_supported(trace: Traceability, payload: dict):
    """"About 1.1" from 1.158 is truncation, not rounding, and writers do it."""
    warming = payload["comparison"]["warming_c"]          # 1.1669
    assert trace.supported(Mention(int(warming * 10) / 10, "1.1", "warmed 1.1 C"))
