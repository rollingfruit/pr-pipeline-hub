# PR Pipeline Hub implementation checkpoint

## Deployed

- ECS `http://119.8.233.58:8080`: React/TypeScript dashboard, detail/overview/capability/environment views.
- FastAPI on loopback 8792, PostgreSQL on loopback 5439. Existing archive files and original viewer service retained.
- `/runs/{id}` and legacy artifact URLs preserved. View token exchanged for an HttpOnly cookie. Anonymous archive access denied.
- Signed, size-limited Webhook endpoint and repository-ID allowlist. Durable event inbox, FIFO review queue, fenced leases, delivery outbox.
- 12 canonical repository identities verified against GitHub and registered. No historical PR scans.
- Existing PR #101 baseline/candidate E01/E02/E03 artifacts displayed without changing historical conclusions.

## Implemented, not activated end to end

Local authenticated polling is now active for `rollingfruit/agent-governance-gw`, every 60 seconds, independently of Webhook ingress. See LOCAL-PR-MONITOR.md. The monitor posts observed transitions to the ECS queue but does not bypass the unfinished Agent/Worker integration.

- SSH-only Worker RPC and optional `PIPELINE_CONTROL_MODE=ecs` runner integration.
- Independent GitHub status/comment delivery reconciliation and retry. NewLink delivery explicitly reports missing integration instead of claiming success.
- Versioned core/path selection; PR #96 hardcoding removed. Controlled runs block risky build/install changes.
- Worker lease loss stops further stages and suppresses direct status writes; interrupted queue slots require explicit local reconciliation.

Do not enable `PIPELINE_CONTROL_MODE=ecs` yet. Local default remains the existing worker. GitHub repository Webhooks are now ACTIVE for 12 repositories, but real delivery is blocked at the network layer (see WEBHOOK-ACTIVATION-20260909.md). The control queue is not yet authoritative for local/manual submissions.

## Remaining Acceptance Blockers

1. Confirm AgentServer outbound endpoint/auth configuration and real group message/task acknowledgments; implement the two-phase xiao-commitor review contract.
2. Complete public-service shared runtime rebuild mapping and observability Compose mapping. Identity registration is not build/E2E verification.
3. Freeze all harness, dependencies, build assets and configuration; complete cache identities and restart recovery checks.
4. Finish local submission compatibility/idempotency and approved high-risk rerun entry, then switch to one ECS-authoritative queue.
5. Activate idempotent repository Webhooks and create an isolated, unmerged acceptance PR. Verify GitHub event, local execution, artifact hash, comment and NewLink URL together.
6. Complete requested real failure matrix, including model/Daemon offline, candidate/baseline failures and delivery recovery. Unit fixtures do not certify these integrations.

## Verification

- Runner/delivery unit suite: `python3 -m unittest discover -s tests -v` (23 tests).
- PostgreSQL/API tests: `python -m unittest -v test_control` with a test-capable DSN. Creates/drops a unique test schema, not production records (10 tests).
- Windows Edge browser checks: `scripts/verify-dashboard.cjs` at 1440, 1920, 390. Uses the authorized existing report and checks real case count, tabs/logs/Trace/auth/layout, full Playwright report and video range requests.
- WSL frontend build: copy `web/package*.json`, `web/src`, `web/index.html`, `web/tsconfig.json` to `/root/pr-hub-web-build`; `npm ci && npm run build`; copy generated `dist` back to `web/dist`.
- Deploy: `python3 deploy_control.py` inside WSL. Server switch occurs only after readiness. Existing viewer remains available on loopback8791 for rollback.

## Limits

This is a deployed dashboard/control-plane checkpoint, not the completed automatic review launch. HTTP exposes bearer links and private reports in transit. PostgreSQL, Worker API and uploads are not public. No branch protection or merge operation was changed.
