import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pr_pipeline_hub as hub


class HelpersTest(unittest.TestCase):
    def test_message_id_is_durable_and_conflicting_reuse_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
                hub.PipelineHub, "_find_gh_cli", return_value="gh"), mock.patch.object(
                hub.threading.Thread, "start"):
            pipeline = hub.PipelineHub(Path(directory))
            args = ("https://github.com/rollingfruit/agent-governance-gw/pull/96", "group", "http://localhost")
            first = pipeline.create_run(*args, profile="browser-e2e", request_id="group:message")
            again = pipeline.create_run(*args, profile="browser-e2e", request_id="group:message")
            self.assertEqual(first["id"], again["id"])
            self.assertEqual(pipeline.queue.qsize(), 1)
            restored = hub.PipelineHub(Path(directory))
            self.assertEqual(restored.queue.get_nowait(), first["id"])
            self.assertEqual(restored.runs[first["id"]]["status"], "queued")
            with self.assertRaises(ValueError):
                restored.create_run(*args, profile="code-review", request_id="group:message")

    def test_go_toolchain_uses_repository_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "go.mod").write_text(
                "module example.com/demo\n\ngo 1.23.0\n\ntoolchain go1.24.6\n",
                encoding="utf-8",
            )
            self.assertEqual(hub.PipelineHub._go_toolchain(workspace), "go1.24.6")

    def test_find_git_cli_prefers_wsl_native_git(self):
        with mock.patch.object(hub.shutil, "which", return_value="/usr/bin/git"):
            self.assertEqual(hub.PipelineHub._find_git_cli(), "/usr/bin/git")

    def test_parse_pr_url(self):
        self.assertEqual(
            hub.parse_pr_url("https://github.com/rollingfruit/agent-governance-gw/pull/70"),
            ("rollingfruit", "agent-governance-gw", 70),
        )

    def test_parse_pr_url_rejects_non_github_url(self):
        with self.assertRaises(ValueError):
            hub.parse_pr_url("https://example.com/owner/repo/pull/70")

    def test_redact_github_token_and_header(self):
        value = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB Authorization: bearer secret-value"
        result = hub.redact(value)
        self.assertNotIn("ghp_", result)
        self.assertNotIn("secret-value", result)

    def test_create_run_enforces_repository_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(hub.PipelineHub, "_find_gh_cli", return_value="gh"):
                pipeline = hub.PipelineHub(Path(directory))
            with self.assertRaises(PermissionError):
                pipeline.create_run(
                    "https://github.com/another/repository/pull/1",
                    "tester",
                    "http://localhost:8787",
                )

    def test_create_run_uses_public_base_url(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(hub.PipelineHub, "_find_gh_cli", return_value="gh"):
                pipeline = hub.PipelineHub(Path(directory), "https://pipeline.example.internal/")
            with mock.patch.object(pipeline.queue, "put"):
                run = pipeline.create_run(
                    "https://github.com/rollingfruit/agent-governance-gw/pull/70",
                    "tester",
                    "http://localhost:8787",
                )
            self.assertEqual(
                run["web_url"],
                f"https://pipeline.example.internal/runs/{run['id']}",
            )

    def test_create_run_can_embed_view_token_for_group_link(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {"PIPELINE_EMBED_VIEW_TOKEN": "true", "PIPELINE_VIEW_TOKEN": "read-only token"}
            with mock.patch.dict("os.environ", env, clear=False), mock.patch.object(
                hub.PipelineHub, "_find_gh_cli", return_value="gh"
            ):
                pipeline = hub.PipelineHub(Path(directory), "https://pipeline.example.internal")
                with mock.patch.object(pipeline.queue, "put"):
                    run = pipeline.create_run(
                        "https://github.com/rollingfruit/agent-governance-gw/pull/70",
                        "tester",
                        "http://localhost:8787",
                    )
            self.assertEqual(
                run["web_url"],
                f"https://pipeline.example.internal/runs/{run['id']}?access_token=read-only+token",
            )


if __name__ == "__main__":
    unittest.main()
