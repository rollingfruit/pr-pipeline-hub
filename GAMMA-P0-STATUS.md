# dev-gamma P0 implementation checkpoint

Date: 2026-09-12. P0 queue/Worker/Robot CI cutover is deployed. The user reduced
the first stability experiment to 10 rounds. Running is not acceptance passed.

## Live cutover and first 10 rounds

- Backup: `/var/backups/pr-gamma-p0/20260912-120845`, including PostgreSQL dump,
  Robot CI SQLite backups, configuration and previous application files.
- Control, unique Worker, Robot CI main and preview are active. Both known
  dev-gamma post-build/deploy-only entries now use the same PostgreSQL queue.
  Preview-only repository test features were preserved.
- The privileged helper is installed with isolated Python startup. Imported
  application modules and their parent directories are root-owned, not mode 777.
- Worker descendants were verified in the 2 CPU / 10GiB cgroup. The 12GiB
  free-memory gate initially blocked execution; unused platform-owned CI Compose
  containers were stopped without deleting images/volumes or lowering the gate.
- Diagnostic `gamma-dba52f388ff5c3bb796b414a`, child
  `gamma-check-20260912-121147-c0d9ee`: E01-E06 (7 assertions) passed, but cleanup
  failed. The failed diagnostic remains failed and is excluded from formal rounds.
- Root cause: `connect-daemon` uses the historical `hw` Workspace, whereas the
  WeLink deletion contract checks `MULTICA_WORKSPACE_ID`. Their mismatch produced
  native HTTP 409, mapped by AgentLink to 503. Under the quarantined queue lock,
  the operator aligned that dev-gamma configuration with a UID/resourceVersion
  guarded patch. The previous Deployment was saved privately. No business image
  or assertion was modified. All 7 bot bindings and the test account were then
  cleaned through supported APIs; the daemon stopped and its runtime was verified
  offline. Recovery is recorded separately and does not turn the attempt green.
- The Workspace is shared by the test team. Per-round accounts, bots, daemon,
  fixture directories and evidence are isolated; do not claim per-round Workspaces.
- Formal experiment: `gamma-e7b4f5b48f05b7a03897ed1a`, target 10 rounds, each
  E01-E06, no test retries. Repeated submission returned the same record.
  URL: http://119.8.233.58/pipeline/runs/gamma-e7b4f5b48f05b7a03897ed1a
- Rounds 1-6 passed. Round 7 (`gamma-check-20260912-133717-f7529f`) was interrupted
  after the established nested SSH transport became inactive. E01-E04 passed;
  E05/E06 and business cleanup could no longer reach the forwarded application.
  The original experiment remains unsuccessful at 6/7 first-pass rounds and was
  not resumed or rewritten.
- Evidence-gated recovery used a fresh SSH connection. It removed four bot
  bindings, deactivated the test account, stopped the daemon, verified its runtime
  offline, verified the archive, and released quarantine with zero active residuals.
- Future tasks now check both SSH transports before opening each forwarded channel,
  serialize reconnects and retry channel creation once. A forced-disconnect test
  returned HTTP 200 before and after reconnect. Post-change diagnostic
  `gamma-ccbe57c1f7ca7f524f072483` passed E01-E06 (7 assertions), archive and full
  cleanup on the first attempt with zero active residuals.
- Four separate continuation tasks filled target slots 7-10 after hardening. All
  passed E01-E06 on the first attempt, verified their archives and finished with
  zero active residuals. The ten successful target slots required eleven actual
  attempts because the original round 7 remains failed. See
  `GAMMA-P0-STABILITY-20260912.md` for the immutable attempt-level accounting.
- At 2026-09-12 12:48 CST, the first formal round passed all 7 assertions across
  E01-E06, archived successfully with verified hashes, removed 7 bot bindings,
  deactivated its ordinary account, stopped its daemon and verified the server
  runtime offline. Active residuals: zero. The same persistent parent automatically
  started round 2, child `gamma-check-20260912-124753-40c7d1`, without operator
  intervention inside the experiment. Remaining rounds continue on CI.
- Latest checks: 37 Gamma unit tests passed; four PostgreSQL schema-isolated
  queue/fencing/recovery tests passed separately. UI build passed. Chromium
  rendering at 1440/1920/390 had no page errors or document overflow; authenticated
  internal rendering was tested, not a new end-user login. Anonymous same-site
  dashboard requests still redirect to Robot CI login.

## Operation and remaining limits

