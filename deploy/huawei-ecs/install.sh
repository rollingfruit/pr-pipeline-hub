#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(readlink -f "${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}")"
APP_ROOT=/opt/pr-pipeline-hub
DATA_DIR=/var/lib/pr-pipeline-hub
ENV_FILE=/etc/pr-pipeline-hub.env
PUBLIC_BASE_URL="${PIPELINE_PUBLIC_BASE_URL:-http://119.8.233.58}"

install_gh() {
  command -v gh >/dev/null && return
  local version archive temp_dir
  version="$(python3 - <<'PY'
import json
import urllib.request
with urllib.request.urlopen("https://api.github.com/repos/cli/cli/releases/latest", timeout=30) as response:
    print(json.load(response)["tag_name"].lstrip("v"))
PY
)"
  archive="gh_${version}_linux_amd64.tar.gz"
  temp_dir="$(mktemp -d)"
  curl -fsSL --retry 3 "https://github.com/cli/cli/releases/download/v${version}/${archive}" -o "$temp_dir/$archive"
  tar -xzf "$temp_dir/$archive" -C "$temp_dir"
  install -m 0755 "$temp_dir/gh_${version}_linux_amd64/bin/gh" /usr/local/bin/gh
  rm -rf "$temp_dir"
}

write_env() {
  local trigger_token view_token
  if [[ -f "$ENV_FILE" ]]; then
    trigger_token="$(sed -n 's/^PIPELINE_TRIGGER_TOKEN=//p' "$ENV_FILE" | head -n1)"
    view_token="$(sed -n 's/^PIPELINE_VIEW_TOKEN=//p' "$ENV_FILE" | head -n1)"
  else
    trigger_token=""
    view_token=""
  fi
  [[ -n "$trigger_token" ]] || trigger_token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  [[ -n "$view_token" ]] || view_token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  umask 077
  cat >"$ENV_FILE" <<EOF
PIPELINE_PUBLIC_BASE_URL=$PUBLIC_BASE_URL
PIPELINE_TRIGGER_TOKEN=$trigger_token
PIPELINE_VIEW_TOKEN=$view_token
PIPELINE_EMBED_VIEW_TOKEN=true
PIPELINE_ALLOWED_REPOS=rollingfruit/agent-governance-gw
PIPELINE_DATA_DIR=$DATA_DIR/data
PIPELINE_GOPROXY=https://proxy.golang.org,direct
PIPELINE_GH_CLI=/usr/local/bin/gh
PIPELINE_GIT_CLI=/usr/bin/git
PIPELINE_RUNNER_NAME=Huawei_ECS
EOF
  chmod 0600 "$ENV_FILE"
}

install_gh
dnf install -y nginx >/dev/null
id prpipeline >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --create-home --shell /sbin/nologin prpipeline
mkdir -p "$APP_ROOT" "$DATA_DIR/data"
ln -sfn "$SOURCE_DIR" "$APP_ROOT/current"
chown -R root:root "$SOURCE_DIR"
chown -R prpipeline:prpipeline "$DATA_DIR"
write_env

install -m 0644 "$SOURCE_DIR/deploy/huawei-ecs/pr-pipeline-hub.service" /etc/systemd/system/pr-pipeline-hub.service
install -m 0644 "$SOURCE_DIR/deploy/huawei-ecs/nginx-pr-pipeline-hub.conf" /etc/nginx/conf.d/pr-pipeline-hub.conf
rm -f /etc/nginx/conf.d/default.conf

systemctl daemon-reload
systemctl enable --now pr-pipeline-hub
nginx -t
systemctl enable --now nginx
systemctl restart nginx pr-pipeline-hub

for _ in {1..30}; do
  if curl -fsS http://127.0.0.1/api/health >/dev/null 2>&1; then
    echo "PR Pipeline Hub deployed: $PUBLIC_BASE_URL"
    exit 0
  fi
  sleep 0.5
done
journalctl -u pr-pipeline-hub -n 50 --no-pager >&2
exit 1
