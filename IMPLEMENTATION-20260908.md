# Local PR E2E Integration Verification

## PR #101 Acceptance Completed

Run `20260908-203211-6bb7f6` completed successfully in 469 seconds:
http://127.0.0.1:8788/runs/20260908-203211-6bb7f6

- Head `4314961e2239759a34481300de1a59e6e9b8905d`, live base `ac96791fa1684b650ade402b2ddf800d867ed6d9`.
- Candidate tree `c6b2ad743b29678859f8c560f803e6cb690e9243`.
- Candidate Governance image `sha256:f85bad08d4315722f28bf2af7fc6bc225b4d93c2a33eac6d9084784cbbb88de1`.
- E01/E02/E03 passed on BOTH baseline and candidate: six browser executions with trace, video, screenshots and correlation evidence. PR96-specific DR suites were not part of this PR101 core acceptance.
- GitHub `newlink/e2e-local=success`, status ID `53734583136`, independently verified through the GitHub API.
- Supplemental `go test ./internal/agentreply ./internal/coordinator -count=1 -timeout=120s` passed against the frozen candidate; logs are under this run's `artifacts/supplemental/`.
- Current local product: http://localhost:18066. Candidate environment remains running.
- Earlier attempts remain failed: a missing shared CCE runtime image and a baseline Codex cloud-config/network timeout. They were not edited into successes.
- The shared Ubuntu runtime was imported from the authorized CCE builder and its layers/configuration verified. Import provenance is in the WSL build-inputs cache.

The form now offers explicit PR-head diagnosis, which is non-acceptance and never writes GitHub status. API guards, unit tests and desktop/mobile form checks passed; an actual conflict-head browser diagnostic has not yet been executed. Formal PR101 acceptance used a clean merge candidate, not a conflict bypass.

Production NewLink group trigger/delivery and a public URL for these local runs remain unverified. No group test message was sent during this verification.

## Observed Result

- PR: https://github.com/rollingfruit/agent-governance-gw/pull/96
- Head: `26ef54c2a9ca59ce590730242796486f6118d332`
- Live main: `ac96791fa1684b650ade402b2ddf800d867ed6d9`
- The PR API reports the older base `2a1be5a1`; acceptance now resolves the live branch ref independently and checks it against fetched Git objects.
- Formal run: http://127.0.0.1:8788/runs/20260908-200003-9c29e1
- GitHub `newlink/e2e-local`: `failure`, status ID `53732110787`, verified via GitHub API.
- Merge conflicts: `docs/openapi.source.json`, `internal/coordinator/service.go`, `internal/coordinator/types.go`.
- Candidate build and browser suites did NOT execute. Existing baseline diagnostic successes are not candidate acceptance evidence.

## Queue Verification

Diagnostic run `20260908-200004-83c596` started at `2026-09-08T12:00:27Z`, after the formal run finished. It completed at `12:00:47Z` and did not write GitHub status. Both retained their actual merge-conflict logs.

The Hub has one worker, persists queued submissions, restores queued work after restart, and deduplicates `request_id`. The E2E environment additionally uses a shared WSL file lock across Hub data directories. A running task interrupted by restart is not treated as passed or automatically replayed. GitHub reconciliation for a process killed mid-run still needs implementation.

## Build Integration

Baseline images can be reused only when full source SHA, successful build provenance, and Docker image ID match. Compose receives immutable image IDs. Missing images use the tested CCE build helper with a fixed revision. Candidate builds archive the actual merge tree and keep their own build manifest. Only explicitly owned test environments are stopped when switching deployments; evidence remains outside container volumes.

These newly connected post-merge stages still require a conflict-free PR for end-to-end verification.

## Group Integration Status

`scripts/group-e2e.ps1` submits the full E2E profile with a group/message idempotency key and returns queued/final result envelopes. It requires a dedicated endpoint configuration with `base_url`, `trigger_token`, `view_token`, verified `group_id`, and `bot_name=xiao-commitor`. It rejects non-shareable result URLs.

This script is NOT a NewLink message listener and does not itself send group replies. The production robot binding, authenticated public local-run view, and queued/final group message delivery have NOT been configured or verified. Existing ECS code-review routing has deliberately not been redirected to an unverified or unauthenticated local endpoint. Local E2E traces and test credentials have not been published.

Next acceptance: resolve PR merge conflicts without guessing business behavior; run baseline and candidate suites; configure the actual group ingress/delivery integration and authenticated public view; send two real mentions in the target group and verify FIFO plus both completion links.
