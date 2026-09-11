# Robot CI Gamma integration

## Entry and scope

- Build: http://119.8.233.58/#/build/agent-governance-gw
- Select a branch, `CI isolated E2E`, Gamma test, E01/E02/E03 and baseline comparison, then confirm.
- This target never invokes CCE rollout. Existing CCE deployment remains a separate target.
- The exact archived build image is tested, not a reconstructed PR candidate. No merge approval, GitHub writeback or Codex code review is performed.

## Handoff

Robot CI captures the image ID before its existing image cleanup. The bridge copies the build TAR into its own inbox, verifies the image configuration digest, hashes the TAR and submits an immutable manifest through the authenticated loopback control API. The build ID is the idempotency key. Changed inputs under the same build ID are rejected.

The existing PostgreSQL queue and single Worker execute baseline and candidate in the dedicated Docker daemon. Baseline failure stops candidate execution. A failed assertion, unavailable environment or missing evidence cannot produce success. The original build slot is released before waiting for E2E.

The build page retains a Gamma result and clickable Hub link, including after server restart. Stopping the build waiting loop does not cancel an already queued Hub task. A control outage or process restart is not automatically reported as success; the retained Hub record remains the source of test evidence.

## Server configuration

- `/etc/pr-e2e/artifact-baseline.json`: explicit, full integration baseline; service/repository/source SHA/image ID, including known limitations. Review and replace deliberately when upgrading compatible service versions. Not automatically advanced to moving `main`.
- `/etc/pr-e2e/secrets/worker-token`: server-only credential, existing control Worker secret.
- `/etc/pr-e2e/config.toml`: existing Worker, model, resource, storage and optional-function settings.
- `/var/lib/pr-e2e/artifact-inbox/<build-id>`: owned immutable input archives and manifest; not served publicly.
- `/var/lib/pr-e2e/data/runs/gamma-<build-id>`: execution logs and evidence.
- Independent Docker: `unix:///run/pr-e2e/docker.sock`.

Bridge path overrides: `GAMMA_E2E_BASELINE_FILE`, `GAMMA_E2E_TOKEN_FILE`, `GAMMA_E2E_ARCHIVE_ROOT`. Worker inbox override: `PIPELINE_ARTIFACT_INBOX`. Control remains loopback port 8792; public reporting remains port 8080. No anonymous internal submission endpoint is exposed.

Inbox TAR retention is currently manual. Delete only completed, archived batch directories after checking no live lease uses them. Do not run global Docker/image/volume cleanup on the isolated daemon. Public report retention continues to use the existing publisher policy.

## Verified run, 2026-09-11

- Browser-triggered build `3fe4149627dc`, branch `main`, source `d198100fb0156cc1d55012509097422028af118e`.
- Hub: http://119.8.233.58:8080/batches/gamma-3fe4149627dc
- Exact candidate image: `sha256:eec1606a2dcf2d7ed011cb1875506b1a3873b1d0b610361fe4b817312b8687bd`.
- Build, push, immutable archive import, queue, baseline environment, report publication and failure callback completed.
- Baseline E01 passed. E02 failed; E03 and candidate tests were not executed. This is NOT a passing E2E acceptance.
- Real task `21abf71f-3fd3-4f07-966c-a21c6484210f` was accepted by Schedule, then failed in the Daemon with `refusing to spawn IM agent task: im_task_prompt is empty`. The current Multica Server/Daemon input contract must be aligned before a passing E02/E03 run is possible.
- Baseline Schedule was built from `30fa36d7f45c3920ac4fb8a8d15bd2e5db748fe6`. Mattermost uses the explicitly recorded unmerged CI adapter fix `e4eded6ed5010b18bb81dae9be4ec85ad43387ed`, not upstream main.
- Earlier build `951a26db6f28` failed before queue handoff because the original build removed its local image. The archived-image handoff fixes this; the failed record remains intact.

## Checks and rollback

### Multica alignment, 2026-09-11

Remote main was frozen at `e851104800b7620830153489bf0f045c958c0c5f`.
Server image: `sha256:51dfc17cf610915cc8a9baab2fe822ff0b038c319b71022b261850b4466fb016`.
The Daemon was extracted from that exact CCE image; SHA256:
`7bc95ea5ff45ef3f1e88576fbde28f2cc381bb467fde52ad3fc536e7589ecab9`.
Use `deploy/cloud/align-multica-runtime.py <full-sha>` only after the corresponding
`check-ci-build.py` build succeeds. It takes the environment lock, checks the image
revision, backs up the old binary/baseline and promotes both together.
The record is `/var/lib/pr-e2e/state/multica-runtime-alignment.json`.
It changes only the CI test runtime, not CCE.

Run `gamma-4c06873e43a7` no longer failed with `im_task_prompt` missing: E01 passed
and E02 reached real tool execution and final delivery. E02 failed because the
OpenCode external-directory policy denied the dedicated fixture path.
`allow-e2e-fixture-directory.py` grants only the fixture directory while retaining
the catch-all external-directory denial. Config changes invalidate the previous
tool smoke; run `stack/smoke_opencode.py` again before submitting a new build.
Run `gamma-e85d8f64d513` preserves this stale-smoke preflight failure.

After a successful real tool smoke with the updated config, browser-submitted
build `5262d20a0486` reached baseline E01 (passed). E02 failed at the assertion
that task events contain a `command` or `tool` kind. Candidate and E03 were
not executed. The complete E2E acceptance remains failed; assertions were not
weakened. Trace, video and screenshots are retained at
http://119.8.233.58:8080/batches/gamma-5262d20a0486 .

The deployed step logs were tested in Chrome at 1440, 1920 and 390 widths;
clicking the Pipeline URL opened the actual report in a new tab. Robot CI's
14 CCE tests and 107 job tests subsequently passed in an isolated temporary
directory on CI with its SDK dependencies, never against production data.
Robot CI PR: https://github.com/censong574-spec/robot-ci/pull/11 (not merged).

Seven targeted bridge/manifest/PostgreSQL tests passed, plus three existing control Worker tests. PostgreSQL tests use an isolated temporary schema. The broader Robot CI CCE unit suite could not run locally because its Huawei SDK dependencies were unavailable; no production test suite was run against live Robot CI state.

Browser artifacts are under `.runtime/robot-gamma`; verification covers build result and report links at 1440/1920/390 widths. The verification script requires explicit environment credentials and only submits when `ROBOT_GAMMA_SUBMIT=1`.

Robot CI backup: `/var/backups/pr-e2e/robot-ci-before-gamma-20260910.tgz` (restricted permissions). Existing control configuration and database backups are under `/var/backups/pr-e2e/20260910T155323Z`. The archive tar step reported concurrent file changes, so it is not a consistent full archive snapshot. Existing published reports were retained in place.

For rollback, first wait for active Robot CI builds and Hub leases to finish, stop new submissions, restore only the changed Robot CI files and previous control/frontend files, then restart the affected services. Preserve database records, manifests and reports. Do not run WSL and CI Workers together.
