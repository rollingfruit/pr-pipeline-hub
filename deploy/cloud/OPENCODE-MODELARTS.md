# OpenCode / ModelArts E2E integration

## Configuration deployed

- CLI: OpenCode 1.18.30, pinned on local WSL and CI.
- Agent provider: `opencode`, model `modelarts/deepseek-v4-flash`.
- Provider URL: `https://api.modelarts-maas.com/v2`.
- GM uses the same real ModelArts chat API directly; no Codex subscription adapter.
- CI provider config: `/var/lib/pr-e2e/state/opencode/opencode.json`.
- CI secret: `/var/lib/pr-e2e/state/opencode/modelarts-key`, mode 0600, owned by pr-e2e.
- CI runtime settings: `/var/lib/pr-e2e/state/settings.json`, mode 0600.
- No API key is embedded in this repository, CLI arguments, reports or container images.
- Codex code review remains disabled. CI is the only active Worker; old WSL execution services are stopped.

Daemon startup, runtime discovery and browser bot creation now select `AGENT_PROVIDER` instead of hardcoding Codex. Legacy profiles default to Codex. OpenCode profiles do not require a Codex login. GH and Pipeline control credentials are removed from the daemon environment.

## Actual validation

Real OpenCode 1.18.30 read-file tool smokes passed on local WSL and CI with DeepSeek. Each generated an unpredictable file, required a completed tool event, and checked the final answer against that file. CI completed in 8.572 seconds. This is tool integration evidence, not full browser E2E acceptance.

The previous Qwen deployment was rejected because:

| Request | Result |
| --- | --- |
| Plain chat | HTTP 200, nonempty model response |
| tools + tool_choice=auto | HTTP 400, ModelArts.81001 |

Provider error: `"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set`.

This is not an authentication error. The configured model deployment must support automatic function calling for OpenCode's real tool loop. Do not force tool_choice=none, manufacture tool results or relax E02/E03 assertions to turn this into a pass.

CI standalone Python needs the host CA bundle through `SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt`; certificate verification remains enabled. CLI subprocesses must receive closed stdin (`DEVNULL`) and an explicit workspace (`--dir`). The previous startup timeout was caused by inherited open stdin. Current evidence is `/var/lib/pr-e2e/state/opencode-smoke/smoke-report.json`.

The CI runtime preflight requires a fresh successful OpenCode tool smoke through `OPENCODE_SMOKE_REPORT`. A failed or missing smoke blocks E2E runtime readiness, while source/image building remains available. CI Worker, editor and publisher are active. Browser baseline and joint-candidate acceptance are still in progress.

11 configuration/stack/contract unit tests passed. These are not browser E01/E02/E03 acceptance.

## Reproducible checks

`configure_opencode.py` reads the API key exclusively from stdin and generates the isolated provider config; use `--settings` to update the runtime profile.

`probe_modelarts.py --key-file <private-key-file>` checks real plain chat and automatic function calling without printing credentials.

`smoke_opencode.py --cli <opencode-path> --directory <isolated-smoke-directory> --config <provider-config>` generates a random file, asks the real agent to read it, and requires both a completed tool event and the correct response. Output is a sanitized `smoke-report.json`, not a PR acceptance report.

The endpoint has a one-request-per-second quota. Direct diagnostic probes are paced; real Agent retry/rate-limit behavior must also be observed during browser E01/E02/E03. Do not remove tool assertions or substitute canned responses on quota errors.

References: https://opencode.ai/docs/providers/ and https://opencode.ai/docs/config/
