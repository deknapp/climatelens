"""Configuration. Every secret is read from the environment, never from the tree."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.environ.get("CLIMATELENS_CACHE", REPO_ROOT / ".cache"))

# The two 30-year climate normals we compare. 1951-1980 is the NASA GISTEMP
# baseline convention; using it means our local numbers are directly comparable
# to the global anomaly everyone quotes.
BASELINE = (1951, 1980)
RECENT = (1995, 2024)

# Global mean surface warming, 1951-1980 baseline to the 2015-2024 decade.
# Source: NASA GISTEMP v4 / IPCC AR6. Used only to give the local number context.
GLOBAL_WARMING_C = 1.28

MODEL = os.environ.get("CLIMATELENS_MODEL", "claude-opus-5")
PORT = int(os.environ.get("CLIMATELENS_PORT", "8099"))


def anthropic_key() -> str | None:
    """The API key, or None if unset.

    Read on the server only. It is never serialised into any API response --
    see tests/test_privacy.py, which fails the build if it ever is.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key or None


def load_dotenv() -> None:
    """Minimal .env loader so there is no dependency just for this."""
    env = REPO_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
