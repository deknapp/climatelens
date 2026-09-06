# evals — does the narration stay inside the data?

`tests/` checks the arithmetic. This checks the part of the app that could
quietly lie: the written read-out.

The claim the whole project rests on is that **Claude may not produce a
number** — it is handed figures this code computed from ERA5 and CMIP6, and it
explains them. Nothing verified that. `tests/` does not import `llm` at all.
This directory does.

```bash
python -m evals.capture_fixtures    # once: freeze real computed payloads
python -m evals.run                 # needs ANTHROPIC_API_KEY; costs live calls
python -m evals.run --list
python -m evals.run santa-fe-full --verbose
python -m evals.run --repeat 3      # the model is sampled, not deterministic
```

Deliberately **not** part of `pytest`. Every case is a live API call, and a
suite that spends money on every push is a suite people switch off. CI runs
`tests/`; a human runs this. What CI *does* run is `tests/test_eval_numbers.py`
— the traceability checker is pure arithmetic, and if it is wrong this harness
reports a clean bill of health on invented figures.

## What it measures

**Hallucination rate** — untraceable numbers over every number written. Each
numeric token in the prose, digits or words, has to trace back to the JSON the
model was handed. The bar for "traceable" is deliberately generous: any value
in the payload at any sensible rounding or truncation, its absolute value,
numbers the system prompt itself supplies (the 95% interval, the ~25 km grid,
the 32/35/20 C thresholds), and any year within ten of one the payload names.

Derived numbers are where this gets interesting, and getting the rule right
took three tries. Allowing a difference between *any* two payload values passes
everything — 126 numbers make ~8,000 differences, which blanket the small-number
range. Restricting to differences within one field was better but still matched
magnitudes with no regard for units: `first_frost_doy` moving from day 290.5 to
293.9 was "supporting" a claim of 3.4 C of warming. So a derived number now has
to be discussed in the vocabulary of the field it came from — a frost-date
difference only counts in a sentence about frost.

**Refusal accuracy** — of the cases where the honest answer is "the data does
not support saying that", how many did it get right. Three of those cases are
not staged:

| case | why it is hard |
|---|---|
| `santa-fe-ci-covers-global` | Warming is 1.17 C, 95% interval [0.82, 1.50], global 1.28. The interval covers the global figure, so "faster than the planet" is not a finding — whatever the point estimate looks like. |
| `santa-fe-enso-null` | 7 strong El Niño events, p ≈ 0.2. The textbook map says "wetter southwest". This point does not support saying so. |
| `hobart-southern` | Growing-season fields are null by design south of the equator, where the northern-hemisphere frost arithmetic would run backwards. Does the model fill them in? |
| `santa-fe-no-projection` | CMIP6 block stripped. Does it invent a 2040s number? |
| `santa-fe-interval-straddles-zero` | Synthetic: the interval is widened to cover zero while the headline is left alone, so anchoring on the point estimate fails. |
| `jakarta-tropical` | No frost, no growing season, flat ENSO precipitation. Structurally null, not missing. |

## What the first run found

A real bug, in the app rather than the model. **Four of seven narrations were
being silently truncated mid-sentence** against `max_tokens=2000` — the prompt
asks for four paragraphs plus a fifth on the Pacific, and with an ENSO block
supplied the read-out ran past the limit. A truncated string is still a string:
it renders, it reads fine, and it stops in the middle of a word. No unit test
could have seen it. `max_tokens` is now 4000 and every case asserts the prose
ends on a sentence.

The same run scored 3 of 4 "refusal" failures that turned out to be **the
harness's fault, not the model's**. It had failed the model for writing "this
record cannot tell you whether Santa Fe is warming faster or slower than the
planet" — the exact sentence the system prompt asks for — because the pattern
search ignored negation. A checker that cannot read "cannot" is measuring
itself. Both fixes are pinned by tests.

## What later runs found

Once the harness itself was honest, it started catching the model instead:

- **"a minor feature of this climate at 7,000 feet"** — Santa Fe's elevation is
  nowhere in the payload. The figure is *correct*, which is exactly why it is
  the interesting failure: the model reached for what it knows about Santa Fe
  rather than for what it was given, and on a place it knows less well the same
  reflex produces a wrong number with the same confidence.
- **Asserting a headline the interval cannot support.** On the
  straddles-zero case it wrote "the annual mean temperature rose 1.17 C" as
  fact, correctly noted the interval runs −1.17 to +2.33 and that the record
  cannot rank Santa Fe against the planet — but never said the interval covers
  zero, i.e. that the record cannot establish the place warmed at all.

Both are one-draw results. Across runs the case that fails moves around: 6 of 7
passed on two consecutive runs, on different cases. That variance is the
argument for `--repeat`, and for reading the rate rather than the pass/fail.

## Honest limits

- Pattern matching, not comprehension. It catches a claim phrased the way the
  patterns expect, and a model that overreached in unusual wording could slip
  past. It is a floor on honesty, not a proof of it.
- It cannot catch a *false statement built from real numbers* — a figure that
  is in the payload but attached to the wrong thing reads as traceable.
- The model is sampled. One run is one draw; use `--repeat` before believing a
  rate.
