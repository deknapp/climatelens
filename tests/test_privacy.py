"""This repo is public and the app holds an API key. These tests are the reason
that is safe: the key must never reach the browser or the git tree."""

import re
import subprocess
from pathlib import Path

from climatelens import config

REPO_ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".py", ".md", ".toml", ".txt", ".html", ".css", ".js",
                 ".yml", ".yaml", ".json", ".sh", ".example", ".cfg", ""}


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT,
                         capture_output=True, text=True)
    return [REPO_ROOT / line for line in out.stdout.splitlines() if line.strip()]


# A real key is the prefix followed by a long opaque secret. Matching the bare
# prefix would flag this file's own source, and `.env.example`, which show the
# shape without ever containing a key.
KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")


def test_no_anthropic_key_is_committed_anywhere():
    for path in tracked_files():
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.exists():
            continue
        if path.resolve() == Path(__file__).resolve():
            continue  # this file necessarily talks about the shape of a key
        found = KEY_RE.search(path.read_text(errors="ignore"))
        assert not found, f"possible real API key committed in {path}"


def test_dotenv_is_ignored_by_git():
    assert ".env" in (REPO_ROOT / ".gitignore").read_text().split()


def test_the_frontend_never_mentions_a_key():
    """The browser calls our own routes only. If the page ever names the key or
    the Anthropic endpoint directly, the server-side-only guarantee is broken."""
    page = (REPO_ROOT / "climatelens" / "static" / "index.html").read_text()
    assert "ANTHROPIC_API_KEY" not in page
    assert "api.anthropic.com" not in page
    assert "sk-ant" not in page


def test_key_is_read_from_environment_only(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert config.anthropic_key() is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert config.anthropic_key() == "sk-ant-test"
