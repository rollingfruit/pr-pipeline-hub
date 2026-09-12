# dev-gamma P0 stability result

Date: 2026-09-12

## Result

The requested ten successful E01-E06 rounds completed. The original persistent
experiment passed rounds 1-6 and stopped at round 7 when its established nested
SSH transport became inactive. That failed attempt remains unchanged. After
evidence-gated cleanup and SSH reconnect hardening, four continuation rounds
completed successfully.

- Successful target slots: 10/10
- Actual attempts needed for those slots: 11
- First-attempt pass rate across those attempts: 10/11 (90.9%)
- Post-hardening continuation: 4/4 (100%)
- Additional post-hardening diagnostic: 1/1 (100%)
- Post-hardening total: 5/5 (100%)
- Archive verification failures: 0
- Successful cleanup records with active residuals: 0
- Operator intervention: one evidence-gated recovery after the failed attempt

This is not a claim that the original experiment passed 10/10. Its immutable
result is 6/7 before interruption. The continuation records are separate tasks.

## Attempts

| Slot | Child run | Result | Duration | Cleanup | Active residuals |
| --- | --- | --- | ---: | --- | ---: |
| 1 | `gamma-check-20260912-123750-51f291` | passed | 587s | passed | 0 |
| 2 | `gamma-check-20260912-124753-40c7d1` | passed | 581s | passed | 0 |
| 3 | `gamma-check-20260912-125747-ef6ba9` | passed | 589s | passed | 0 |
| 4 | `gamma-check-20260912-130748-a0ea12` | passed | 589s | passed | 0 |
| 5 | `gamma-check-20260912-131748-ada25d` | passed | 588s | passed | 0 |
| 6 | `gamma-check-20260912-132748-02d015` | passed | 557s | passed | 0 |
| 7, failed attempt | `gamma-check-20260912-133717-f7529f` | environment error | 316s | recovered separately | 0 after recovery |
| 7, continuation | `gamma-check-20260912-152108-1ff835` | passed | 564s | passed | 0 |
| 8 | `gamma-check-20260912-153123-90516c` | passed | 584s | passed | 0 |
| 9 | `gamma-check-20260912-154224-c59795` | passed | 581s | passed | 0 |
| 10 | `gamma-check-20260912-155255-c47cb6` | passed | 581s | passed | 0 |

The independent post-change diagnostic was
`gamma-check-20260912-145826-1429b9` and passed in 580 seconds.

## Failure classification

The failed attempt was an infrastructure error, not an observed product
assertion regression. The nested Paramiko transport reported `Broken pipe` and
then `SSH session not active`. E01-E04 had already passed. E05 tool-failure,
E05 terminal-failure and E06 event-replay could no longer reach the forwarded
application, and business inventory cleanup could not be verified through the
same dead connection.

The recovery created a fresh SSH connection, removed four bot bindings,
deactivated the fixture account, stopped the daemon, verified the runtime
offline, verified the archive and released quarantine with zero active
residuals. It did not rewrite the failed attempt.

## Hardening verification

The access layer now checks both jump-host and nested node transports before
opening a forwarded channel. Reconnects are serialized, dead clients are closed,
and channel creation is retried once on a fresh connection. A forced disconnect
test returned HTTP 200 before and after reconnect. Three focused reconnect tests,
44 Gamma tests and four disposable PostgreSQL queue/fencing/recovery tests pass.
