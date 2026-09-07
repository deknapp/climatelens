---
title: climatelens
emoji: 🌡️
colorFrom: orange
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# climatelens

Pick anywhere on Earth and see what has already changed there — measured
against a 1951–1980 baseline, computed from ERA5 reanalysis rather than
recalled from memory.

- **Observed** — ERA5 (ECMWF) via Open-Meteo. Two thirty-year normals compared,
  with a bootstrapped interval on the headline difference.
- **Projected** — five downscaled CMIP6 models for the 2040s, each differenced
  against its own baseline so model bias cancels. The range between them is
  shown, because a single model's projection has no error bar.
- **El Niño** — what ENSO winters have actually done at that point, over 77
  winters of NOAA's index.

**Narration is disabled on this deployment.** The written "what this means
here" paragraph is the only part that calls an LLM, and it is switched off so
the deployment cannot incur per-visitor cost. Everything numerical works.

Source: https://github.com/deknapp/climatelens
