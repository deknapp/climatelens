"""The written read-out.

Claude's job here is narrow on purpose: it is handed numbers that this app has
already computed from ERA5 and CMIP6, and asked to say what they mean for the
place in question. It is never asked what the temperature is. If the model and
the data ever disagree, the data is right and the model is the bug.

The API key is read from the process environment on the server. It is never
placed in a response body, a template, or anything the browser receives.
"""

from __future__ import annotations

import json

from .config import MODEL, anthropic_key

SYSTEM = """You explain local climate data to a non-specialist.

You will be given a JSON block of already-computed statistics for one location:
a 1951-1980 baseline climate normal, a 1995-2024 normal, the differences
between them, and where available a CMIP6 projection for the 2040s.

Rules, in order of importance:

1. Never state a number that is not in the JSON you were given. You have no
   independent knowledge of this location's climate. If a field is null, the
   data did not support computing it -- say so plainly or leave it out.
2. Do not round away the signal. If warming is 1.7 C, say 1.7 C, not "almost
   two degrees".
3. "warming_ci" is a 95% interval on the headline number. Quote it at least
   once, and respect it: if it covers "global_warming_c" you may NOT say this
   place is warming faster or slower than the planet. Say the record cannot
   separate them. The sign of a difference that sits inside the interval is
   not a finding.
4. Lead with whichever indicator actually changed most for this place. In some
   places that is summer heat; in many colder places the story is the collapse
   in frost days and a longer growing season, which matters more locally than
   the annual mean.
5. Be concrete and local. "Thirty more days a year above 32 C than your
   grandparents had" beats "significant warming".
6. State uncertainty honestly. ERA5 is a ~25 km gridded reanalysis, not the
   thermometer at the local airport. The projection is one model under one
   scenario, not a forecast.
7. No exhortation, no policy advice, no comfort, no alarm. Describe what
   changed. The reader can draw their own conclusions.

You may also be given an "enso" block: the state of the Pacific right now from
NOAA's Oceanic Nino Index, and a composite of what past El Nino, La Nina and
neutral winters were actually like at this exact point. Additional rules that
apply to it, and that override anything you believe you know:

8. You know the textbook El Nino map. Ignore it. The only El Nino signal you
   may describe is the one computed for this point. If the composite here
   disagrees with the continental picture you remember, the composite is
   right and you say what it says.
9. Never forecast. The index reports observed seasons; whether the coming
   winter is an El Nino winter is not yet an observed fact. Say what past
   events did here, not what this one will do.
10. Report the hit rate alongside the average, always. "Seventeen of twenty
   five El Nino winters were wetter than trend" is the honest form. An
   average shift that only half the events shared is not an expectation, and
   you must say so.
11. Respect the p-value you are given. Above about 0.1, or with fewer than
    ten events, the signal is not distinguishable from chance -- say that
    plainly rather than describing the number as though it were a pattern.
12. The anomalies are measured against the fitted warming trend, so they are
    ENSO on top of warming, not instead of it. Do not present them as a
    reprieve from the warming described above.

Write 3-4 short paragraphs of plain prose, plus one further short paragraph on
the Pacific if an "enso" block was supplied. No headings, no bullet points."""


class LLMUnavailable(RuntimeError):
    """No API key configured. The app still works; only narration is off."""


def available() -> bool:
    return anthropic_key() is not None


def explain(place_label: str, comparison: dict, *, enso: dict | None = None,
            timeout: float = 60.0) -> str:
    """Narrate an already-computed comparison. Returns prose.

    ``enso`` is optional: when the ENSO composite for this point has been
    computed, it is handed over too, under the same rule as everything else --
    the model explains these numbers and may not supply its own.
    """
    key = anthropic_key()
    if key is None:
        raise LLMUnavailable(
            "ANTHROPIC_API_KEY is not set. Every number on the page is still "
            "computed and displayed; only the written summary needs a key."
        )

    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise LLMUnavailable("the `anthropic` package is not installed") from exc

    client = anthropic.Anthropic(api_key=key, timeout=timeout)
    block: dict = {"location": place_label, "statistics": comparison}
    if enso:
        block["enso"] = enso
    payload = json.dumps(block, indent=2, default=str)

    response = client.messages.create(
        model=MODEL,
        # 2000 was not enough. The prompt asks for four paragraphs plus a fifth
        # on the Pacific, and with an ENSO block supplied the read-out ran past
        # the limit and stopped mid-sentence -- on four of seven eval cases,
        # silently, because a truncated string is still a string. Nothing in
        # tests/ could catch that; evals/ caught it on its first run.
        max_tokens=4000,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                f"Here are the computed climate statistics for {place_label}. "
                f"Explain what they mean for this place.\n\n```json\n{payload}\n```"
            ),
        }],
    )

    return "".join(b.text for b in response.content if b.type == "text").strip()
