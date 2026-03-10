#!/usr/bin/env bash
# Start the Python engine for local development.

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE_DIR="$REPO_ROOT/engine"
VENV_DIR="$ENGINE_DIR/.venv"

if [ ! -f "$VENV_DIR/bin/python" ]; then
  echo "Run scripts/setup-engine.sh first."
  exit 1
fi

echo "Starting OpenMarker engine on http://127.0.0.1:8765 ..."
cd "$ENGINE_DIR"
"$VENV_DIR/bin/python" api/main.py
