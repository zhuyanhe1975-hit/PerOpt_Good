#!/usr/bin/env bash
set -euo pipefail

# Run the Vite dev server for the UI.
#
# Usage:
#   scripts/dev_frontend.sh
#   VITE_PORT=3000 scripts/dev_frontend.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found. Please install Node.js/npm first." >&2
  exit 1
fi

VITE_HOST="${VITE_HOST:-0.0.0.0}"
VITE_PORT="${VITE_PORT:-3000}"

echo "[frontend] host: $VITE_HOST"
echo "[frontend] port: $VITE_PORT"
echo
echo "[frontend] UI will be: http://localhost:${VITE_PORT}/"
echo

if [[ ! -d node_modules ]]; then
  echo "[frontend] node_modules missing; running: npm install"
  npm install
fi

exec npm run dev -- --host "$VITE_HOST" --port "$VITE_PORT"

