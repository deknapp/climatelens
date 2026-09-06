"""Extract every number from prose, and decide whether the data supports it.

This is the whole point of the harness. The app's central claim is that Claude
may not produce a number -- it narrates figures this code already computed. That
claim was never checked by anything: `tests/` does not import `llm`.

The rule enforced here: every numeric token in the narration must be traceable
to the JSON the model was handed. "Traceable" has to be generous or the harness
cries wolf, and the boundary took two iterations to get right. Both failures are
worth recording, because they are the whole reason to trust the number it prints.

**First attempt: any difference between any two values.** That sounds fair --
"12 hot days then, 15 now" makes "three more" a legitimate sentence. But a
payload holds ~126 numbers, so ~8,000 pairwise differences densely cover the
entire small-number range and the check passes everything. A planted "warmed
3.4 C" scored as supported.

**Second attempt: differences within the same field only.** Better, and still
wrong. `first_frost_doy` moves from day 290.5 to day 293.9, a difference of 3.4
-- which happily "supported" that same planted 3.4 C of warming. Magnitudes were
being matched with no regard for what they measured.

**What it does now.** A number that appears *literally* in the payload needs no
context; it is in the data. A number that has to be *derived* must also be
discussed in the vocabulary of the field it was derived from -- a difference
between two frost dates only counts if the sentence is about frost. That is what
stops a day-of-year from underwriting a temperature.

Also allowed, all context-free because they are unambiguous:

  - the absolute value of a payload number (a delta of -19.5 read as "19 fewer")
  - numbers the *system prompt* supplies (the 95% interval, the ~25 km grid,
    the 32 C / 35 C / 20 C thresholds it names)
  - any year within ten of a year the payload names, so "the 1970s" is fine

Anything left over is a number the model brought from somewhere else, which is
the failure this repo claims cannot happen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Spelled-out numbers, because "seventeen of twenty five El Nino winters" is the
# form the system prompt actually asks for and a digit-only regex would miss it.
WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
}

_NUMERIC = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w])")
_WORD = re.compile(r"\b(" + "|".join(WORDS) + r")\b", re.IGNORECASE)

# Field-name tokens that say nothing about what a number measures, so they can
# never license a derived figure on their own.
GENERIC = {"c", "days", "day", "doy", "mean", "value", "2050", "km", "per",
           "decade", "rate", "avg", "average", "n", "count", "total"}

# What a field's numbers are allowed to be talked about as. A derived number is
# only supported if the sentence around it uses one of these words.
VOCABULARY = {
    "frost": {"frost", "freeze", "freezing", "frozen"},
    "hot": {"hot", "heat", "32", "90"},
    "very": {"hot", "heat", "35", "95", "dangerous"},
    "warm": {"warm", "night", "nights", "overnight", "sleep"},
    "nights": {"night", "nights", "overnight", "warm", "sleep"},
    "growing": {"growing", "season", "grow", "garden", "crop"},
    "season": {"growing", "season", "grow", "garden", "crop"},
    "min": {"minimum", "night", "nights", "overnight", "low", "lows", "coldest"},
    "max": {"maximum", "day", "daytime", "high", "highs", "afternoon", "hottest"},
    "first": {"first", "autumn", "fall", "frost"},
    "last": {"last", "spring", "frost"},
    "precipitation": {"precipitation", "rain", "rainfall", "wet", "dry", "moisture"},
    "precip": {"precipitation", "rain", "rainfall", "wet", "dry", "moisture"},
    "winters": {"winter", "winters", "event", "events"},
    "events": {"winter", "winters", "event", "events"},
    "nino": {"nino", "el nino"},
    "nina": {"nina", "la nina"},
    "neutral": {"neutral"},
    "years": {"year", "years"},
    "covered": {"year", "years", "record", "coverage"},
    "warming": {"warm", "warming", "warmer", "temperature"},
    "temperature": {"warm", "warming", "warmer", "temperature", "degree", "degrees"},
}


@dataclass(frozen=True)
class Mention:
    """One number as it appeared in the prose."""

    value: float
    text: str
    context: str

    def __str__(self) -> str:
        return f"{self.text!r} in …{self.context}…"


def extract(prose: str) -> list[Mention]:
    """Every number in the text, digits or words, with surrounding context."""
    found: list[Mention] = []
    for match in _NUMERIC.finditer(prose):
        raw = match.group(1)
        found.append(Mention(float(raw.replace(",", "")), raw,
                             _context(prose, match.start(), match.end())))
    for match in _WORD.finditer(prose):
        word = match.group(1).lower()
        found.append(Mention(float(WORDS[word]), word,
                             _context(prose, match.start(), match.end())))
    return found


def _context(text: str, start: int, end: int, width: int = 45) -> str:
    return " ".join(text[max(0, start - width):end + width].split())


def values_in(obj, out: set[float] | None = None) -> set[float]:
    """Every number anywhere in a nested JSON structure."""
    if out is None:
        out = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            values_in(value, out)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            values_in(value, out)
    elif isinstance(obj, str):
        for token in re.findall(r"\d+(?:\.\d+)?", obj):
            out.add(float(token))
    return out


def groups_in(obj, by_key=None, siblings=None):
    """Two views of the payload that make derived numbers checkable.

    ``by_key`` maps a field name to every value it takes anywhere in the tree,
    so ``hot_days`` collects the baseline, recent and projection figures and a
    difference between them is a sentence the data supports.

    ``siblings`` holds the ``{name: value}`` numbers sitting directly together
    in one object, so a ratio between two of them ("seventeen of twenty five,
    so 68%") is supported.
    """
    if by_key is None:
        by_key, siblings = {}, []
    if isinstance(obj, dict):
        here: dict[str, float] = {}
        for key, value in obj.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                by_key.setdefault(key, set()).add(float(value))
                # `mean_c` and `mean_c_2050` are one field over two windows, so
                # "1.5 C above the baseline, 1.1 above today" is arithmetic the
                # data supports. Grouping them under the base name is what lets
                # the check see that.
                base = key[:-5] if key.endswith("_2050") else key
                if base != key:
                    by_key.setdefault(base, set()).add(float(value))
                here[key] = float(value)
            else:
                groups_in(value, by_key, siblings)
        if len(here) > 1:
            siblings.append(here)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            groups_in(value, by_key, siblings)
    return by_key, siblings


def _roundings(value: float) -> set[float]:
    """The forms a writer might legitimately use for one computed number."""
    forms = {value, abs(value)}
    for v in (value, abs(value)):
        for places in (0, 1, 2):
            forms.add(round(v, places))
        forms.add(float(int(v)))          # truncation: 19.47 -> "19 fewer days"
        forms.add(float(int(v)) + 1)      # and rounding up to the next whole day
        forms.add(int(v * 10) / 10)       # and "about 1.1" from 1.158
    return forms


# A bare temperature field ("mean_c") tokenises to nothing but generics, which
# left it with no vocabulary and so no derived number from it could ever be
# supported. These are the words a temperature is actually discussed in.
TEMPERATURE = {"temperature", "temperatures", "warm", "warmed", "warming",
               "warmer", "cooler", "colder", "degree", "degrees", "normal",
               "baseline", "mean", "average", "annual"}


def vocabulary_for(key: str) -> set[str]:
    """The words a derived number from this field may be discussed in."""
    words: set[str] = set()
    for token in re.split(r"[_\s]+", key.lower()):
        if token in GENERIC or not token:
            continue
        words |= VOCABULARY.get(token, {token})
    if not words and re.search(r"_c(_2050)?$|^warming", key.lower()):
        return set(TEMPERATURE)
    return words


class Traceability:
    """Decides whether a number in the prose is supported by the data."""

    # Supplied by the system prompt rather than the JSON, so legitimate.
    PROMPT_CONSTANTS = {95.0, 25.0, 32.0, 35.0, 20.0, 0.0, 1.0, 2.0, 3.0, 4.0}

    def __init__(self, payload: dict, *, tolerance: float = 0.051):
        self.tolerance = tolerance
        self.raw = values_in(payload)
        self.by_key, self.sibling_sets = groups_in(payload)

        # Context-free: these numbers are in the data, or in the prompt.
        self.allowed: set[float] = set(self.PROMPT_CONSTANTS)
        for value in self.raw:
            self.allowed |= _roundings(value)

        # Context-bound: a difference within one field, usable only if the
        # sentence is about that field. See the module docstring.
        self.derived: list[tuple[float, set[str]]] = []
        for key, values in self.by_key.items():
            words = vocabulary_for(key)
            if not words:
                continue
            ordered = sorted(values)
            for i, a in enumerate(ordered):
                for b in ordered[i + 1:]:
                    for form in _roundings(b - a):
                        self.derived.append((form, words))

        self.years = self._year_span(payload)

    @staticmethod
    def _year_span(payload: dict) -> set[float]:
        """Any year within ten of one the JSON names, so "the 1970s" passes."""
        years = {int(v) for v in values_in(payload)
                 if 1800 <= v <= 2100 and v == int(v)}
        span: set[float] = set()
        for year in years:
            span |= {float(y) for y in range(year - 10, year + 11)}
        return span

    def _mentions(self, context: str, words: set[str]) -> bool:
        low = context.lower()
        return any(word in low for word in words)

    def supported(self, mention: Mention) -> bool:
        value = mention.value
        if any(abs(value - a) <= self.tolerance for a in self.allowed):
            return True
        if value in self.years:
            return True
        for form, words in self.derived:
            if abs(value - form) <= self.tolerance and self._mentions(mention.context, words):
                return True
        # A percentage computed from two counts sitting side by side in one
        # object: 17 of 25 -> "68%". Siblings only, and the sentence still has
        # to be about one of them.
        if "%" in mention.context or "percent" in mention.context.lower():
            for group in self.sibling_sets:
                for name_a, a in group.items():
                    for name_b, b in group.items():
                        if not b or name_a == name_b:
                            continue
                        # "122% of the normal" and "70 percent more than" are
                        # both ratios of the same two numbers, stated
                        # differently. The second form cost a false positive on
                        # the first run: nights warmed 1.48 C against days at
                        # 0.87, and "roughly 70 percent more" was scored a
                        # hallucination because only 170% was being allowed.
                        for candidate in (100.0 * a / b, 100.0 * (a - b) / b):
                            if abs(value - candidate) <= 1.0 and (
                                    self._mentions(mention.context, vocabulary_for(name_a))
                                    or self._mentions(mention.context, vocabulary_for(name_b))):
                                return True
        return False

    def unsupported(self, prose: str) -> list[Mention]:
        return [m for m in extract(prose) if not self.supported(m)]
