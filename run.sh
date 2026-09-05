#!/usr/bin/env bash
# Build a virtualenv on first run, then serve on http://127.0.0.1:8099
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: building the environment…"
  (command -v uv >/dev/null && uv venv .venv) || python3 -m venv .venv
  (command -v uv >/dev/null && uv pip install --python .venv/bin/python -q -r requirements.txt) \
    || .venv/bin/pip install -q -r requirements.txt
fi
PORT="${CLIMATELENS_PORT:-8099}"
echo "climatelens → http://127.0.0.1:${PORT}"
exec .venv/bin/python -m uvicorn climatelens.api:app --host 127.0.0.1 --port "$PORT"
