#!/usr/bin/env bash
# Only installs the isolated engine. Never starts a queue consumer.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
test "$(id -u)" = 0
test -x /usr/bin/dockerd
test ! -e /etc/pr-e2e/docker.json || { echo 'Existing config: inspect before rerunning'; exit 1; }
if ip -4 route | grep -Eq '172\.29\.|172\.30\.250\.'; then
  echo 'Reserved E2E subnet conflicts with current routes'; exit 1
fi
getent group pr-e2e >/dev/null || groupadd --system pr-e2e
id pr-e2e >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/pr-e2e --gid pr-e2e --shell /bin/bash pr-e2e
install -d -m 0750 -o root -g pr-e2e /etc/pr-e2e
install -d -m 0755 /run/pr-e2e
install -m 0640 -o root -g pr-e2e "$HERE/docker-ci.example.json" /etc/pr-e2e/docker.json
install -m 0644 "$HERE/pr-e2e.slice" /etc/systemd/system/pr-e2e.slice
install -m 0644 "$HERE/pr-e2e-docker.service" /etc/systemd/system/pr-e2e-docker.service
install -m 0755 "$HERE/pr-e2e-network.sh" /usr/local/lib/pr-e2e-network.sh
/usr/bin/dockerd --validate --config-file=/etc/pr-e2e/docker.json
systemctl daemon-reload
systemctl start pr-e2e.slice
systemctl enable --now pr-e2e-docker
test "$(cat /sys/fs/cgroup/memory/pr.slice/pr-e2e.slice/memory.limit_in_bytes)" = 10737418240
test "$(cat /sys/fs/cgroup/cpu/pr.slice/pr-e2e.slice/cpu.cfs_quota_us)" = 200000
DOCKER_HOST=unix:///run/pr-e2e/docker.sock docker info --format '{{.DockerRootDir}} {{.CgroupDriver}}'
echo 'Engine installed; networking and workload cgroup diagnostics still required.'
