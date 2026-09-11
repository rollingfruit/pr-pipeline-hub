# Incremental dashboard deployment

- `/` and `/reviews` now show the same incremental PR dashboard, with eleven repository filters. Mattermost remains a test adapter and is not polled by this dashboard worker. Existing historical records and repository hooks are not deleted.
- Local personal GitHub CLI authentication is reused. Each repository has an independent persisted baseline and outbox. Existing governance baseline is preserved; other repositories establish initial snapshots without submitting historical builds. New PR events use the existing ECS intake, not a second queue.
- Timeline merges observed PR metadata with execution attempts, sorted by latest PR update or execution creation time. Poll receipt time never moves an old PR to the top. Multiple attempts remain accessible. Unknown timestamps go into history.
- Older than rolling 24 hours is collapsed, not deleted. Running and queued attempts remain visible regardless of age. The current execution band is independent of repository/search filters. Rows render in batches of 30 with scrolling and a load-more fallback.
- Clicking a live execution opens an authenticated, five-second refreshed detail preview with actual stage logs; the full existing report page remains accessible. No task is synthesized when idle.
- A listening indicator means a recent successful PR snapshot, not E2E support or success for that repository. Authenticated polling is the working transport; this change does not claim GitHub Webhook delivery or NewLink outbound authentication has been fixed.
- HTTP viewer access remains read-only and keeps the existing shared token. Build/run triggering is unchanged.

Verification: TypeScript/Vite production build, five polling unit tests (including repository routing, no initial enqueue, durable retry), and `scripts/verify-incremental.cjs` across 1440/1920/390. Tests read real deployed inventories and old PR101 evidence. A separate browser-only fixture validates the idle-otherwise running preview; it is never submitted to the backend and is not an E2E execution result.
