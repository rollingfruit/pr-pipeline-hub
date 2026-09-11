#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"
PID_FILE="$RUNTIME_DIR/server.pid"
LOG_FILE="$RUNTIME_DIR/server.log"
ENV_FILE="$RUNTIME_DIR/pipeline.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

PORT="${PIPELINE_PORT:-8787}"
export PIPELINE_DATA_DIR="${PIPELINE_DATA_DIR:-$RUNTIME_DIR/data}"
export PIPELINE_GOPROXY="${PIPELINE_GOPROXY:-https://goproxy.cn,direct}"

mkdir -p "$RUNTIME_DIR"

is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

case "${1:-start}" in
  start)
    if is_running; then
      echo "PR Pipeline Hub already running with PID $(cat "$PID_FILE")"
      exit 0
    fi
    nohup python3 "$ROOT_DIR/pr_pipeline_hub.py" --port "$PORT" >"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
    sleep 1
    if ! is_running; then
      cat "$LOG_FILE"
      exit 1
    fi
    echo "PR Pipeline Hub started: ${PIPELINE_PUBLIC_BASE_URL:-http://127.0.0.1:$PORT}"
    ;;
  stop)
    if is_running; then
      kill "$(cat "$PID_FILE")"
      for _ in {1..20}; do
        is_running || break
        sleep 0.2
      done
    fi
    rm -f "$PID_FILE"
    echo "PR Pipeline Hub stopped"
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status)
    if is_running; then
      echo "running PID=$(cat "$PID_FILE") URL=http://127.0.0.1:$PORT"
    else
      echo "stopped"
      exit 1
    fi
    ;;
  logs)
    tail -n 200 -f "$LOG_FILE"
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs}" >&2
    exit 2
    ;;
esac
