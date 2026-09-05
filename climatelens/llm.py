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
3. Lead with whichever indicator actually changed most for this place. In some
   places that is summer heat; in many colder places the story is the collapse
   in frost days and a longer growing season, which matters more locally than
   the annual mean.
4. Be concrete and local. "Thirty more days a year above 32 C than your
   grandparents had" beats "significant warming".
5. State uncertainty honestly. ERA5 is a ~25 km gridded reanalysis, not the
   thermometer at the local airport. The projection is one model under one
   scenario, not a forecast.
6. No exhortation, no policy advice, no comfort, no alarm. Describe what
   changed. The reader can draw their own conclusions.

Write 3-4 short paragraphs of plain prose. No headings, no bullet points."""


class LLMUnavailable(RuntimeError):
    """No API key configured. The app still works; only narration is off."""


def available() -> bool:
    return anthropic_key() is not None


def explain(place_label: str, comparison: dict, *, timeout: float = 60.0) -> str:
    """Narrate an already-computed comparison. Returns prose."""
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
    payload = json.dumps({"location": place_label, "statistics": comparison},
                         indent=2, default=str)

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
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
