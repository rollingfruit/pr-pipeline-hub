# Team access and NewLink delivery checkpoint

## Team access

- External HTTP 8080 now responds from this machine. Existing view-token URL follows HTTP 303 to an authenticated page with HTTP 200.
- View token remains the existing server-configured token; no rotation performed. It has no time-based expiration in the server. The HttpOnly browser cookie lasts seven days; reopening the original token URL signs in again.
- This is shared read access, not an administrative/worker credential. Anyone holding it can view private pipeline reports. HTTP transport is an explicit demo limitation. Keep the URL inside the trusted team.
- Reports remain subject to the seven-day artifact retention policy, independently of token validity.

## Actual desktop mechanism inspected

App: `D:/IM/newLink/NewLink/NewLink.exe`, archive `resources/app.asar`.

Read-only inspection of `plugin/im/dist/static/js/im.js` found exported `sendTextMessage({target,chatType,entry,text})`. It validates types, rate limit, content length, sensitive-content rules, group membership and mute state, then invokes `sendTextMessageToSingle`. It runs in the authenticated desktop user context; this API has no structured mention argument and returns `{result,errorMsg}`, not an Agent task receipt.

`common.js` contains the managed Multica executable selection and IM/native module calls. The main process is loaded through `main.jsc`. No application files were patched, no debug listener was enabled, and no login database/process-memory extraction was used.

Therefore this desktop text interface is not equivalent to an authenticated bot sender or an execution request. A literal `@xiao-commitor` string cannot prove bot invocation.

## Implemented outbound adapter

`newlink_delivery.py` is wired into the existing durable outbox. It follows the repository's `internal/agentreply/client.go` protocol:

- POST `{base_url}/v1/agent/messages/reply`, `X-Auth-Token` from an external service-token file.
- Fixed approved group, Agent, workspace and bot account. Tenant/corp must be configured explicitly.
- Stable request ID per pipeline run and delivery phase. Require response code 0/2602 **and** a real `imMsgId`.
- Never fabricate a source chat message for a GitHub-origin event. Whether AgentServer accepts unsolicited notifications with an empty source must be verified with its operator.
- Reject redirects with the service credential, localhost share links, and messages over 500 characters.
- Activation timestamp prevents unintentionally replaying historical outbox messages when credentials become available.
- A successful outbound receipt reports `agent_execution=not_requested`; task dispatch still requires the real AgentServer/Multica ingress contract and authenticated receipt.

Template: `newlink-delivery.example.json`. Active configuration is `.runtime/newlink-delivery.json`, or the file specified by `PIPELINE_NEWLINK_CONFIG`. It remains disabled/unconfigured because the authorized service credential, exact AgentServer URL and tenant/corp configuration are not available. No group message was claimed or fabricated. Local tests: 31 passed.

## GitHub transport remains separate

After HTTP access was restored, new real repository-hook pings still returned HTTP 502 from GitHub. Local browser reachability does not prove GitHub-source ingress is allowed. Governance's authenticated local polling remains the working discovery path.
