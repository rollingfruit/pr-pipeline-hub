#!/usr/bin/env bash
set -euo pipefail
umask 077
destination="/var/backups/pr-e2e/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$destination"
tar --exclude='*.pyc' -czf "$destination/control-config.tgz" /etc/pr-pipeline-control.env /etc/nginx /etc/systemd/system/pr-pipeline-control.service /opt/pr-e2e-share
docker exec pr-pipeline-postgres sh -c 'exec pg_dumpall -U "${POSTGRES_USER:-postgres}"' | gzip > "$destination/database.sql.gz"
if [ -d /var/lib/pr-e2e-share ]; then
    tar -czf "$destination/archives.tgz" /var/lib/pr-e2e-share
fi
(cd "$destination" && sha256sum *.gz > SHA256SUMS)
printf 'Backup completed: %s\n' "$destination"
