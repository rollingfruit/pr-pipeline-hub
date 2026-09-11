# PR Pipeline Hub

`PR Pipeline Hub` runs private GitHub pull request checks on a local WSL host.
It exposes a small HTTP API for Multica/Codex and a live browser view for team
members. GitHub Actions is not required.

## Current stages

1. Resolve the PR and create an isolated Git worktree.
2. Merge the latest base branch into the isolated worktree without committing.
3. Check Go formatting for files added or changed by the PR.
4. Run `go vet ./...`.
5. Run `go test ./...`.
6. Run `scripts/verify-change-docs.sh <base-sha>`.

Both open and merged PRs are accepted. A merged PR is a post-merge verification
run, not a merge gate; the page records `pr_state` so the Agent can describe the
result accurately. For merged PRs, changed-file and documentation checks compare
against the parent of the first PR commit instead of today's base branch.

The default repository allowlist contains only
`rollingfruit/agent-governance-gw`. Add comma-separated repositories with
`PIPELINE_ALLOWED_REPOS`.

## WSL setup

The server can reuse GitHub CLI authenticated on Windows. Confirm that this
works from WSL before starting:

```bash
"/mnt/c/Users/XIAO/AppData/Local/Programs/GitHub CLI/gh.exe" auth status
```

Install the Go toolchain and start the server:

```bash
cd /mnt/d/code/welink-micro/pr-pipeline-hub
bash scripts/bootstrap-wsl.sh
bash scripts/server.sh start
```

The local start script defaults `PIPELINE_GOPROXY` to
`https://goproxy.cn,direct` because the current WSL NAT cannot reach
`proxy.golang.org`. Set it to the company module proxy when one is available.

Open `http://127.0.0.1:8787`. Windows normally forwards WSL localhost ports.

## Huawei ECS deployment

Package the source without `.runtime`, upload it to the server, extract it to a
versioned directory under `/opt/pr-pipeline-hub/releases`, then run:

```bash
bash deploy/huawei-ecs/install.sh /opt/pr-pipeline-hub/releases/<release-id>
```

The installer creates the `prpipeline` service account, installs GitHub CLI and
Nginx, preserves existing API tokens, switches `/opt/pr-pipeline-hub/current`,
and enables both systemd services. Authenticate the private-repository account
once as the service user:

```bash
runuser -u prpipeline -- env HOME=/var/lib/pr-pipeline-hub \
  gh auth login --hostname github.com --git-protocol https --web
```

The current ECS endpoint is `http://119.8.233.58`. The Huawei Cloud security
group must permit inbound TCP port 80 for intended viewers.

To expose the page to machines on a trusted corporate LAN, first configure
`PIPELINE_TRIGGER_TOKEN` and `PIPELINE_VIEW_TOKEN`, then run an elevated
PowerShell window:

```powershell
& D:\code\welink-micro\pr-pipeline-hub\scripts\expose-lan.ps1 install
```

WSL's NAT address can change after a WSL restart, so rerun `install` when that
happens. For access across the public internet, place the service behind an
authenticated reverse tunnel or SSO proxy; do not expose private PR logs with
an unauthenticated quick tunnel.

## Agent trigger

From PowerShell:

```powershell
& D:\code\welink-micro\pr-pipeline-hub\scripts\trigger-pr.ps1 `
  -PrUrl https://github.com/rollingfruit/agent-governance-gw/pull/70 `
  -RequestedBy github-reviewer
```

The response includes `web_url`. The Agent should send that URL to the group
immediately, poll `GET /api/runs/{id}`, and fetch failed output from
`GET /api/runs/{id}/stages/{stage}/log`.

## Access control

For local development, API tokens are optional. Before exposing the service
outside the machine, set both values:

```bash
export PIPELINE_TRIGGER_TOKEN="a-long-random-trigger-token"
export PIPELINE_VIEW_TOKEN="a-separate-read-only-token"
export PIPELINE_PUBLIC_BASE_URL="https://pipeline.example.internal"
```

Persist local service settings in `.runtime/pipeline.env`; `scripts/server.sh`
loads that file on every start. When there is no SSO proxy yet, set
`PIPELINE_EMBED_VIEW_TOKEN=true` to include the read-only token in each returned
group link. Anyone holding that URL can read the run, so prefer an authenticated
stable tunnel and leave token embedding disabled in production.

For a stable public development URL, install the official Linux amd64 ngrok
agent at `.runtime/bin/ngrok`, connect the account once, and start the tunnel:

```bash
PowerShell -File scripts/start-ngrok.ps1 auth -Authtoken <token-from-ngrok-dashboard>
PowerShell -File scripts/start-ngrok.ps1 start
```

The script discovers the account's assigned HTTPS development domain, updates
`PIPELINE_PUBLIC_BASE_URL`, preserves the application tokens, writes the local
Agent config, and restarts the Hub. Use `status`, `restart`, `stop`, or `logs`
for lifecycle management. Set `NGROK_URL` before `start` when the account has a
specific reserved domain.

Agent requests send `X-Pipeline-Token`. Browser links may append
`?access_token=<PIPELINE_VIEW_TOKEN>`; an authenticated reverse proxy or SSO is
preferred for production because private source paths and logs are sensitive.

## Conflicts And Diagnostic Runs

The E2E form defaults to the merge candidate. A merge conflict fails acceptance;
it is never resolved by blindly choosing one side. Selecting `PR head` runs the
PR version without merging the target branch. This requires `diagnostic: true`,
cannot be full acceptance, and never writes a successful merge check to GitHub.

API example for explicit head-only diagnosis:

```json
{"pr_url":"https://github.com/rollingfruit/agent-governance-gw/pull/101","profile":"browser-e2e","source_mode":"pr-head","diagnostic":true,"suites":["E01","E02","E03"]}
```

Do not skip build failures, missing authentication, unavailable models or failed
assertions. A smaller selected suite can be run as a debug check, but cannot
overwrite `newlink/e2e-local`. Preserve the unsuccessful full run as evidence.

When the CCE baseline starts requiring `local/ai-ubuntu-runtime:22.04-apt-v1`,
run `mattermost-microservice/infra/pr-e2e/sync-runtime-image.py` in WSL. It imports
the builder's image via SSH, verifies filesystem layers and runtime configuration,
and records both server/local image identities and the archive checksum.

## Tests

```bash
cd /mnt/d/code/welink-micro/pr-pipeline-hub
python3 -m unittest discover -s tests -v
```
