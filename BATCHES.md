# Cross-repository batch validation

## Entry Points

- Local authenticated editor: http://127.0.0.1:8793/
- ECS public read-only dashboard: http://119.8.233.58:8080/batches
- Execution history: http://119.8.233.58:8080/history
- Existing `/runs/{id}` and artifact paths remain valid.
- Repeatable local startup: `scripts/start-batches.ps1`. This starts the existing model bridge/proxy and services and keeps WSL alive. It does not restart an active task or install a scheduled task.

## Operation

The 11 repository monitors only discover PR activity. Webhook/polling does not enqueue builds. Choose one open, non-draft PR per supported repository in the local editor, resolve current versions, select a nonempty implemented suite set, then submit. Editing PR links invalidates the parsed selection. Public-service and observability remain unsupported for candidate builds.

E01/E02/E03, baseline comparison and GitHub writeback default on. Code review defaults off; this does not disable the real Codex runtime used by E2E. Optional review suggestions do not change the submitted test set. Disabling baseline comparison or omitting core suites gives partial validation, not merge approval.

Batch metadata and member versions are persisted in PostgreSQL. Batches use the same global claim lock, lease and local environment lock as legacy tasks. Repeated submission IDs are idempotent. A new submission creates a separate attempt and keeps previous evidence. Version changes/closure invalidate results. Conflicts stop candidate preparation. Recovery of an interrupted worker requires `recover_local_worker.py <id>` and checks the local environment lock and owned processes before closing the old task with error statuses.

ECS has no anonymous execution endpoint. Local POSTs require the existing origin/host checks and selection token; ECS writes use SSH RPC and worker authentication. HTTP reports are publicly readable by design, including private repository evidence. This is an explicit demonstration limitation, not an enterprise confidentiality boundary.

## Verification Recorded On 2026-09-10

- 40 Python tests and 13 isolated PostgreSQL/API tests passed. These are platform tests, not real product E2E evidence.
- Playwright exercised real local form parsing/submission, ECS batch navigation and tabs, 1440/1920/390 layouts, and denial of anonymous writes.
- Real selected combination: agent-governance-gw #104 (`98c25d51dad788ba829ae26526dbf9f42503c795`, base `95742b4bf9e414886bc1863aa2cd93b4c8a1e2ba`) and semantic-schedule #161 (`15e37b552bd0787bc41dc44014a7f5517d1a702c`, base `0200d7cb82ec3a3f843e5bfbb66668b86d44e414`). Both were open, non-draft, mergeable and had no unapproved build-entry changes when submitted.
- Real run: http://119.8.233.58:8080/batches/batch-8a5c64a9-3c52-49e2-9994-d18ef2d6d3d3
- Parsing, version checks and joint merge preparation ran. The environment build failed because required `local/ai-python-build:3.11.15-v1` and `local/ai-python-runtime:3.11.15-apt-v1` images were unavailable; Docker attempted a public registry resolution. E01/E02/E03 were not executed, so baseline/candidate acceptance is NOT passed.
- GitHub comments: https://github.com/rollingfruit/agent-governance-gw/pull/104#issuecomment-5611650678 and https://github.com/rollingfruit/semantic-schedule/pull/161#issuecomment-5611656831 . Environment error was written, not success or APPROVE.
- Earlier interrupted/encoding/network failures remain in history. They were not relabeled as passes.

## Remaining Acceptance Work

Provision the exact shared base-image inputs required by the frozen service versions using the CCE base build package, record their provenance, and run a fresh batch. Do not retag unrelated images to manufacture compatibility. Real joint baseline/candidate success and product assertion-failure scenarios still need acceptance after this environment blocker is removed. Optional code review has platform coverage but was intentionally not invoked in these real runs. NewLink delivery is not an acceptance condition of this release.

Untrusted candidate code is not strongly isolated from the WSL build host. High-risk build changes require local approval. The runtime uses the existing subscribed CLI model adapter, not identical CCE model-provider transport. External registry availability, mutable upstream tags, host restarts and finite disk space remain operational risks. Keep this release in observation mode.
