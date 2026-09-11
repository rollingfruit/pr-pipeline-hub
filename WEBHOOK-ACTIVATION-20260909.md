# GitHub Webhook activation

## Actual state

All 12 configured private repositories now have an ACTIVE hook owned by this Hub:

- URL: `http://119.8.233.58:8080/webhooks/github`
- Events: `pull_request`, `push`
- JSON body with HMAC SHA-256 signature validation
- Repo IDs registered; no historical PR scans, branch protection edits or merges
- Existing hooks belonging to other systems were not modified
- Exact hook IDs and GitHub delivery receipts: `.runtime/webhooks.json`

The first real GitHub ping deliveries all failed with HTTP 502 and status `failed to connect to host`. Their response headers are null and response body empty. They did not reach the control plane. Hook activation must not be described as a successful review trigger yet.

## Network diagnosis

- ECS nginx listens on `0.0.0.0:8080`; control plane loopback 8792 is healthy.
- Host INPUT policy is ACCEPT; firewalld is not running.
- Check cloud security group / network ACL / upstream access policy for GitHub ingress.
- GitHub `/meta` currently lists these IPv4 webhook sources: `192.30.252.0/22`, `185.199.108.0/22`, `140.82.112.0/20`, `143.55.64.0/20`.
- Allow TCP 8080 from those sources. Do not expose PostgreSQL, worker API or SSH to all sources as a workaround.

After the rules are corrected, run in WSL:

```bash
python3 redeliver_webhooks.py
python3 verify_webhooks.py
```

The second command requires an actual successful GitHub receipt per repository. A local curl or synthetic test is not equivalent.

## NewLink diagnosis

The active Windows Daemon is v26.3.32, runtime `3ec06f0f-06aa-47e1-92c4-076d43ab2266`, and its heartbeat is acknowledged. It connects to `https://api.cloudbeta.welink.huawei.com`, not the old Cloudflare address found in archived logs.

The authenticated local collaboration API confirms a completed `xiao-commitor` task:

- Agent: `2b6d5bef-1a74-4e13-8638-eb64ea35e869`
- Workspace: `f599cfe5-bc2b-4900-bf05-5e2dbe18a431`
- Task: `c11b0ce0-03df-43db-9726-269923713395`

This proves prior inbound group-to-agent execution, not permission for a new service to publish group messages. The CLI's persistent server/workspace configuration is empty because the desktop-managed daemon receives its configuration separately. The public execution-agent endpoint returns HTTP 401 without platform authentication.

The production AgentServer outbound credential has not been located in the inspected local CLI configuration. No expired task credential, fabricated source message or unauthenticated impersonation was used. ECS-authoritative Worker switching and automatic NewLink dispatch remain incomplete. The existing local runner is unchanged.
