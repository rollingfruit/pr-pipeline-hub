# Local GitHub PR monitor

## 2026-09-09 PR inventory update

- Current polling scope remains `rollingfruit/agent-governance-gw`, not all twelve repositories.
- Every scan paginates GitHub `pulls?state=all`; the ECS monitor snapshot now contains all PRs, including closed/merged history. Historical inventory does not enqueue historical builds.
- `/reviews` is the dedicated PR navigation destination, available even with zero execution records. Each PR shows its state/head and associated execution attempts; unexecuted PRs are explicitly marked.
- `/` remains the execution overview; `/runs/{id}` preserves evidence detail links. HTML responses use `Cache-Control: no-store` to avoid retaining an old navigation bundle on future loads.
- On 2026-09-09 at 17:24 local time the authenticated monitor had synchronized 102 PRs (5 open), with zero pending transport events. NewLink is not required for this ingestion path.
- Tests: monitor history/no-retroactive-build/durable-retry/closure tests; browser checks cover sidebar navigation, direct reload, inventory/API row agreement, execution detail, existing evidence, and 1440/1920/390 widths. These UI checks do not rerun business E2E.

Earlier checkpoints below describe the previous implementation and may contain superseded connectivity/status statements.

Enabled for `rollingfruit/agent-governance-gw` using the existing Windows GitHub CLI authentication from WSL.

- Service: `pr-github-monitor.service`, enabled at WSL boot, checks approximately every 60 seconds.
- State and pending event outbox: `/root/.local/share/newlink-pr-e2e/pr-monitor/governance.json`.
- SSH transfers events to the existing ECS queue. GitHub inbound access to port8080 is not required for this path.
- First scan records existing open PRs without backfilling builds. New PRs, new head commits, ready-for-review, reopen and observed close/merge transitions are submitted.
- Failed uploads retain the exact event for retry. Poll and Webhook events deduplicate against the same repository/PR/head identity.
- This is an ingestion monitor, not another build queue. The unfinished Agent dispatch/queue consumer integration remains visible as incomplete; ingestion does not prove review/E2E success.
- Target-branch-only updates and transient PR changes that both occur between polls are not guaranteed to be observed by this fallback. Keep Webhooks for the eventual complete event path.
- Windows/WSL must remain running, with GitHub authentication and SSH connectivity available. A sleeping machine cannot poll.

Status is shown in `http://119.8.233.58:8080/runners` with the usual viewer authorization.

```bash
systemctl status pr-github-monitor
journalctl -u pr-github-monitor -n 10 --no-pager
systemctl stop pr-github-monitor
systemctl start pr-github-monitor
```

At startup verification, PR #102 had already merged at `2026-09-09T06:16:59Z`; the newest still-open PR was #96. No retrospective pre-merge pass was created for #102.
# 2026-09-09 更新：本机选择入队和真实 Codex 检视

- 本机操作入口：http://127.0.0.1:8793/ 。当前监听 governance 仓库，列出开放 PR，点击入队后重新读取 GitHub 的 PR 状态和当前目标分支 SHA。
- ECS 看板“运行环境”增加本机操作入口链接。远端仍为只读，操作入口仅在运行 WSL 的这台机器可用。
- `pr-local-selection` 为 loopback-only 服务，校验 Host、Origin 和页面会话令牌；拒绝匿名 POST 和跨域写入。
- `.runtime/ecs-worker.enabled` 开启现有 Hub 的 ECS 单 Worker。现有本机 `POST /api/runs` 需要触发令牌；ECS 模式接受 browser-e2e / merge，诊断与旧 code-review 参数不会隐式运行。
- Worker 使用本机订阅 Codex、专用 E2E 认证目录和原有代理，执行只读检视并保存结构化 findings；不是 NewLink `xiao-commitor` 的任务回执。
- E01/E02/E03 必跑，路径规则与 Agent 可以追加 DR/DR-contract；未实现用例不能选为通过。构建高风险变更仍阻塞等待人工确认。
- SSH 心跳每 10 秒，服务端租约 180 秒，暂时失败重试；失联 120 秒停止后续阶段。中断后的环境核对通过 `recover_local_worker.py RUN_ID`，不得直接把中断记录改为通过。
- 明确重试：`python3 local_selection.py --retry 96`。只允许完成或已核对的阻塞记录重试，生成新运行 ID，保留旧记录；普通重复提交仍幂等。

本次实测：`20260909-151610-1d2d0e`，PR #96，head `26ef54c2a9ca59ce590730242796486f6118d332`，base `97aa3a8b32f94da729527e590927808d892424cb`。
真实 Codex 检视完成、环境检查通过；合并预演发现 `docs/openapi.source.json`、`internal/coordinator/service.go`、`internal/coordinator/types.go` 冲突。构建及 E2E 被跳过，不能作为 E2E 成功证据。
报告 11 个文件已传 ECS，GitHub 状态 failure，评论：https://github.com/rollingfruit/agent-governance-gw/pull/96#issuecomment-5597839864 。

剩余限制：NewLink 出站鉴权仍未打通；公网 8080 从当前本机实测超时（SSH 可达、服务器 nginx 监听正常），不能宣称群内分享访问已验证。未重新验证无冲突 PR 的全套 E2E 成功。

以下为此前监听阶段记录，执行器“尚未接通”的描述已由上述更新替代。
