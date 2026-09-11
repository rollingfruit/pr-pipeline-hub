#!/usr/bin/env bash
set -euo pipefail
export PATH="/usr/local/node-v24.11.1-linux-x64/bin:$PATH"
npm install --prefix /opt/pr-pipeline-tools/opencode opencode-ai@1.18.30 --no-audit --no-fund
ln -sfn /opt/pr-pipeline-tools/opencode/node_modules/.bin/opencode /opt/pr-pipeline-tools/bin/opencode
