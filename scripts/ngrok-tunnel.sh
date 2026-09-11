#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"
NGROK="$RUNTIME_DIR/bin/ngrok"
PID_FILE="$RUNTIME_DIR/ngrok.pid"
LOG_FILE="$RUNTIME_DIR/ngrok.log"
URL_FILE="$RUNTIME_DIR/ngrok.url"
ENV_FILE="$RUNTIME_DIR/pipeline.env"
AGENT_CONFIG="$RUNTIME_DIR/pipeline-agent.json"
PORT="${PIPELINE_PORT:-8787}"

is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

public_url() {
  python3 - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as response:
    tunnels = json.load(response).get("tunnels", [])
urls = [item.get("public_url", "") for item in tunnels if item.get("proto") == "https"]
if not urls:
    raise SystemExit(1)
print(urls[0])
PY
}

write_setting() {
  local key="$1" value="$2"
  mkdir -p "$RUNTIME_DIR"
  touch "$ENV_FILE"
  python3 - "$ENV_FILE" "$key" "$value" <<'PY'
import pathlib
import sys

path, key, value = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
updated = []
found = False
for line in lines:
    if line.startswith(f"{key}="):
        updated.append(f"{key}={value}")
        found = True
    else:
        updated.append(line)
if not found:
    updated.append(f"{key}={value}")
path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
}

sync_agent_config() {
  python3 - "$ENV_FILE" "$AGENT_CONFIG" <<'PY'
import json
import pathlib
import sys

env_path, config_path = map(pathlib.Path, sys.argv[1:])
values = {}
for line in env_path.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        values[key] = value
config = {
    "local_base_url": "http://127.0.0.1:8787",
    "trigger_token": values.get("PIPELINE_TRIGGER_TOKEN", ""),
    "view_token": values.get("PIPELINE_VIEW_TOKEN", ""),
    "allow_local_web_url": False,
}
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

start_tunnel() {
  [[ -x "$NGROK" ]] || { echo "ngrok binary missing: $NGROK" >&2; exit 1; }
  "$NGROK" config check >/dev/null
  if is_running; then
    echo "ngrok already running with PID $(cat "$PID_FILE")"
  else
    rm -f "$URL_FILE"
    local args=(http "http://127.0.0.1:$PORT" --log stdout --log-format json)
    [[ -n "${NGROK_URL:-}" ]] && args+=(--url "$NGROK_URL")
    nohup "$NGROK" "${args[@]}" >"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
  fi

  local url=""
  for _ in {1..40}; do
    is_running || { tail -n 80 "$LOG_FILE" >&2; exit 1; }
    url="$(public_url 2>/dev/null || true)"
    [[ -n "$url" ]] && break
    sleep 0.5
  done
  [[ -n "$url" ]] || { tail -n 80 "$LOG_FILE" >&2; exit 1; }
  printf '%s\n' "$url" >"$URL_FILE"
  write_setting PIPELINE_PUBLIC_BASE_URL "$url"
  write_setting PIPELINE_EMBED_VIEW_TOKEN true
  sync_agent_config
  "$ROOT_DIR/scripts/server.sh" restart >/dev/null
  curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null
  echo "ngrok tunnel ready: $url"
}

case "${1:-start}" in
  start) start_tunnel ;;
  restart)
    "$0" stop
    start_tunnel
    ;;
  stop)
    if is_running; then kill "$(cat "$PID_FILE")"; fi
    rm -f "$PID_FILE" "$URL_FILE"
    echo "ngrok tunnel stopped"
    ;;
  status)
    is_running || { echo "stopped"; exit 1; }
    echo "running PID=$(cat "$PID_FILE") URL=$(public_url)"
    ;;
  logs) tail -n 200 -f "$LOG_FILE" ;;
  *) echo "Usage: $0 {start|restart|stop|status|logs}" >&2; exit 2 ;;
esac
