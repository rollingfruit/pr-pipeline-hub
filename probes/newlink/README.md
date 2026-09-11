# NewLink mention probe

This folder contains read-only inspection and correlation tools. It does not patch the installed app, read login databases, replay expired credentials, or synthesize a user message.

## Confirmed client behavior

- Installed application: `D:/IM/newLink/NewLink/NewLink.exe`.
- `plugin/im/dist/static/js/6743.js`: mention picker renders `atListWrap` from member accounts.
- `common.js`: `replaceAtWord` and `insertAt` route through the editor's `at` implementation; selection uses the member's account, not just its display name.
- The editor produces an anchor with `role="@"`; a literal text string does not establish that structure.
- The standalone `sendTextMessage` convenience interface lacks a structured mention parameter. It cannot be assumed to trigger an Agent.

## Native UI probe

Target: group `蓝区编码演示`, real mention picker item `xiao-commitor`.
Marker: `NL-20260909-01`.
Draft: `链路探针 NL-20260909-01：请只回复“NL-20260909-01 已收到”，不要修改代码、创建流水线或回写 GitHub。`

Sent once through the actual native UI after user confirmation, at 2026-09-09 16:50 +08:00. The source message and xiao-commitor opening Ack were observed in the approved group. The expected final marker reply was not observed.

Daemon evidence identifies task `cc38f47f-7d11-4ee9-aecf-03d5ff6c6673`, chat session `8ac006a7-f932-44be-9ff2-57f41c8ea3e4`. At 16:50:34.348 it was received and picked for provider `codex`; at 16:50:34.350 it failed with `im_task_prompt is empty`. Agent, workspace, group and runtime IDs all match the approved target. Codex was not spawned. An Ack is not successful execution.

The local collaboration task list did not contain the marker because this failure occurred before process startup. This is why both task-list and daemon-log evidence are needed. No extra probe was sent, no PR was created, and this probe did not run E2E or post to GitHub.

After confirmation, send through the normal client, observe the source message and bot response, then run `task-receipts.ps1`. Correlate the marker with a real daemon task. Absence of a task is not by itself failure: the platform may directly answer without starting the executor.

## Tools

- `inspect-asar.cjs <app.asar> <search terms...>`: bounded source excerpts from the installed IM JavaScript bundle. Read-only.
- `task-receipts.ps1 -Marker NL-20260909-01`: authenticated local collaboration API; outputs only matching bot/workspace task IDs, status and timestamps. Does not print its viewing token or unrelated task content.
- `task-receipts.ps1 -TaskId <real-task-id>`: direct correlation when task events omit the prompt marker.
- `python daemon-receipts.py --task-id <real-task-id>`: read-only scoped lifecycle events, including pre-spawn failures. Emits an allowlist of fields, never raw prompts, credentials or arbitrary error contents. With WSL pass `--log /mnt/c/Users/XIAO/.multica/daemon.log`.

## Remaining contract blocker

Local Multica source maps `IMAgentTaskContext.Prompt` to the daemon's `im_task_prompt`. The live cloud task supplied an empty value while including 16790 bytes of execution context. This establishes the missing wire field, but does not establish which deployed upstream version lost it. Obtain the task context and deployed version from the cloud operator before changing serialization or reconstructing instructions.

A local service guard now rejects blank prompts before database access in `EnqueueIMAgentTask`, with a regression test. It has not been deployed to the cloud API serving the desktop. The daemon's strict validation is deliberately preserved. This guard detects the problem earlier; it does not repair the missing cloud instruction.

For final acceptance require all three: real source mention, correlated successful executor task, final reply in the same group. Unattended GitHub-triggered dispatch and AgentServer result delivery require their own authenticated receipts and remain separate from this native UI probe.

Native interaction uses the available `@oai/sky` Computer Use skill. Window and element identifiers must be freshly observed; do not replay fixed coordinates in an unattended worker. This probe validates the existing user workflow, not a production unattended message bridge.
