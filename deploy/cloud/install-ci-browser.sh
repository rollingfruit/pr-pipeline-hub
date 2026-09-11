#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -un)" != pr-e2e ]; then
    echo 'Run as pr-e2e inside pr-e2e.slice' >&2
    exit 1
fi
export PATH="/usr/local/node-v24.11.1-linux-x64/bin:$PATH"
destination=/var/lib/pr-e2e/state/playwright
mkdir -p "$destination"
cp /opt/pr-pipeline-ci/stack/playwright/package.json /opt/pr-pipeline-ci/stack/playwright/package-lock.json "$destination/"
cd "$destination"
npm ci --ignore-scripts --no-audit --no-fund
./node_modules/.bin/playwright install chromium
