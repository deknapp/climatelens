# climatelens

Pick anywhere on Earth and see what climate change has already done to it.

Not a forecast and not a global average — the local record for one point,
computed from ERA5 reanalysis against a 1951–1980 baseline, next to a CMIP6
projection for the 2040s.

```bash
git clone https://github.com/deknapp/climatelens && cd climatelens
./run.sh          # builds a venv on first run, serves http://127.0.0.1:8099
```

No API key is needed to use it. All the climate data is keyless and public;
only the optional written summary calls Claude.

---

## What it computes

Two thirty-year **climate normals** at the chosen point — **1951–1980** (the
NASA GISTEMP baseline convention, so the local number is directly comparable to
the global anomaly everyone quotes) and **1995–2024** — and the difference
between them:

| | |
|---|---|
| **Annual mean temperature** | the local warming signal, and how it compares to global mean warming |
| **Days above 32 °C / 35 °C** | heat that changes what outdoor work and school days look like |
| **Nights above 20 °C** | the night-time floor above which sleep and heat recovery degrade |
| **Frost days** | often the largest change, and the one that reshapes local ecology |
| **Growing season** | last spring frost to first autumn frost |

Then the same indicators from a downscaled CMIP6 model for the 2040s.

Santa Fe, New Mexico, for example: **+1.17 °C**, just under the global +1.28 °C
over the same period — but **19.5 fewer frost days a year** and a growing season
a week longer.

## Where the numbers come from

| Source | What it is |
|---|---|
| [ERA5](https://www.ecmwf.int/en/forecasts/dataset/ecmwf-reanalysis-v5) (ECMWF), via Open-Meteo | the standard reanalysis record of what the weather actually was, 1940→present |
| CMIP6 downscaled, via Open-Meteo | the model intercomparison underlying the IPCC assessment reports |
| [Open-Meteo](https://open-meteo.com/) geocoding | place name → coordinates |

None of them require an API key.

### One methodological note

A climate model's *absolute* temperature carries its own systematic bias, so
subtracting an ERA5 baseline from a CMIP6 future would report that bias as
though it were warming. The projection here therefore uses the **delta-change
method**: the model's 2040s minus the *same model's* 1951–1980, so the bias
cancels. Without a model baseline to debias against, no projection delta is
reported at all — an absent number beats a wrong one.

In practice Open-Meteo's downscaled product turns out to be bias-corrected
against ERA5 already — measured across four very different climates the
disagreement over the same window is at most 0.08 °C:

| | ERA5 1951–1980 | CMIP6 1951–1980 | bias |
|---|---|---|---|
| Santa Fe, NM | 8.99 °C | 8.99 °C | +0.00 |
| Reykjavík | 3.64 °C | 3.56 °C | −0.08 |
| Nairobi | 18.28 °C | 18.26 °C | −0.02 |
| Jakarta | 25.86 °C | 25.85 °C | −0.01 |

So the correction changes almost nothing today. It stays in because the code
should not quietly depend on a data vendor happening to debias for us.

## What it does not claim

- **ERA5 is a ~25 km gridded reanalysis, not a weather station.** These are the
  numbers for the grid cell containing your town, not the thermometer at the
  local airport.
- **The projection is one model under one scenario.** It is a projection, not a
  forecast, and the spread across models is real and not shown here.
- **Thirty years is the minimum for a climate normal.** Any single year in
  either window can look nothing like the average.
- **Attribution is not causation-per-location.** This shows what changed at a
  point. Formal attribution of a local change to anthropogenic forcing is a
  separate and harder problem.

## Architecture

```
browser ──▶ FastAPI ──▶ Open-Meteo (ERA5, CMIP6, geocoding)   [no key]
                    └─▶ Anthropic  (narration only)           [key, server-side]
```

The API key is read from the server's environment and never leaves the server.
The browser talks only to this app's own `/api/*` routes.
`tests/test_privacy.py` fails the build if a key is ever committed, or if the
frontend so much as names the Anthropic endpoint.

**Claude is not allowed to produce a number.** Every figure on the page is
computed in `climatelens/indicators.py` from the daily series. The model is
handed those computed values and asked what they mean for that place —
grounding, not recall. If the model and the data disagree, the data is right
and the model is the bug.

## Layout

```
climatelens/
├── config.py       baseline windows, thresholds, env-only secrets
├── data.py         Open-Meteo clients (ERA5, CMIP6, geocoding) + disk cache
├── indicators.py   the seven indicators — pure functions, no I/O, no model
├── llm.py          the narration call; key from env, never serialised
├── api.py          FastAPI routes
└── static/         the page
tests/
├── test_indicators.py   indicators against hand-built series
└── test_privacy.py      the key cannot reach the tree or the browser
```

```bash
.venv/bin/python -m pytest      # 13 tests
```

## Configuration

Copy `.env.example` to `.env` (git-ignored). Everything in it is optional:

- `ANTHROPIC_API_KEY` — enables the written summary. Without it every number
  still renders; only the prose is switched off.
- `CLIMATELENS_MODEL` — defaults to `claude-opus-5`.
- `CLIMATELENS_PORT` — defaults to 8099.

## License

MIT
