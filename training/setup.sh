#!/usr/bin/env bash
# One-time setup for the persona training environment (Apple Silicon).
# Creates training/.venv with mlx-lm — completely separate from the
# backend's Python environment.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  done
fi

echo "Using $($PYTHON --version) at $PYTHON"
"$PYTHON" -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
echo
echo "Training environment ready: training/.venv"
echo "The admin page's Start Training button will now work."
