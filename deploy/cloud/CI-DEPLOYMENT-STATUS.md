# CI deployment checkpoint: 2026-09-10

## Current state

CI Worker, authenticated editor, publisher, control API and public dashboard are active on 119.8.233.58. WSL consumer, publisher, editor and monitor are stopped. Full browser baseline/candidate acceptance is still in progress. Image builds and tool smokes are not E01/E02/E03 acceptance.

- Dashboard: http://119.8.233.58:8080/
- Authenticated submission: http://119.8.233.58:8080/submit/
- Recorded attempt: http://119.8.233.58:8080/batches/batch-batch-8652f7d4726ca3efab6f4fc1e6af2449
- This attempt stopped at the Temporal image-tag mismatch (subsequently fixed); its PR version is stale. Earlier failures remain visible.
- Code review, GitHub writeback, monitoring and NewLink delivery remain disabled.
- Gamma, CCE, kubeconfig and cloud security groups are unchanged.

## Installation

- User/group: pr-e2e; home: /var/lib/pr-e2e.
- App: /opt/pr-pipeline-ci; Python 3.12.11 venv: .venv. System Python unchanged.
- Central config: /etc/pr-e2e/config.toml; referenced credentials: /etc/pr-e2e/secrets.
- Private runtime profile: /var/lib/pr-e2e/state/settings.json, mode 0600.
- OpenCode 1.18.30 with modelarts/deepseek-v4-flash; GM uses the same real endpoint.
- Provider config: /var/lib/pr-e2e/state/opencode/opencode.json; API key is a private file reference.
- Node 24.18.0 and Go 1.25.9/1.26.5: /var/lib/pr-e2e/state/tools.
- Independent Docker socket: /run/pr-e2e/docker.sock; data: /var/lib/pr-e2e-docker.
- Cgroup: /pr.slice/pr-e2e.slice; 10 GiB memory, CPU quota 200000/100000.
- Admission: 12 GiB available memory and 60 GiB free disk. Insufficient resources wait, not PR failure.
- Bridge: e2ebr0, 172.30.250.0/24; Compose pool: 172.29.0.0/16.

## Verified so far

- Authorized GitHub credential transfer over SSH; dedicated profile reads all 11 private repositories. Root gh unchanged.
- Real Docker build/container cgroup isolation verified; original Docker and PostgreSQL remain active.
- Resource shortage diagnostic refused task admission.
- OpenCode real read-file tool smokes passed on WSL and CI with unpredictable fixtures and real tool events.
- Browser submitted Governance #105 and Schedule #155, baseline plus E01/E02/E03, code review/writeback off.
- Report and submission verified at 1440/1920/390 widths; logs visible; anonymous submission 401; public internal API 404.
- Archive upload/hash receipts work; failed batch evidence retained.
- CCE UT/build completed for all required application images. Fourteen isolated Compose containers started.
- E01 passed in 18.1 seconds with the explicitly recorded, unmerged Mattermost adapter fix below. The original adapter baseline failed.
- Legacy Python 3.11.15 bases imported from original daemon with matching IDs, not retagged from newer bases.

## Build behavior

Repository .cid/build.yaml drives real UT and CCE builds; push/deploy steps are rejected. Mattermost packaging runs in a dedicated container with only the E2E Docker socket, owned paths and allowlisted environment. Docker bind-mount exchange uses owned paths visible to both caller and daemon, not systemd private /tmp. Writable installers are isolated from frozen inputs.

Per-build build.json records source SHA, contract, assets, effective generated assets and image IDs. Batch manifests retain source/image provenance. Build logs stream to Pipeline. Passing build does not prove runtime readiness or browser behavior.

## Operations and rollback

Pre-cutover backup: /var/backups/pr-e2e/20260910T095802Z, including config/app, DB dump, archives and SHA256SUMS. Earlier backup: /var/backups/pr-e2e/20260910T080502Z.

Inspect: systemctl status pr-ci@worker pr-ci@editor pr-ci@publisher pr-e2e-docker pr-pipeline-control

Role template: /etc/systemd/system/pr-ci@.service. Submission permits loopback and 124.70.231.102/32 and requires login. HTTP credentials and requests are cleartext: restricted-network demonstration only.

Rollback: stop CI roles, preserve evidence and resolve leases, then restore WSL consumer. Never run both consumers. Do not overwrite a running DB or delete isolated Docker data automatically.

Remaining acceptance: actual baseline and joint-candidate E01/E02/E03, Daemon-offline recovery, final version/evidence checks. Verify reboot enablement and retained-environment resource admission at final handover.

## Real browser diagnostics and blockers

Private evidence roots are under /var/lib/pr-e2e/state/diagnostics/. They are diagnostic runs, not passing PR acceptance, and have not yet been published as dashboard runs.

- 20260910-115505-bccd9b: original E01 failed because Mattermost omitted the Idempotency-Key header required by AgentLink.
- 20260910-121954-66190a: E01 passed using local-only adapter commit e4eded6ed5010b18bb81dae9be4ec85ad43387ed, based on c6b4425abfb2b28e015f8fb08988c8bb84664419. Image local/pr-e2e-mattermost:e4eded6ed501, ID sha256:6640366530bab658ffe2f98b6cf182e3ca10d8d7efce83d2fa45e7c8932e52fa. No branch was pushed or merged.
- 20260910-122103-30d904 and 20260910-123625-b056cc: E02 failed because deep registration marked OpenCode credentials unavailable; Schedule skipped the offline bot.
- The dedicated daemon now has native OpenCode auth storage using the same real ModelArts credential and an auth-list preflight. No synthetic readiness response or provider-key alias was used.
- 20260910-124400-ca0505: OpenCode deep registration reported provider_ready=true; Schedule then failed Job submission with agent_cli_input is required. The selected Schedule #155 targets the older fix/im-compact-idle-prompt branch. Newer Multica requires a contract not supplied by this old baseline. Do not bypass this failure or label it a model failure.
- CellMem returned HTTP 500 for memory operations and Schedule used its existing Redis fallback. This is an additional unresolved environment/service issue, not verified long-term memory coverage.
- Governance #105 was subsequently closed without merge. The next formal batch needs freshly resolved open PRs and matching integration inputs.
- E03 and the full joint candidate have not passed.

At the last network probe, public /api/health returned HTTP 200 but SSH from Windows and WSL failed during connection/key exchange. Direct egress remained 124.70.231.102. No security-group or host SSH settings were changed.

Local follow-up code adds a fail-closed deep-registration readiness gate and private auth rotation tests. Ten focused Python unit tests passed; unit fixtures are not real E2E evidence. This final readiness-gate revision still needs synchronization to CI after SSH recovers.
