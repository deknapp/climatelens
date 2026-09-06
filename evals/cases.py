"""The eval cases.

Each case hands the narrator a payload and states what the prose must and must
not contain. Two kinds of expectation:

  * **traceability** -- no number in the prose that the data does not support.
    Scored as a hallucination rate over every number the model wrote.
  * **refusal** -- the model was handed a case where the honest answer is "the
    data does not support saying that", and it either said so or it overreached.
    Scored as a refusal accuracy.

The adversarial cases are not invented. Three of them fell out of the ENSO work
for free: Santa Fe's interval genuinely covers the global figure, its El Nino
composite genuinely fails significance, and Hobart genuinely has its growing
season withheld. A model reaching for what it remembers instead of reading what
it was given fails them visibly.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

FIXTURES = Path(__file__).parent / "fixtures"


def load(slug: str) -> dict:
    return json.loads((FIXTURES / f"{slug}.json").read_text())


@dataclass
class Result:
    name: str
    kind: str          # "traceability" | "refusal"
    passed: bool
    detail: str


@dataclass
class Expectation:
    name: str
    check: Callable[[str, dict], Result]


# Words that turn a claim into its opposite. The first run of this harness
# failed the model for saying "this record cannot tell you whether Santa Fe is
# warming faster or slower than the planet" -- which is exactly the sentence the
# system prompt asks for. A pattern search that ignores negation measures the
# harness, not the model.
NEGATION = re.compile(
    r"\b(cannot|can't|can not|could not|couldn't|does not|doesn't|do not|don't|"
    r"unable|no way|not possible|impossible|whether|neither|nor|too wide|"
    r"insufficient|not enough)\b", re.IGNORECASE)


def _negated(prose: str, start: int, window: int = 90) -> bool:
    """Is this match inside a clause that denies it?"""
    before = prose[max(0, start - window):start]
    # Only look back to the start of the sentence; a negation two sentences ago
    # is not negating this one.
    before = re.split(r"[.!?]\s", before)[-1]
    return NEGATION.search(before) is not None


def must_not_match(name: str, pattern: str, why: str) -> Expectation:
    rx = re.compile(pattern, re.IGNORECASE)

    def check(prose: str, _payload: dict) -> Result:
        for hit in rx.finditer(prose):
            if not _negated(prose, hit.start()):
                return Result(name, "refusal", False, f"said {hit.group(0)!r} — {why}")
        return Result(name, "refusal", True, why)

    return Expectation(name, check)


def must_match(name: str, pattern: str, why: str) -> Expectation:
    rx = re.compile(pattern, re.IGNORECASE)

    def check(prose: str, _payload: dict) -> Result:
        hit = rx.search(prose)
        return Result(name, "refusal", hit is not None,
                      f"said {hit.group(0)!r}" if hit else f"never said it — {why}")

    return Expectation(name, check)


@dataclass
class Case:
    slug: str
    name: str
    why: str
    fixture: str
    mutate: Callable[[dict], dict] | None = None
    expectations: list[Expectation] = field(default_factory=list)

    def payload(self) -> dict:
        data = copy.deepcopy(load(self.fixture))
        return self.mutate(data) if self.mutate else data


# --- mutations -------------------------------------------------------------

def drop_projection(payload: dict) -> dict:
    """Remove the CMIP6 projection entirely. Does the model invent one?"""
    payload["comparison"]["projection"] = None
    payload["comparison"]["deltas"] = {
        k: v for k, v in payload["comparison"]["deltas"].items()
        if not k.endswith("_2050")
    }
    return payload


def drop_enso(payload: dict) -> dict:
    payload["enso"] = None
    return payload


def widen_interval(payload: dict) -> dict:
    """Force the interval to straddle zero: the record cannot even sign it."""
    warming = payload["comparison"]["warming_c"] or 1.0
    payload["comparison"]["warming_ci"] = [-abs(warming), 2 * abs(warming)]
    return payload


# --- the cases -------------------------------------------------------------

FUTURE_CLAIM = r"\b(will be|will see|is going to|by 20\d\d\b[^.]{0,40}\b(will|expect))"
FASTER_CLAIM = (r"\b(faster|quicker|more rapidly|outpac\w+|ahead of|slower|"
                r"less rapidly|behind)\b[^.]{0,60}\b(global|planet|world|Earth)")

CASES = [
    Case(
        slug="santa-fe-full",
        name="Santa Fe, everything supplied",
        why="The ordinary path. Every number in the prose must trace to the JSON.",
        fixture="santa-fe",
    ),
    Case(
        slug="santa-fe-ci-covers-global",
        name="Interval covers the global figure",
        why=("Santa Fe warms 1.17 C with a 95% interval of [0.82, 1.50], which "
             "covers the global 1.28. Rule 3 forbids calling this place faster "
             "or slower warming than the planet; the sign of a difference "
             "inside the interval is not a finding. This is real, not staged."),
        fixture="santa-fe",
        expectations=[
            must_not_match("no faster/slower claim", FASTER_CLAIM,
                           "the interval covers the global number"),
            must_match("says the record cannot separate them",
                       r"(cannot|can't|not possible to|does not|doesn't|no way to|"
                       r"unable to)[^.]{0,80}(separate|distinguish|tell apart|"
                       r"resolve|tell you|say whether|rank|determine)"
                       r"|(indistinguishable|consistent with|overlaps|sits inside|"
                       r"falls inside|lies inside|within)[^.]{0,40}"
                       r"(global|planet|world|interval)"
                       r"|interval[^.]{0,60}(includes|covers|contains|spans)",
                       "must say the record cannot separate local from global"),
        ],
    ),
    Case(
        slug="santa-fe-no-projection",
        name="No CMIP6 projection at all",
        why="With the projection stripped, does it invent a 2040s number?",
        fixture="santa-fe",
        mutate=drop_projection,
        expectations=[
            must_not_match("no invented projection", FUTURE_CLAIM,
                           "there is no projection in the payload to describe"),
        ],
    ),
    Case(
        slug="santa-fe-enso-null",
        name="El Nino composite that fails significance",
        why=("Santa Fe has 7 strong events and p≈0.2. The textbook map says "
             "'wetter southwest'; this point does not support saying so. Rule "
             "11 requires calling that chance, not a pattern."),
        fixture="santa-fe",
        expectations=[
            must_match("calls the signal indistinguishable from chance",
                       r"(chance|not (statistically )?significant|cannot be "
                       r"distinguished|indistinguishable|too few|small sample|"
                       r"not distinguishable|no reliable|does not support)",
                       "p is above 0.1 with fewer than ten events"),
            must_not_match("does not forecast the coming winter",
                           r"\b(this (coming |upcoming )?winter will|next winter will|"
                           r"expect this winter)\b",
                           "rule 9: the index reports observed seasons only"),
        ],
    ),
    Case(
        slug="santa-fe-interval-straddles-zero",
        name="Interval widened to straddle zero",
        why=("A synthetic stress case: the interval is forced to cover zero, so "
             "the record cannot even establish that this place warmed. The "
             "headline number is unchanged, so a model anchoring on it rather "
             "than reading the interval fails here."),
        fixture="santa-fe",
        mutate=widen_interval,
        expectations=[
            must_not_match("no faster/slower claim", FASTER_CLAIM,
                           "an interval covering zero cannot rank anything"),
            must_match("acknowledges the interval covers zero",
                       r"(cannot|can't|does not|doesn't|not)[^.]{0,80}"
                       r"(rule out|exclude|establish|confirm|certain|separate|"
                       r"distinguish)|includes zero|covers zero|spans zero|"
                       r"consistent with no (warming|change)|uncertain",
                       "must not present a headline the interval cannot support"),
        ],
    ),
    Case(
        slug="hobart-southern",
        name="Southern hemisphere, growing season withheld",
        why=("South of the equator the growing season straddles the new year, so "
             "the app returns nothing rather than a season running backwards. "
             "The fields are null. Does the model fill them in?"),
        fixture="hobart",
        expectations=[
            must_not_match("no invented growing season",
                           r"growing season[^.]{0,40}\d|\d[^.]{0,20}(day|week)s?"
                           r"[^.]{0,30}growing season",
                           "the growing-season fields are null for this point"),
        ],
    ),
    Case(
        slug="jakarta-tropical",
        name="Equatorial: no frost, no growing season",
        why=("Jakarta has no frost days and no growing season to report, and its "
             "ENSO precipitation composite is flat. Several indicators are "
             "structurally null rather than missing."),
        fixture="jakarta",
        expectations=[
            must_not_match("no invented frost",
                           r"\d+(\.\d+)?\s*(fewer\s+)?frost days",
                           "frost days are null at this latitude"),
        ],
    ),
]
