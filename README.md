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

And separately, **what El Niño has actually meant at this point** — see below.

Santa Fe, New Mexico, for example: **+1.17 °C**, just under the global +1.28 °C
over the same period — but **19.5 fewer frost days a year** and a growing season
a week longer.

## Where the numbers come from

| Source | What it is |
|---|---|
| [ERA5](https://www.ecmwf.int/en/forecasts/dataset/ecmwf-reanalysis-v5) (ECMWF), via Open-Meteo | the standard reanalysis record of what the weather actually was, 1940→present |
| CMIP6 downscaled, via Open-Meteo | the model intercomparison underlying the IPCC assessment reports |
| [Open-Meteo](https://open-meteo.com/) geocoding | place name → coordinates |
| [Oceanic Niño Index](https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt), NOAA CPC | which winters since 1950 were El Niño, La Niña, or neutral |

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

## El Niño, for one place

An El Niño gets announced and the local question goes unanswered: *what does
that mean here?* The usual answer is a continental map with a few arrows on
it. This computes the answer for a point instead.

NOAA's index says which winters since 1950 were El Niño. ERA5 says what those
winters were actually like at the chosen coordinates. The gap between the El
Niño winters and the rest is the answer, and three things keep it from
overclaiming:

**Detrending.** El Niño winters are not spread evenly through the record, and
the climate warmed underneath the whole thing. Composited raw, a recent-leaning
set of events reports global warming as though it were an ENSO signal — in a
synthetic record with a pure trend and no ENSO signal at all, the naive version
reports 0.88 °C of El Niño warming that does not exist. Every anomaly here is
measured against the fitted trend across all winters instead.

**A hit rate, not just an average.** One winter is coming, not twenty-five.
Santa Fe's El Niño winters average 122% of normal precipitation, but the number
that answers the actual question is that **17 of 25 were wetter**. Eleven of
twenty-five would be a coin flip however large the mean.

**A permutation test.** With twenty-odd events a composite difference can look
convincing and mean nothing. Shuffling the labels ten thousand times and
counting how often chance does as well is the cheapest honest check, and needs
no distribution tables and no dependency. Santa Fe's precipitation signal
survives at p = 0.004. Its seven *strong* El Niño winters do not survive at all,
and the page says so rather than quietly reporting their mean as a fact.

Validation, against places whose teleconnection is independently known:

| | Winter temperature | Winter precipitation |
|---|---|---|
| **Lima** | +0.54 °C, 20 of 25, p = 0.0001 | 91% of normal, not significant |
| **Santa Fe** | −0.55 °C, 16 of 25, p = 0.039 | 122% of normal, 17 of 25, p = 0.004 |
| **Seattle** | +0.40 °C, 19 of 25, p = 0.026 | 95% of normal, not significant |

Lima sits beside the Niño 3.4 region the index is defined on, and shows the
strongest signal in the set — which is the sanity check working.

The composite covers **December–February only**, because that is when ENSO
peaks and when its influence away from the tropics is strongest. That is a real
limitation, not a hidden one: the Indonesian and eastern Australian droughts
peak in the dry season, roughly June to November, so Jakarta and Sydney look
quiet here even though their teleconnection is strong and well established. A
weak result in this window is not evidence of no signal.

Nothing in this section forecasts. The index reports observed seasons; whether
the coming winter is an El Niño winter is not yet an observed fact, and this
app does not assert things that are not.

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
- **The ENSO composite is history, not a forecast.** It says what past El Niño
  winters did here. It does not say what the next one will do, and a hit rate
  of 17 in 25 is exactly as uncertain as it sounds.
- **ERA5 precipitation is a model-assimilated field, not a rain gauge.** Its
  totals are less trustworthy than its temperatures, most of all in mountains.

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
├── enso.py         the El Niño composite — detrending, hit rates, permutation test
├── llm.py          the narration call; key from env, never serialised
├── api.py          FastAPI routes
└── static/         the page
tests/
├── test_indicators.py   indicators against hand-built series
├── test_enso.py         the composite, including that detrending really works
└── test_privacy.py      the key cannot reach the tree or the browser
```

```bash
.venv/bin/python -m pytest      # 28 tests
```

## Configuration

Copy `.env.example` to `.env` (git-ignored). Everything in it is optional:

- `ANTHROPIC_API_KEY` — enables the written summary. Without it every number
  still renders; only the prose is switched off. Read on the server only: the
  browser never sees it, and `/api/health` reports whether narration is on
  without ever revealing the key itself.
- `CLIMATELENS_MODEL` — defaults to `claude-opus-5`.
- `CLIMATELENS_PORT` — defaults to 8099.

## License

MIT
