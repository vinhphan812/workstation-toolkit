#!/bin/bash
# Bootstrap script for Linux/macOS
# Run: bash install.sh

set -e
cd "$(dirname "$0")/.."

echo "Installing Workstation Toolkit..."

if ! command -v python3 &>/dev/null; then
    echo "Python 3 not found. Install from python.org or your package manager."
    exit 1
fi

if ! command -v uv &>/dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.local/bin/env" 2>/dev/null || true
fi

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

echo "Installed. Activate: source .venv/bin/activate"
echo "Run: python -m workstation diagnose"
