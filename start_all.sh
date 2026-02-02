#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/industrial-robot-arm-optimizer-good"
BACKEND_DIR="$ROOT_DIR/PerfOpt_v0"
BACKEND_PY="${BACKEND_PY:-$BACKEND_DIR/scripts/perfopt_http_backend.py}"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8080}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
FRONTEND_URL="http://localhost:${FRONTEND_PORT}"

BACKEND_CONDA_ENV="${BACKEND_CONDA_ENV:-mjwarp_env}"
BACKEND_LOG="${BACKEND_LOG:-$BACKEND_DIR/artifacts/perfopt_http_backend.stdout.log}"
BACKEND_PID_FILE="${BACKEND_PID_FILE:-$BACKEND_DIR/artifacts/perfopt_http_backend.pid}"
FRONTEND_LOG="${FRONTEND_LOG:-$FRONTEND_DIR/artifacts/vite.stdout.log}"
FRONTEND_PID_FILE="${FRONTEND_PID_FILE:-$FRONTEND_DIR/artifacts/vite.pid}"

log() {
  printf "[%s] %s\n" "$(date +'%F %T')" "$*"
}

check_health() {
  curl -fsS "${BACKEND_URL}/health" >/dev/null 2>&1
}

kill_port_occupant() {
  local port="$1"
  local killed=0
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [[ -n "${pids:-}" ]]; then
      log "Port ${port} in use by: ${pids} (killing)"
      kill ${pids} 2>/dev/null || true
      sleep 0.5
      for pid in ${pids}; do
        if kill -0 "$pid" 2>/dev/null; then
          log "Force killing pid=$pid"
          kill -9 "$pid" 2>/dev/null || true
        fi
      done
      killed=1
    fi
  fi
  if [[ "$killed" -eq 0 ]] && command -v fuser >/dev/null 2>&1; then
    if fuser -n tcp "$port" >/dev/null 2>&1; then
      log "Port ${port} in use (fuser) - killing"
      fuser -k -n tcp "$port" >/dev/null 2>&1 || true
      killed=1
    fi
  fi
  return 0
}

start_backend() {
  mkdir -p "$(dirname "$BACKEND_LOG")"

  if check_health; then
    log "Backend already healthy at ${BACKEND_URL}"
    return 0
  fi

  # If port is occupied but backend is unhealthy, kill the occupant to ensure clean start.
  if ! check_health; then
    if command -v lsof >/dev/null 2>&1; then
      if lsof -ti tcp:"$BACKEND_PORT" >/dev/null 2>&1; then
        log "Backend port ${BACKEND_PORT} is occupied and unhealthy; force stopping occupant"
        kill_port_occupant "$BACKEND_PORT"
      fi
    elif command -v fuser >/dev/null 2>&1; then
      if fuser -n tcp "$BACKEND_PORT" >/dev/null 2>&1; then
        log "Backend port ${BACKEND_PORT} is occupied and unhealthy; force stopping occupant"
        kill_port_occupant "$BACKEND_PORT"
      fi
    fi
  fi

  log "Starting backend: ${BACKEND_PY}"
  if [[ "${CONDA_DEFAULT_ENV:-}" == "$BACKEND_CONDA_ENV" ]]; then
    PERFOPT_HOST="$BACKEND_HOST" PERFOPT_PORT="$BACKEND_PORT" \
      nohup python "$BACKEND_PY" >>"$BACKEND_LOG" 2>&1 &
    echo $! >"$BACKEND_PID_FILE"
    return 0
  fi

  if [[ "${FORCE_CONDA_RUN:-1}" == "1" ]]; then
    if command -v conda >/dev/null 2>&1; then
      PERFOPT_HOST="$BACKEND_HOST" PERFOPT_PORT="$BACKEND_PORT" \
        nohup conda run -n "$BACKEND_CONDA_ENV" python "$BACKEND_PY" \
        >>"$BACKEND_LOG" 2>&1 &
      echo $! >"$BACKEND_PID_FILE"
      return 0
    fi
  fi

  log "Backend requires active conda env: ${BACKEND_CONDA_ENV}"
  log "Current CONDA_DEFAULT_ENV=${CONDA_DEFAULT_ENV:-<none>}"
  log "Run: conda activate ${BACKEND_CONDA_ENV} (or set FORCE_CONDA_RUN=1)"
  return 1

  local retries=40
  local sleep_s=0.5
  for _ in $(seq 1 "$retries"); do
    if check_health; then
      log "Backend healthy at ${BACKEND_URL}"
      return 0
    fi
    sleep "$sleep_s"
  done

  log "Backend failed to become healthy. Check log: $BACKEND_LOG"
  return 1
}

start_frontend() {
  mkdir -p "$(dirname "$FRONTEND_LOG")"
  # Ensure frontend port is free before starting.
  kill_port_occupant "$FRONTEND_PORT"
  log "Starting frontend (no terminal): $FRONTEND_DIR"
  nohup bash -lc "cd \"$FRONTEND_DIR\" && npm run dev -- --port ${FRONTEND_PORT} --host 127.0.0.1" \
    >>"$FRONTEND_LOG" 2>&1 &
  echo $! >"$FRONTEND_PID_FILE"
}

open_browser() {
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$FRONTEND_URL" >/dev/null 2>&1 &
    return 0
  fi
  log "Cannot open browser automatically. Open: $FRONTEND_URL"
  return 1
}

main() {
  log "Project root: $ROOT_DIR"
  start_backend
  start_frontend
  sleep 1
  open_browser
  log "Done."
}

main "$@"
