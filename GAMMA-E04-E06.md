# Gamma E04-E06 repair

## Normal test paths

- E04: browser-created bot, browser-submitted project check, real script-start evidence,
  the current Run Card's Stop Answer button, cancelled run, idempotent cancellation.
- E05/tool-failure: a private project check exits 37 and emits its diagnostic. Require
  a correlated failed command event, a completed explanation, the diagnostic marker,
  and exit code 37 in the final user-visible reply.
- E05/terminal-failure: first confirm actual script execution, then crash only this
  run's dedicated daemon. Check process UID, HOME, daemon ID and executable before
  signalling through a pidfd. Wait for server-side failure delivery, then restore
  the same control-plane owner and verify publishable runtime readiness.
- E06: browser file-read task, two concurrent native Job requests using Schedule's
  source-event idempotency key, the same original Job ID, successful original task,
  and exactly one final reply containing the file's unpredictable content. This is
  a hybrid browser/API-boundary test, not a full gateway-envelope replay.

Fixtures do not change gateway safety policy, borrow another user's application identity, or replace
browser actions with API fallback. E05 process crash does not certify graceful daemon
shutdown semantics. An earlier graceful-stop diagnostic remained running until
daemon recovery; that failure record is preserved.

## Fixes

- Artificial `sleep` / random-answer chat commands were rejected by the LLM content
  safety filter. Normal project-file tasks replace those prompts; safety remains on.
- E04 used the retired Stop Agent selector and endpoint. It now uses the current
  Chinese Run Card control and `/agent-runs/{id}/cancel`.
- E05 incorrectly required a successful command event for an intentionally failed
  command. Only E05 expects `failed`; E02/E03 still require `completed` tool events.
- Recovery now reuses the verified `CONTROL_USER_ID`, including the local identity
  suffix. Recovery errors no longer overwrite the original assertion failure.
- Gamma provides the host Python 3.11 to fault control because the bundled Python
  3.12 lacks pidfd bindings. Other execution remains on the existing runtime.
- OpenCode IM execution now honors the existing `FinalOutputOnly` contract. Tool
  and progress events remain in the event stream; pre-tool prose no longer pollutes
  the final delivery. Native default output behavior remains unchanged.
- File-read fixtures contain a Chinese project record with an unpredictable nonce.
  This keeps verbatim file output consistent with the requested reply locale; it
  does not disable locale validation or place the answer in the user prompt.
- E02 updates that record before the same-conversation follow-up, requesting a
  fresh tool read without repeating the path or disclosing the new value. A cached
  answer cannot satisfy the tool-event and updated-content assertions.
- Readiness verifies Deployment generation, updated/ready replica counts, Pod image
  references and actual image IDs. An available old replica is not sufficient.

## Reproducible deployment

The tested baseline source is `4e3e8c5f74f6cdb92f7220685cb8fea9a7cd553a`.
The backported fix is `b8b3ac427a849b6e0dcfc064413a60ca78268f3e`, on local branch
`fix/opencode-gamma-final-output`. The main-compatible patch is
`60bbe1fbc572d3928977601f66127af2b565ff8d`, on `fix/opencode-im-final-output`.
Neither branch is automatically merged.

CCE build: `build/package/build.sh pack`, actual Go builder version 1.26.5.
No database migration differences exist between the deployed baseline and backport.
CI inputs/output: `/var/lib/pr-e2e/opencode-final-b8b3ac4/`.
Published image: `swr.cn-southwest-2.myhuaweicloud.com/public_ai/multica-server@sha256:2b96b912738b2028a0f6ae4c4f8164f50b9b62a4b00242897fce344a95561d2e`.

The former desired image tag was unavailable in SWR; an older ReplicaSet was still
serving. The environment was reconciled to its verified serving digest before the
candidate deployment. Private backup: `/var/lib/pr-e2e/gamma-maintenance/20260911-opencode/`.
Rollback is conditional on an unchanged Deployment template, never an unconditional
overwrite of another operator's update.

Final full-suite acceptance: `/pipeline/runs/gamma-check-20260911-205917-64cccb`.
E01-E06, including both E05 cases, passed in the same execution. All 75
archived artifact hashes match; the frozen environment was not stale. Real report rendering, evidence and logs were
checked at widths 1440, 1920 and 390 through the authenticated internal viewer.
This UI check does not certify the separate Robot CI login flow. Earlier failed
records, including the locale mismatch in `gamma-check-20260911-202950-7e95e1`
and E02 cached follow-up in `gamma-check-20260911-205325-b953a7`,
remain unchanged.

Earlier independent E04-E06 acceptance also passed:
`/pipeline/runs/gamma-check-20260911-204516-665cfa` (42 verified artifacts).
The dedicated runtime is stopped after each run; the successfully verified
Multica candidate remains deployed. Test conversations and archived evidence remain.

Repeat this exact CCE artifact acceptance on CI (serialized by the existing Gamma
environment lock):

```bash
systemd-run --wait --pipe --collect --property=Slice=pr-e2e.slice \
  /usr/local/bin/python3.11 /opt/pr-pipeline-ci/accept-opencode-build.py \
  --suites E01 E02 E03 E04 E05 E06
```

The helper validates the immutable image/source identity and freezes the selected
suites before invoking the normal Gamma driver. It is a pinned repair-verification
entry, not a replacement for Robot CI's ordinary build handoff. No PR approval,
GitHub delivery, or NewLink notification is implied by these environment results.
Future Multica builds must include the OpenCode fix; the image hotfix does not merge
source changes into any business branch.
