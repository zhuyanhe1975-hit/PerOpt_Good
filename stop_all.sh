#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/PerfOpt_v0"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8080}"
BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
BACKEND_PID_FILE="${BACKEND_PID_FILE:-$BACKEND_DIR/artifacts/perfopt_http_backend.pid}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
FRONTEND_DIR="$ROOT_DIR/industrial-robot-arm-optimizer-good"
FRONTEND_PID_FILE="${FRONTEND_PID_FILE:-$FRONTEND_DIR/artifacts/vite.pid}"

log() {
  printf "[%s] %s\n" "$(date +'%F %T')" "$*"
}

check_health() {
  curl -fsS "${BACKEND_URL}/health" >/dev/null 2>&1
}

stop_backend() {
  local stopped=0

  if [[ -f "$BACKEND_PID_FILE" ]]; then
    local pid
    pid="$(cat "$BACKEND_PID_FILE" 2>/dev/null || true)"
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
      log "Stopping backend pid=$pid"
      kill "$pid" 2>/dev/null || true
      sleep 0.5
      if kill -0 "$pid" 2>/dev/null; then
        log "Force killing backend pid=$pid"
        kill -9 "$pid" 2>/dev/null || true
      fi
      stopped=1
    fi
    rm -f "$BACKEND_PID_FILE"
  fi

  if check_health; then
    log "Backend still healthy; trying pkill fallback"
    pkill -f "perfopt_http_backend.py" 2>/dev/null || true
    sleep 0.5
  fi

  if check_health; then
    log "Backend still running at ${BACKEND_URL}"
    return 1
  fi

  if [[ "$stopped" -eq 1 ]]; then
    log "Backend stopped"
  else
    log "Backend was not running"
  fi
}

stop_frontend() {
  local stopped=0

  if [[ -f "$FRONTEND_PID_FILE" ]]; then
    local pid
    pid="$(cat "$FRONTEND_PID_FILE" 2>/dev/null || true)"
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
      log "Stopping frontend pid=$pid"
      kill "$pid" 2>/dev/null || true
      sleep 0.5
      if kill -0 "$pid" 2>/dev/null; then
        log "Force killing frontend pid=$pid"
        kill -9 "$pid" 2>/dev/null || true
      fi
      stopped=1
    fi
    rm -f "$FRONTEND_PID_FILE"
  fi

  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti tcp:"$FRONTEND_PORT" 2>/dev/null || true)"
    if [[ -n "${pids:-}" ]]; then
      log "Stopping frontend on port ${FRONTEND_PORT}: ${pids}"
      kill ${pids} 2>/dev/null || true
      sleep 0.5
      for pid in ${pids}; do
        if kill -0 "$pid" 2>/dev/null; then
          log "Force killing frontend pid=$pid"
          kill -9 "$pid" 2>/dev/null || true
        fi
      done
      stopped=1
    fi
  fi

  if [[ "$stopped" -eq 0 ]]; then
    pkill -f "npm run dev" 2>/dev/null || true
    pkill -f "vite" 2>/dev/null || true
  fi

  if [[ "$stopped" -eq 1 ]]; then
    log "Frontend stopped (port ${FRONTEND_PORT})"
  else
    log "Frontend stop attempted (port ${FRONTEND_PORT})"
  fi
}

stop_backend
stop_frontend
