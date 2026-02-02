#!/usr/bin/env bash
set -euo pipefail

# Convenience helper: prints exactly what to run in two terminals.
# We intentionally do NOT start both processes here, so you can debug them independently.

PERFOPT_HOST="${PERFOPT_HOST:-127.0.0.1}"
PERFOPT_PORT="${PERFOPT_PORT:-8080}"
PERFOPT_CONDA_ENV="${PERFOPT_CONDA_ENV:-mjwarp_env}"

echo "Terminal A (backend):"
echo "  PERFOPT_HOST=${PERFOPT_HOST} PERFOPT_PORT=${PERFOPT_PORT} PERFOPT_CONDA_ENV=${PERFOPT_CONDA_ENV} ./scripts/dev_backend.sh"
echo
echo "Terminal B (frontend):"
echo "  ./scripts/dev_frontend.sh"
echo
echo "Then open:"
echo "  http://localhost:3000/"
echo
echo "Backend health:"
echo "  curl http://${PERFOPT_HOST}:${PERFOPT_PORT}/health"

