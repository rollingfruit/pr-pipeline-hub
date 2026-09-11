#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"
BIN="$RUNTIME_DIR/bin/cloudflared"
PID_FILE="$RUNTIME_DIR/tunnel.pid"
LOG_FILE="$RUNTIME_DIR/tunnel.log"
ENV_FILE="$RUNTIME_DIR/pipeline.env"
AGENT_CONFIG="$RUNTIME_DIR/pipeline-agent.json"
ORIGIN="${PIPELINE_HUB_ORIGIN:-http://127.0.0.1:8787}"

mkdir -p "$RUNTIME_DIR/bin"

is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

public_url() {
  grep -Eo 'https://[-a-z0-9]+\.trycloudflare\.com' "$LOG_FILE" 2>/dev/null |
    grep -v '^https://api\.trycloudflare\.com$' |
    tail -1
}

wait_for_url() {
  local url=""
  for _ in {1..60}; do
    url="$(public_url || true)"
    if [[ -n "$url" ]] && grep -q 'Registered tunnel connection' "$LOG_FILE" 2>/dev/null; then
      printf '%s\n' "$url"
      return 0
    fi
    is_running || break
    sleep 1
  done
  cat "$LOG_FILE" >&2 || true
  return 1
}

write_config() {
  local url="$1"
  local trigger_token view_token
  trigger_token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  view_token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  umask 077
  printf '%s\n' \
    "PIPELINE_PUBLIC_BASE_URL=$url" \
    "PIPELINE_TRIGGER_TOKEN=$trigger_token" \
    "PIPELINE_VIEW_TOKEN=$view_token" \
    "PIPELINE_EMBED_VIEW_TOKEN=true" >"$ENV_FILE"
  if [[ -n "${PIPELINE_WINDOWS_PROXY:-}" ]]; then
    printf '%s\n' "PIPELINE_WINDOWS_PROXY=$PIPELINE_WINDOWS_PROXY" >>"$ENV_FILE"
  fi
  python3 - "$AGENT_CONFIG" "$trigger_token" "$view_token" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({
    "local_base_url": "http://127.0.0.1:8787",
    "trigger_token": sys.argv[2],
    "view_token": sys.argv[3],
}, indent=2), encoding="utf-8")
PY
  chmod 600 "$ENV_FILE" "$AGENT_CONFIG"
}

start_tunnel() {
  if [[ ! -x "$BIN" ]]; then
    echo "Missing $BIN; install the official cloudflared Linux amd64 binary first." >&2
    exit 1
  fi
  if is_running; then
    echo "Quick Tunnel already running: $(public_url)"
    return 0
  fi
  local url=""
  for attempt in 1 2 3; do
    : >"$LOG_FILE"
    nohup "$BIN" tunnel --no-autoupdate --protocol http2 --url "$ORIGIN" >"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
    if url="$(wait_for_url)"; then
      break
    fi
    if is_running; then kill "$(cat "$PID_FILE")" || true; fi
    rm -f "$PID_FILE"
    echo "Quick Tunnel attempt $attempt failed; retrying..." >&2
    sleep "$((attempt * 2))"
  done
  if [[ -z "$url" ]]; then
    echo "Unable to establish a Quick Tunnel after 3 attempts" >&2
    exit 1
  fi
  write_config "$url"
  "$ROOT_DIR/scripts/server.sh" restart
  echo "Quick Tunnel started: $url"
}

stop_tunnel() {
  if is_running; then
    kill "$(cat "$PID_FILE")"
    for _ in {1..20}; do
      is_running || break
      sleep 0.2
    done
  fi
  rm -f "$PID_FILE"
  echo "Quick Tunnel stopped"
}

case "${1:-start}" in
  start) start_tunnel ;;
  restart) stop_tunnel; start_tunnel ;;
  stop) stop_tunnel ;;
  status)
    if is_running; then
      echo "running PID=$(cat "$PID_FILE") URL=$(public_url)"
    else
      echo "stopped"
      exit 1
    fi
    ;;
  logs) tail -n 200 -f "$LOG_FILE" ;;
  *) echo "Usage: $0 {start|restart|stop|status|logs}" >&2; exit 2 ;;
esac
