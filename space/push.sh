#!/usr/bin/env bash
# Copy this repository into a Hugging Face Space and push it.
#
#   usage:  bash space/push.sh <hf-username> [space-name]
#
# Narration is disabled by the Dockerfile (CLIMATELENS_DISABLE_NARRATION=1),
# so this deployment cannot call an LLM and cannot cost anything per visitor.
# Do not add an ANTHROPIC_API_KEY secret to the Space.
set -euo pipefail

USER="${1:?usage: bash space/push.sh <hf-username> [space-name]}"
NAME="${2:-climatelens}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)/${NAME}"

echo "Cloning https://huggingface.co/spaces/${USER}/${NAME}"
git clone "https://huggingface.co/spaces/${USER}/${NAME}" "$WORK"
cd "$WORK"

cp -R "$SRC/climatelens" .
cp "$SRC/pyproject.toml" "$SRC/LICENSE" .
cp "$SRC/space/Dockerfile" "$SRC/space/README.md" .

# A Space is a public git repository. .env must never reach it.
cat > .gitignore <<'IGNORE'
.env
.env.*
__pycache__/
*.pyc
.venv/
cache/
IGNORE

# Belt and braces: refuse to push if a key somehow made it into the tree.
if grep -rqE "sk-ant-[A-Za-z0-9_-]{20,}" . --exclude-dir=.git 2>/dev/null; then
  echo "ABORT: something that looks like an API key is in the tree." >&2
  exit 1
fi

git add -A
git commit -m "climatelens: narration disabled" || echo "nothing to commit"

echo
echo "Pushing. Username: ${USER}   Password: your Hugging Face WRITE token."
git push

echo
echo "Done. Watch the build at:"
echo "  https://huggingface.co/spaces/${USER}/${NAME}"
