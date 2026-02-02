#!/usr/bin/env bash
set -euo pipefail

# Run PerfOpt_v0 HTTP backend (MuJoCo + Optuna) for the frontend to call.
#
# Usage:
#   scripts/dev_backend.sh
#   PERFOPT_PORT=8080 scripts/dev_backend.sh
#   PERFOPT_HOST=127.0.0.1 PERFOPT_PORT=8080 PERFOPT_CONDA_ENV=mjwarp_env scripts/dev_backend.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PY_DEFAULT="$ROOT_DIR/../PerfOpt_v0/scripts/perfopt_http_backend.py"

PERFOPT_HOST="${PERFOPT_HOST:-127.0.0.1}"
PERFOPT_PORT="${PERFOPT_PORT:-8080}"
PERFOPT_CONDA_ENV="${PERFOPT_CONDA_ENV:-mjwarp_env}"
PERFOPT_BACKEND_PY="${PERFOPT_BACKEND_PY:-$BACKEND_PY_DEFAULT}"

usage() {
  cat <<EOF
Usage:
  ./scripts/dev_backend.sh

Options (optional; defaults shown):
  --host <host>         (default: ${PERFOPT_HOST})
  --port <port>         (default: ${PERFOPT_PORT})
  --env <conda_env>     (default: ${PERFOPT_CONDA_ENV})
  --py <backend_py>     (default: ${PERFOPT_BACKEND_PY})
  -h, --help            Show help

Environment variables (also supported):
  PERFOPT_HOST, PERFOPT_PORT, PERFOPT_CONDA_ENV, PERFOPT_BACKEND_PY
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      PERFOPT_HOST="${2:-}"; shift 2;;
    --port)
      PERFOPT_PORT="${2:-}"; shift 2;;
    --env)
      PERFOPT_CONDA_ENV="${2:-}"; shift 2;;
    --py)
      PERFOPT_BACKEND_PY="${2:-}"; shift 2;;
    -h|--help)
      usage; exit 0;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2;;
  esac
done

if [[ -z "${PERFOPT_HOST}" ]]; then
  echo "--host is required" >&2
  exit 2
fi
if [[ ! "${PERFOPT_PORT}" =~ ^[0-9]+$ ]] || (( PERFOPT_PORT < 1 || PERFOPT_PORT > 65535 )); then
  echo "--port must be 1..65535 (got: ${PERFOPT_PORT})" >&2
  exit 2
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "conda not found. Please install/initialize conda first." >&2
  exit 1
fi

if [[ ! -f "$PERFOPT_BACKEND_PY" ]]; then
  echo "Backend script not found: $PERFOPT_BACKEND_PY" >&2
  echo "Set PERFOPT_BACKEND_PY to the correct path." >&2
  exit 1
fi

echo "[backend] conda env: $PERFOPT_CONDA_ENV"
echo "[backend] host: $PERFOPT_HOST"
echo "[backend] port: $PERFOPT_PORT"
echo "[backend] script: $PERFOPT_BACKEND_PY"
echo
echo "[backend] health will be: http://${PERFOPT_HOST}:${PERFOPT_PORT}/health"
echo

export PERFOPT_HOST PERFOPT_PORT
exec conda run -n "$PERFOPT_CONDA_ENV" python "$PERFOPT_BACKEND_PY"
