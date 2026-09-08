# climatelens as a running service.
#
# A server is genuinely required here. The page needs thirty-year normals,
# bootstrapped intervals and ENSO composites computed over seventy years of
# daily ERA5 — that is real numerical work, and moving it into the browser
# would mean rewriting it in JavaScript and getting it subtly wrong.
#
# Narration is deliberately switched off in this image. It is the only part of
# the application that costs money per visitor, and on a public deployment
# that cost would fall on whoever configured the key. Every number on the page
# is computed from ERA5 and CMIP6 and is unaffected by its absence.

FROM python:3.11-slim

RUN useradd -m -u 1000 user
# CLIMATELENS_CACHE matters. The disk cache defaults to <repo>/.cache, which is
# /app/.cache in this image -- and /app is root-owned while the process runs as
# uid 1000, so the first cache write fails, FastAPI answers a 500, and the page
# tries to parse "Internal Server Error" as JSON. /tmp is the one place a Space
# is guaranteed to be writable.
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    CLIMATELENS_DISABLE_NARRATION=1 \
    PORT=7860 \
    CLIMATELENS_CACHE=/tmp/climatelens-cache

WORKDIR /app
COPY --chown=user . /app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e . \
    && pip install --no-cache-dir uvicorn

RUN mkdir -p /tmp/climatelens-cache && chown -R user:user /tmp/climatelens-cache /app

USER user
EXPOSE 7860

# Spaces expect the service on 7860. One worker: the free tier has two cores
# and the upstream calls are I/O bound, so concurrency buys nothing here and
# a second worker would double the cache misses.
CMD ["uvicorn", "climatelens.api:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
