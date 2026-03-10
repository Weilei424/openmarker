#!/usr/bin/env bash
# Set up the Python engine virtual environment and install dependencies.

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE_DIR="$REPO_ROOT/engine"
VENV_DIR="$ENGINE_DIR/.venv"

echo "Setting up Python engine..."

cd "$ENGINE_DIR"

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r requirements.txt

echo "Engine setup complete. Venv: $VENV_DIR"
echo "To run: $VENV_DIR/bin/python api/main.py"
