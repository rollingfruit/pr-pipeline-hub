# dev-gamma build validation and environment diagnostics

## Scope

The same real browser driver supports existing-environment diagnostics and a
verified Robot CI build rollout. Neither mode is a PR verdict or a baseline
comparison. The build bridge resolves each module's existing Robot CI environment
and deployment/container mapping. Environment a5932430eb2f anchors the trusted
dev-gamma cluster connection, not the only allowed module ID. Six selectable
suites are passed unchanged; the default remains E01/E02/E03.
Robot CI remains the source of environment credentials and website sessions.
Its SWR login is registry authentication, not the identity used by a bot.

The CI host runs the browser and a dedicated OpenCode daemon. Diagnostic mode
does not change images; build mode patches only the selected container image.
Neither mode resets databases or reuses developer daemons or user accounts.
Each invocation provisions its own ordinary test account, bots, channels and
filesystem fixtures. Business records remain available for inspection. Automatic
fixture retention/cleanup is not implemented; do not run an unattended schedule.

## Installed entry point

On `ecs-liusong-ci`, from an authorized operator shell:

```sh
systemd-run --unit="gamma-check-$(date +%Y%m%d-%H%M%S)" \
  --slice=pr-e2e.slice \
  /usr/local/bin/python3.11 /opt/pr-pipeline-ci/gamma_acceptance.py \
  --environment-id a5932430eb2f --suites E01 E02 E03
```

The journal immediately prints `PIPELINE_URL`. Reports require the existing
Robot CI login. Do not expose the internal control API or add a public command
execution endpoint. Robot CI's gamma_real.py invokes this driver after checking
the Docker archive config hash against the immutable SWR manifest. Select both
gamma deployment and gamma testing in the existing build pipeline. Test-only
mode requires the exact image digest to be already deployed.

Configuration sources:

- Robot CI environment database/config: jump host, nodes, namespace, credentials.
- `/var/lib/pr-e2e/state/settings.json`: OpenCode model and config-file reference.
- OpenCode credential file referenced by the existing configuration, read only.
- Per-run `/var/lib/pr-e2e/gamma-diagnostics/<id>/private`: generated test identity,
  exact deployed Daemon binary hash, browser identity mapping and private traces.
- `/var/lib/pr-e2e-share/runs/<id>`: redacted logs, screenshots, videos and manifest.

Only the per-run fixture directory is added to the isolated OpenCode external
directory allowlist; other external paths remain denied. GitHub credentials,
Robot CI passwords and Multica service credentials are not Agent task inputs.
The Daemon binary is downloaded from deployed Multica and its SHA256 is verified
against that deployment's bundled binary.

The diagnostic now explicitly disables Codex discovery in its private Daemon
profile. It does not uninstall or change the CI host's Codex. This is a scoped
single-provider fixture, not a fix for the observed multi-provider UI selection
reset. Historical failed runs remain available as evidence of that issue.

## Isolation and limitations

Diagnostics use a cluster-wide nonblocking lock across module IDs, one browser worker and the
existing `pr-e2e.slice` budget. This lock is NOT the PostgreSQL batch lease or the
original CCE deployment lock. Other users can still update dev-gamma; the driver
compares deployment templates at the end and marks changes stale. It never rolls
back other users' changes. Do not advertise concurrent shared-environment rollout
safety until the original rollout path and batch scheduler share a single lease.

The selected image is rolled out before extracting the matching Multica Daemon.
E05 enables fault control for this invocation's dedicated profile only. E04/E06
use the dynamically forwarded Multica endpoint. Existing modules without an
environment/workload mapping require configuration rather than guessed targets.

Diagnostic records describe existing images. Build records additionally include
the actual build SHA, immutable SWR reference and image config digest. Rollout
uses UID/resourceVersion compare-and-swap; failures restore only our unchanged
template, and external updates prohibit automatic rollback. Database migrations
are outside image rollback guarantees. The test Daemon is stopped at completion;
the existing cluster services remain running. No successful case replaces a
failed case in an older run. All assertions and evidence remain associated with
their actual invocation.

## Verified build acceptance (2026-09-11)

The root operator invoked the deployed Robot CI post-build entry point with the
existing artifact from build 82cf0e6101c8, creating separate history 4b93efe1cfa7.
This was not a fresh browser build submission. The selected SHA was
717528cb9cd69a1100e6798cccf0b140735093cd; SWR digest was
sha256:c4761bc2c6a5bddd0c360817a25e008c3a594624bed23a1868482a054968cff5.

- gamma-check-20260911-163733-5093c8: E02 failed, E01/E03 passed; actual image
  rollback succeeded. An OpenCode progress prefix was rejected by Multica's
  final-delivery validator even though a tool had read the file.
- gamma-check-20260911-164807-d0820a: rollout and E01/E02/E03 passed, including
  follow-up. The test request now explicitly asks for only final file contents;
  no completion, tool-use or correlation assertions were relaxed. This does
  not fix the broader progress-prefix compatibility issue in Multica.
- Both archives have 35 verified artifacts. Final deployments were ready 1/1;
  governance retained the verified image, Mattermost/Multica were unchanged.
- Report evidence/log UI checked at 1440, 1920 and 390 pixels with actual data.
  That UI check does not substitute for a new Robot CI login acceptance.

The UI browser check `tests/gamma_report_browser.cjs <run-id>` reads real archived
data through the internal authenticated API at 1440/1920/390 widths. It verifies
UI interactions, not the external Robot CI login flow or business E2E assertions.

## Acceptance on 2026-09-11

`gamma-check-20260911-153644-f152d1` completed E01, E02 and E03 successfully in
one invocation, with no browser test retries. E02 verified the unpredictable
fixture contents, a real completed file-tool event, the correlated final post
and a follow-up in the same conversation. E03 selected a visible mention before
sending and verified the same execution/delivery chain in its own group.

Report: `http://119.8.233.58/pipeline/runs/gamma-check-20260911-153644-f152d1`.
This success applies only to the captured current environment and the dedicated
OpenCode-only fixture. It does not certify the unresolved multi-provider
selection reset, image rollout/rollback, or automatic build-to-test integration.
