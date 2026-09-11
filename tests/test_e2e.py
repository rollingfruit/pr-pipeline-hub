import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import e2e_catalog as catalog
import e2e_runner
from pr_pipeline_hub import PipelineHub


class E2ETest(unittest.TestCase):
    def test_head_only_is_explicit_diagnostic_and_never_full_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            hub = self.pipeline(directory)
            args = ("https://github.com/rollingfruit/agent-governance-gw/pull/101", "test", "http://localhost")
            with self.assertRaises(ValueError):
                hub.create_run(*args, profile="browser-e2e", source_mode="pr-head")
            run = hub.create_run(*args, profile="browser-e2e", source_mode="pr-head", diagnostic=True)
            self.assertFalse(run["full_acceptance"])
            self.assertTrue(run["diagnostic"])

    def test_metadata_uses_live_target_branch_not_pr_cached_base(self):
        with tempfile.TemporaryDirectory() as directory:
            hub = self.pipeline(directory)
            run = hub.create_run("https://github.com/rollingfruit/agent-governance-gw/pull/96", "test", "http://localhost", profile="browser-e2e")
            runner = e2e_runner.E2ERunner(hub, hub.runs[run["id"]])
            with mock.patch.object(hub, "_gh_json", side_effect=[
                    {"baseRefName": "main", "baseRefOid": "old"}, {"object": {"sha": "current"}}]):
                self.assertEqual(runner.metadata()["baseRefOid"], "current")

    def test_selection_is_independent_of_pr_number(self):
        selected, full = catalog.select_suites("rollingfruit/agent-governance-gw", 96)
        self.assertTrue(full)
        self.assertEqual([s["id"] for s in selected], ["E01", "E02", "E03"])
        selected, full = catalog.select_suites("rollingfruit/agent-governance-gw", 96, ["E01"])
        self.assertFalse(full)
        self.assertEqual([s["id"] for s in selected], ["E01"])

    def test_rejects_unimplemented_empty_and_bad_selections(self):
        for selection in ([], ["E04"], ["unknown"], "E01", [1]):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                catalog.select_suites("a/b", 1, selection)

    def test_zero_skipped_missing_and_duplicate_evidence_cannot_pass(self):
        good = {"id": "rule", "suite": "DR", "status": "passed", "evidence": ["trace.zip"]}
        bad = [[], [good], [good, good], [good, {**good, "id": "model", "status": "skipped"}],
               [good, {**good, "id": "model", "evidence": []}]]
        for cases in bad:
            with self.subTest(cases=cases), self.assertRaises(ValueError):
                catalog.validate_result({"tests": cases}, "DR")
        self.assertEqual(len(catalog.validate_result({"tests": [good, {**good, "id": "model"}]}, "DR")), 2)

    def pipeline(self, directory):
        with mock.patch.object(PipelineHub, "_find_gh_cli", return_value="gh"), mock.patch.object(PipelineHub, "_worker"):
            return PipelineHub(Path(directory))

    def test_existing_profile_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            hub = self.pipeline(directory)
            run = hub.create_run("https://github.com/rollingfruit/agent-governance-gw/pull/96", "test", "http://localhost:8787")
            self.assertEqual(run["profile"], "code-review")
            self.assertEqual([s["id"] for s in run["stages"]], [s[0] for s in hub.STAGES])

    def test_real_environment_failure_is_error_not_test_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            hub = self.pipeline(directory)
            run = hub.create_run("https://github.com/rollingfruit/agent-governance-gw/pull/96", "test", "http://localhost:8787", profile="browser-e2e")
            runner = e2e_runner.E2ERunner(hub, hub.runs[run["id"]])
            meta = {"state": "OPEN", "title": "test", "headRefOid": "a" * 40, "baseRefOid": "b" * 40,
                    "headRefName": "feature", "baseRefName": "main"}
            states = []
            def github(argv):
                if argv[0] == "pr": return meta
                if "/git/ref/heads/" in argv[1]: return {"object": {"sha": meta["baseRefOid"]}}
                if '/files?' in argv[1]: return [[{'filename':'README.md'}]]
                states.append(argv)
                return {"id": 10}
            with mock.patch('local_agent_review.review'), mock.patch.object(hub, "_gh_json", side_effect=github), mock.patch.object(runner.stack, "doctor", return_value={
                "ok": False, "checks": [{"name": "model-auth", "ok": False, "detail": "not configured"}], "revisions": {}}):
                runner._execute_locked()
            actual = hub.runs[run["id"]]
            self.assertEqual(actual["failure_kind"], "error")
            self.assertEqual(actual["failure_stage"], "preflight")
            self.assertEqual(actual["test_results"], [])
            self.assertEqual(actual["github"]["state"], "error")
            self.assertTrue((Path(directory) / "runs" / run["id"] / "artifacts/report.html").exists())
            self.assertIn("state=pending", states[0])
            self.assertIn("state=error", states[-1])
            self.assertFalse(any("target_url" in a for a in states[-1]))

    def test_diagnostic_does_not_write_github(self):
        with tempfile.TemporaryDirectory() as directory:
            hub = self.pipeline(directory)
            run = hub.create_run("https://github.com/rollingfruit/agent-governance-gw/pull/96", "test", "http://localhost:8787", profile="browser-e2e", diagnostic=True)
            runner = e2e_runner.E2ERunner(hub, hub.runs[run["id"]])
            with mock.patch.object(hub, "_gh_json") as github:
                runner.publish("error")
                github.assert_not_called()


if __name__ == "__main__":
    unittest.main()
