# Same-site CI entry, 2026-09-11

## Public entry

- Robot CI: http://119.8.233.58/
- Pipeline: http://119.8.233.58/pipeline/
- Branch submission: http://119.8.233.58/submit/
- All Pipeline pages, API, logs and downloads use the existing Robot CI session.
- Basic Auth and view tokens are not used. HTML/SVG evidence is downloaded, not
  executed with the site's origin. HTTP remains an explicit demonstration limitation.

## Ownership and ports

Nginx owns public port 80. Robot CI listens on **127.0.0.1:18082**, not 18080:
the test Compose manifest already reserves 18080 for Multica. Control/editor/worker
remain on loopback 8792/8793/8794. The former default Nginx static site is loopback
18081. Public 8080, 443 and the legacy 8788 proxy are retired.

`/etc/pr-e2e/config.toml` holds `auth_mode = "robot-session"`, the public Pipeline
URL, editor URL and `robot_auth_url`. Systemd preserves the public cookie name and
bind settings for Robot CI. Its existing user/session database is unchanged.

## Execution

Branch batches contain repository IDs, branch names and full frozen SHAs, with
null PR identity. No merge is performed. Nonselected dependencies reuse the
frozen integration images in `/etc/pr-e2e/artifact-baseline.json`; selected
repositories are built from detached baseline/candidate sources. The manifest
records image identities, selected tests and the authenticated submitter.

`monitor`, `webhook`, `github_write` and `code_review` are disabled. Eleven owned
GitHub hooks were disabled; their IDs are in
`/var/lib/pr-e2e/state/retired-pr-hooks.json`. Other hooks were not changed.
GitHub credentials are still required for explicit branch discovery and clone.

Both manual branches and Robot CI image handoff use the existing single queue.
Neither a successful build nor a successful submission implies E2E passed.

## Deployment and rollback

Initial consistent database/config backup:
`/var/backups/pr-e2e/same-site-20260911T024121Z`.
The Nginx main configuration also has a timestamped pre-change backup. Additional
Robot CI code from a concurrent deployment was preserved under
`/var/backups/pr-e2e/robot-*-other-deployment-20260911.*` and merged with this change.

The session adapter now uses Robot CI's existing `/api/auth/me` contract and
requires a nonempty string `user`; an anonymous HTTP 200 is not authorization.
Nginx calls editor loopback `/internal/session`, which is blocked at the public
proxy. Legacy `robot_auth_url` values ending in `/api/auth/pipeline` are adapted
to `/api/auth/me`. Robot CI no longer needs the optional auth endpoint patch.
Keep the Gamma image bridge in the maintained Robot CI release; do not overwrite
active build code with an unrelated package. Login contract changes must pass
the session tests before rollout. Authentication errors never grant access.

The September 11 authentication repair backs up and restarts the editor and
control API to refresh their imported adapter, then reloads Nginx; it does not
restart Robot CI, the Worker, or any cluster workload.
Entry point: `deploy/cloud/deploy-session-adapter.py`.

Stop submissions, drain both build and E2E queues, back up, then deploy compatible
code. Do not interrupt active builds by restarting Robot CI. Rollback retains the
single public auth proxy and frozen run records; never restore public anonymous
Hub access or the old Basic Auth password. If the auth backend fails, access is
denied rather than bypassed.

Browser validation: `deploy/cloud/verify-same-site.cjs`; credentials are process
environment values only. `PIPELINE_SUBMIT=1` explicitly enables a real submission.
Default verification covers login, fake identity, branches, mobile/desktop,
history navigation, cross-site denial and logout. Screenshots stay in `.runtime`.

## Acceptance records

### September 11 session repair and Gamma preparation

- Deployed adapter backup: `/var/backups/pr-e2e/session-adapter-20260911T043837Z`.
- Deployed guard/editor backup: `/var/backups/pr-e2e/gamma-guard-20260911T043639Z`.
- Anonymous `/submit/` and `/pipeline/`: 302; protected API: 401;
  forged identity/cookie: 401; public internal-session path: 404.
- Editor now has one test branch per repository. Default-branch comparison stays
  in advanced options; selection changes invalidate resolved versions.
- Five adapter tests, five branch tests and four Gamma bridge tests passed.
  UI fixture tests passed at 1440/1920/390; these are not live E2E evidence.
  The full CCE unit module could not run in the local bundled Python because
  `huaweicloudsdkcore` is not installed; no SDK was installed into system Python.
- Via the existing CCE adapter, dev-gamma `governance`, `mattermost` and
  `multica-server` were each 1/1 Ready. Router endpoint
  `http://172.31.1.212/api/v4/system/ping` returned HTTP 200 from the cluster node.
- No shared cluster images or databases were changed. Dedicated test identity,
  CI Runtime binding, real-cluster runner, shared environment lock and guarded
  image restoration still need integration/acceptance. The existing CCE test
  option now fails before deployment rather than changing images and then
  reporting that testing is unsupported. Do not advertise real Gamma E2E as ready.
- Logged-in browser acceptance still requires the user's existing Robot CI
  session. No temporary account, password reset or session impersonation was used.

- Branch submission: http://119.8.233.58/pipeline/batches/batch-branch-136957d6411e3679ecba60bb3d3f3ad3
- Governance `main`: `d198100fb0156cc1d55012509097422028af118e`.
- Multica `main`: `9c1315092c2ba97e6565434e531e4c13c927e078`.
- Both selected sources were resolved and built; baseline E01 passed, E02 failed.
  Candidate/E03 did not run. This is a real failed E2E result, not merge approval.
- Build handoff: http://119.8.233.58/pipeline/batches/gamma-99e9765924d6 .
  Exact build artifact handed to the same queue; final assertion result is recorded there.
- Browser checks passed at 1440/1920/390, including restored login, branch submit,
  history navigation and logout. Protected video returns HTTP 206 for byte ranges;
  HTML reports download as attachments; anonymous evidence access redirects to login.
- The interrupted build `97d75b0a86d5` and initial failed branch attempts remain
  preserved. No old results were relabeled as passed.
- Robot CI integration PR: https://github.com/censong574-spec/robot-ci/pull/11 .
  It incorporates upstream `b4c0cfc` and the same-site changes; do not deploy upstream
  main alone before the integration is merged.
