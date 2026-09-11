# Local Execution, ECS Artifacts

## Endpoints and configuration

- Local submissions, queue, builds and E2E: `http://127.0.0.1/` (loopback alias for port 8788).
- Read-only ECS archive: `http://119.8.233.58:8080/`. Open the run's authorized `web_url`, not the bare root. HTTP was explicitly requested to avoid certificate requirements; it is not encrypted. HTTPS remains available as an optional endpoint.
- `.runtime/pipeline-local.json`: local execution URLs and repository allowlist.
- `.runtime/pipeline-server.json`: remote base URL, SSH destination, publishing selection and view token. Keep private.
- `.runtime/pipeline-agent.json`: compatibility entry for the installed review skill; calls the local URL, returns the ECS run URL.

ECS does not run builds, Docker, Codex, GitHub authentication or a queue for this new service. Existing ECS services are unchanged. Port 80 is an unrelated build-package service and is deliberately not replaced.

## Start / update

From PowerShell, run the existing `mattermost-microservice/infra/pr-e2e/start-pipeline.ps1` entry. WSL must be running; systemd enables the services on WSL startup, not on Windows startup by itself.

To redeploy the report application (not the CCE application images):

```powershell
wsl -d Ubuntu-24.04 -- python3 /mnt/d/code/welink-micro/pr-pipeline-hub/configure_share.py
wsl -d Ubuntu-24.04 -- systemctl restart pr-e2e-local-hub pr-e2e-publisher pr-e2e-local-url
```

Only restart the Hub when its queue is idle; existing running tests are interrupted by a restart. Candidate CCE builds continue to use the existing E2E runner and frozen source/image inputs.

Local systemd units: `pr-e2e-local-hub`, `pr-e2e-publisher`, `pr-e2e-local-url`.
Remote unit: `pr-e2e-share`. Remote code: `/opt/pr-e2e-share`; data: `/var/lib/pr-e2e-share`.

## Publishing semantics

The publisher checks local runs every 10 seconds, starting with run `20260908-203211-6bb7f6`. Queued/running snapshots contain state, stage logs and step events. Completed snapshots also contain reports, videos, screenshots, traces and version manifests. Upload duration adds to the polling interval.

Uploads use authenticated SSH, validate per-file SHA-256, then atomically switch the server's run snapshot. Failures retry automatically without marking local tests as failed. The local page shows upload status separately. Uploaded reports remain available when the local runner is offline; unfinished snapshots retain their last synchronization timestamp and do not imply a live runner.

Private directories, source checkouts, model/GitHub credentials, environment files and symlinks are excluded. Raw Playwright artifacts can contain test-session data and require an authorized link. Treat a sharing URL as a bearer credential. HTTP exposes traffic to network intermediaries; restrict sharing to trusted networks and recipients. The server exchanges its query token for an HttpOnly cookie; Secure is enabled on HTTPS, with a separate cookie name for HTTP. It does not log bearer URLs and rejects build submissions.

HTTP report pages and videos work. Download Trace ZIPs from the pipeline page for local inspection; online Playwright Trace viewing requires a secure browser context. Public HTTP desktop/mobile checks verified reports, videos and a real Trace ZIP download. Local Windows proxy bypass now includes only the ECS IP in addition to the previous list; the previous settings are backed up in `.runtime/proxy-before-ecs-direct.json`.

## Initial verification (2026-09-08)

- Published PR #101 run `20260908-203211-6bb7f6`: 194 files, approximately 199 MiB before transfer compression.
- Existing real E2E result preserved: baseline E01/E02/E03 and candidate E01/E02/E03 passed. This publication is not a new test run and does not certify a later PR revision.
- Desktop/mobile browser checks against the deployed ECS viewer through an SSH test tunnel: node page, six report links, report loading, video metadata and actual Trace viewer loading passed; anonymous requests blocked. This does not prove public reachability.
- 20 local unit/contract tests passed.
- Public TCP 443 was initially blocked. After the user opened the security group, direct public HTTPS verification passed at 2026-09-08 22:14 CST. The robot's normal health check now reports `shareable_links=true`.
- Direct public desktop/mobile browser verification also passed: six report links, report content, video metadata and actual Trace loading, with anonymous requests blocked. The browser test pins the deployed self-signed certificate and bypasses the workstation proxy; this does not mean other browsers automatically trust the certificate.
- HTTPS currently uses a self-signed IP certificate. Browser trust is required until replaced with a trusted certificate. The local health probe pins this certificate and will not report `shareable_links=true` while public reachability fails.

The group bot uses the existing skill and local Hub configuration. No new group message was sent during this deployment, and group-trigger-to-reply acceptance has not been reverified.
