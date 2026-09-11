# E02/E03: deployment alignment before business-code changes

## Scope and observed evidence

This investigation does not modify source under mattermost-microservice. Earlier adapter and harness edits remain untouched. No new batch was submitted, no PR was merged, and no passing E02/E03 result is claimed.

The cloud editor is http://119.8.233.58:8080/submit/. The dashboard now provides a persistent entry. Local 127.0.0.1:8793 is the stopped pre-migration editor, not the daily execution endpoint.

## E02

The real failed run 20260910-124400-ca0505 reached Schedule and attempted a Multica Job. The server rejected it with `agent_cli_input is required`. This occurred before model execution.

The selected Schedule #155 targets `fix/im-compact-idle-prompt`, whose frozen base was c5217ba326cf239c7a4e967e0fe9fa39706d6254. It must not be silently replaced with main and reported as the original PR baseline.

Local Schedule HEAD is e082246c9a0bc3f1245424a1a9bd00a04190a7b8. Its src/sementic/direct_job.py validates im_execution_context, renders agent_cli_input and sends both the original prompt and canonical execution input. src/sementic/multica_job_client.py rejects missing canonical input before dispatch. Existing tests/test_direct_chat.py covers these fields and forbids degrading an IM task to a native job. Rebuilding a matching current integration baseline is the first corrective action, not adding another compatibility shim.

Before another browser task, verify the dedicated OpenCode runtime has completed deep registration and reports provider_ready=true. Initial online registration is optimistic and is not sufficient. The previously deployed native ModelArts auth and preflight did produce provider_ready=true on CI.

## E03

Group explicit mentions share DirectJobRouter's canonical submission contract with private chat. Correcting the deployment mismatch is necessary for both suites, but an E02 pass cannot certify E03.

Preserve browser creation and actual mention selection. Independently check the selected bot identity, original source message, group channel, thread root, actual tool execution and exactly one final delivery. Do not replace the tested send action with a direct API task or plain @ text.

Current Governance internal/agentreply/client.go uses agent_run_id as a backwards-compatible root-run locator and emits agent_execution_run_id for the actual execution. The existing harness only queries agent_run_id. Inspect real runtime payloads before updating assertions to distinguish root and execution IDs; retain strict task/source/channel/final-post correlation. This is a potential harness mismatch, not yet an observed E03 failure.

## Optional memory dependency

CI CellMem logs identify the HTTP 500 cause as `AGENTARTS_MEMORY_SPACE_ID is required`. The health endpoint alone did not detect missing business configuration. Schedule used its existing Redis fallback. Do not invent a memory space ID or label remote memory verified.

Choose explicitly between provisioning real AgentArts space/authentication and a documented no-cloud-memory execution profile using service-supported configuration. Validate same-session follow-up through real Agent session/tool execution either way; cross-channel and long-term memory remain outside E01/E02/E03 acceptance until separately tested.

## Next controlled run

1. Freeze a current, mutually compatible integration baseline and build its existing CCE contracts. Record full SHAs, dirty-source status, image IDs and test/config fingerprints.
2. Keep any unmerged Mattermost creation-header adapter patch explicitly labelled; it is not stock main. Do not silently apply further business changes.
3. Diagnose the current baseline E02, then E03, retaining failed browser evidence and service correlation.
4. Select fresh open PRs targeting the validated integration baseline. Governance #105 is closed and must not be reused. If an older target branch is intentionally tested, preserve its genuine baseline failure.
5. Run identical baseline/candidate suites and recheck head/target versions before publishing a result. Optional code review and writeback remain disabled unless explicitly enabled.

Deployment of the editor is complete; real joint E2E acceptance remains incomplete.