Submit through the existing internal queue, never invoke a second direct runner:
`python3 /opt/gamma-p0-validation/gamma-p0-task.py stability <unique-submission-id>`.
This operator entry currently requests exactly 10 rounds; the API supports 10 or 30.
For status, use the same script with `status <run-id>`.

Recovery tooling is root-only, checks the current quarantined owner, holds the
existing queue advisory lock, checks old processes, records evidence and uses
the existing recovery operation. Configuration alignment requires explicit
`--align-workspace`; do not repeat it during a frozen experiment.

Full partial-bootstrap cleanup and interruption checkpoint replay are not yet
exhaustively implemented/tested. Unknown inventory still quarantines the environment
and requires operator recovery. Real process-kill/SSH-loss fault injection and
seven-day retention acceptance remain gaps, not verified guarantees. This is not
a hostile-code isolation platform or a forced merge gate.

The sections below retain the earlier pre-cutover checkpoint for history.

## Earlier Implementation Checkpoint

- Gamma submissions share the existing PostgreSQL queue and Worker. A parent
  stability job selects E01-E06 for 30 rounds; there is no second scheduler.
- Environment ownership uses a generation and 180-second lease. Progress renews
  it every 30 seconds. Expiry, missing cleanup evidence or active residuals prevent
  the next task from claiming the environment.
- Recovery requires process, remote-operation, archive and cleanup evidence;
  recovered attempts remain unsuccessful and do not emit PR deliveries.
- Candidate deployment uses the existing rollout CAS checks plus lease checks.
- Frozen harness, dependency, interpreter, model configuration, credential
  fingerprint, deployment configuration and Daemon digests are verified.
- Round records retain first-attempt outcomes and separate archive/cleanup state.
  Infrastructure failures remain in the started-round denominator.
- The detail UI has campaign progress, round links and first-pass statistics.
- Robot CI branch `codex/gamma-p0-stability` is based on main after merged PR12.
  Draft PR: https://github.com/censong574-spec/robot-ci/pull/13 (commit `3d04e14`).

## Verification completed

- Robot CI: 196 tests passed using native Python 3.11 on CI, in an isolated copy.
- PostgreSQL: four disposable-schema tests passed: FIFO/concurrent claim and
  idempotency, expired lease rejection, cleanup quarantine, evidence-gated recovery.
- Gamma unit tests: 24 non-database tests passed; four DB cases separately ran.
- Frozen settings test passed: reconnection cannot rewrite model or Daemon identity.
- React TypeScript compilation and Vite production build passed.
- Read-only dev-gamma readiness: all 16 Deployments ready.

Validation copies are under `/opt/gamma-p0-validation`. They are not live services.

## Administrative cleanup update

The user authorized system-administrator cleanup. The deployed Mattermost already
enables its supported local management socket. `gamma_admin.py` now uses
`mmctl --local` via the existing Gamma SSH access, without distributing administrator
passwords, changing the self-deactivation setting, or elevating browser test users.

Two real administrative diagnostics passed (not E01-E06 rounds):
`admin-check-20260912-114239-088197` and `admin-check-20260912-114559-60e827`.
Both confirmed ordinary-user roles, administrative deactivation, invalidated
sessions, rejected subsequent login, safe repeated cleanup and zero active account
residue. The latter also verified the canonical dev-gamma connection guard.
Eight administrator guard tests and three process-cleanup failure tests passed.
The permission blocker is resolved; production P0 cutover and 30 rounds are still
pending. No test assertions were weakened.

## Earlier Rollout Checklist (Historical)

- Complete and test the cleanup authorization path, idempotent cleanup retry,
  partial-bootstrap cleanup, and every owned resource inventory.
- Preserve preview Robot CI's extra Gamma features while queueing all dev-gamma
  deployment entries; never overwrite preview server.py wholesale.
- Install the narrow root helper only after sealing imported code: some current
  CI Python files are mode 777. The new helper has NOT been installed.
- Validate root-owned execution directories and protected settings with a real E05
  recovery; only mutable runtime binding files may change.
- Finish deployment/retention/restart reconciliation and test lease loss during
  real remote operations. Current unit tests do not prove remote process fencing.
- Back up configuration and databases; switch compatible control, unique Worker
  and Robot CI integrations only while quiescent.
- Test the UI at 1440/1920/390 and one real diagnostic cleanup cycle.
- Only then freeze and submit the persistent formal 30-round experiment.

## Earlier Formal Statistics (Before Cutover)

Planned: 30. Started: 0. Completed: 0. No first-pass rate is available.
The previously successful single E01-E06 run is historical evidence and is not
counted as a round of this experiment. No production cutover has occurred here.
