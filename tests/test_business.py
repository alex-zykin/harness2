import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from harness2.business.adapter import BASE_PROMPT, CLICK_RULE, BusinessAdapter
from harness2.business.codex_adapter import BusinessCodexAdapter
from harness2.business.contract import (
    EPISODE_SCHEMA,
    RESULT_SCHEMA,
    validate_episode,
    validate_result,
)
from harness2.business.demo import run
from harness2.business.execution import ExecutionProfile, GatedDockerExecution
from harness2.business.safe_codex import SafeCodexSubstrate
from harness2.core.spec import BenchmarkAdapter
from harness2.substrate.base import Substrate


class SafeCodexTests(unittest.TestCase):
    def test_no_sandbox_or_hook_bypass(self):
        argv = SafeCodexSubstrate().exec_argv("Analyse synthetic mail", Path("/input"), "model")
        self.assertIn("--sandbox", argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertFalse(any("bypass" in arg for arg in argv))

    def test_prompt_is_after_option_terminator(self):
        argv = SafeCodexSubstrate().exec_argv("--dangerously-bypass-approvals-and-sandbox", Path("/input"), "model")
        self.assertEqual(argv[-2], "--")

    def test_live_execution_and_preflight_are_disabled(self):
        substrate = SafeCodexSubstrate()
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            substrate.execute("episode", None, ["test"], 1)
        with self.assertRaisesRegex(RuntimeError, "Offline"):
            substrate.preflight()

    def test_host_environment_is_not_inherited(self):
        env = SafeCodexSubstrate().exec_env({"SYNTHETIC_SECRET": "synthetic-not-a-secret"}, codex_home=Path("/tmp/codex"))
        self.assertNotIn("SYNTHETIC_SECRET", env)
        self.assertEqual(env["HOME"], "/tmp/home")

    def test_pinned_container_plan_has_no_host_home_or_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / "AGENTS.md").write_text(BASE_PROMPT)
            (source / "episode.json").write_text("{}")
            substrate = SafeCodexSubstrate()
            with self.assertRaisesRegex(ValueError, "digest"):
                substrate.container_plan("codex:latest", source, "Analyse", "model")
            plan = substrate.container_plan("example/codex@sha256:" + "a" * 64, source, "Analyse", "model")
            self.assertEqual(plan[plan.index("--network") + 1], "none")
            self.assertIn("--read-only", plan)
            self.assertIn("65532:65532", plan)
            self.assertFalse(any("bypass" in arg or "docker.sock" in arg for arg in plan))
            self.assertEqual(sum("type=bind" in arg for arg in plan), 1)
            (source / "private.txt").write_text("synthetic")
            with self.assertRaisesRegex(ValueError, "only"):
                substrate.container_plan("example/codex@sha256:" + "a" * 64, source, "Analyse", "model")


class ContractTests(unittest.TestCase):
    def test_rejects_unknown_version_and_authority(self):
        with self.assertRaises(ValueError):
            validate_episode({"schema_version": "999", "sender": "not-an-authority"})

    def test_result_cannot_overrule_suppression(self):
        episode = json.loads(Path("examples/business/synthetic.json").read_text())[0]["episode"]
        episode["suppressed"] = True
        answer = {"schema_version": "1.0", "episode_id": episode["episode_id"],
                  "authority": "advisory_only", "policy": "draft_only", "next_step": "review_draft",
                  "evidence_event_ids": [episode["event"]["event_id"]]}
        with self.assertRaises(ValueError):
            validate_result(answer, episode)

    def test_exported_json_schemas_match_runtime_contract(self):
        for name, schema in (("episode-v1", EPISODE_SCHEMA), ("result-v1", RESULT_SCHEMA)):
            self.assertEqual(json.loads(Path(f"schemas/{name}.schema.json").read_text()), schema)

    def test_unknown_nested_fields_and_non_synthetic_are_rejected(self):
        source = json.loads(Path("examples/business/synthetic.json").read_text())[0]["episode"]
        for mutation in (lambda e: e.update(synthetic=False),
                         lambda e: e.update(schema_version="2.0"),
                         lambda e: e["event"].update(sender="synthetic"),
                         lambda e: e.update(suppressed="false")):
            episode = copy.deepcopy(source)
            mutation(episode)
            with self.assertRaises(ValueError):
                validate_episode(episode)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.adapter = BusinessAdapter(self.root / "output", Path("examples/business/synthetic.json"))

    def test_real_upstream_protocols_and_label_free_source(self):
        self.assertIsInstance(self.adapter, BenchmarkAdapter)
        self.assertIsInstance(self.adapter.substrate, Substrate)
        self.assertEqual(self.adapter.spec.install_mode, "codex_root")
        self.assertEqual(len(self.adapter.tasks("dev")), 5)
        self.assertEqual(len(self.adapter.tasks("holdout")), 3)
        for task in self.adapter.tasks():
            files = list(self.adapter.task_files(task).iterdir())
            self.assertEqual([p.name for p in files], ["episode.json"])
            self.assertNotIn("expected", json.loads(files[0].read_text()))

    def test_frozen_input_changes_require_new_output(self):
        dataset = json.loads(Path("examples/business/synthetic.json").read_text())
        dataset[0]["episode"]["event"]["text"] = "Different synthetic input"
        changed = self.root / "changed.json"
        changed.write_text(json.dumps(dataset))
        with self.assertRaisesRegex(ValueError, "Frozen inputs"):
            BusinessAdapter(self.adapter.root, changed)

    def test_idempotent_execution_and_harness_identity(self):
        task = "synthetic-click"
        first = self.adapter.execute(task, None, "test/base")
        before = (first / "answer.json").read_bytes()
        self.assertEqual(self.adapter.execute(task, None, "test/base"), first)
        self.assertEqual((first / "answer.json").read_bytes(), before)
        self.assertEqual(self.adapter.execution_count, 1)
        candidate = self.root / "candidate"
        candidate.mkdir()
        (candidate / "AGENTS.md").write_text(BASE_PROMPT + CLICK_RULE)
        with self.assertRaisesRegex(ValueError, "different frozen inputs"):
            self.adapter.execute(task, candidate, "test/base")

    def test_candidate_code_config_and_path_escape_are_rejected(self):
        task = self.adapter.tasks()[0]
        candidate = self.root / "candidate"
        candidate.mkdir()
        (candidate / "AGENTS.md").write_text(BASE_PROMPT)
        (candidate / "scripts").mkdir()
        (candidate / "scripts" / "send.py").write_text("raise SystemExit('must not execute')")
        with self.assertRaisesRegex(ValueError, "Only AGENTS"):
            self.adapter.execute(task, candidate, "test/code")
        with self.assertRaisesRegex(ValueError, "Invalid run id"):
            self.adapter.execute(task, None, "../escaped")
        with self.assertRaisesRegex(ValueError, "Only nonempty"):
            self.adapter.validate_tree({"AGENTS.md": BASE_PROMPT, ".codex/hooks.json": "{}"})

    def test_suppression_permission_and_quote_outcomes(self):
        for task, expected in (("synthetic-refusal", ("suppress", "record_opt_out")),
                               ("synthetic-permission-holdout", ("insufficient", "request_permission")),
                               ("synthetic-quote", ("draft_only", "request_details"))):
            result = json.loads(self.adapter.deliverable_text(self.adapter.execute(task, None, f"case/{task}")))
            self.assertEqual((result["policy"], result["next_step"]), expected)
            with self.assertRaises(ValueError):
                validate_result({**result, "send": True}, self.adapter.cases[task]["episode"])
            with self.assertRaises(ValueError):
                validate_result({**result, "evidence_event_ids": ["other-event"]}, self.adapter.cases[task]["episode"])


class IntegrationTests(unittest.TestCase):
    def test_real_upstream_recursion_and_held_out_judging(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run(Path(temporary), Path("examples/business/synthetic.json"))
            self.assertEqual(result["done"], 5)
            self.assertEqual(result["failed"], 0)
            self.assertEqual(result["holdout_passed"], 3)
            self.assertTrue(result["upstream_evidence"])
            self.assertEqual(sum(row["all_pass"] for row in result["baseline_holdout"]), 2)
            self.assertFalse(result["production_promoted"])
            self.assertEqual((result["model_calls"], result["mail_sends"]), (0, 0))
            self.assertTrue(list(Path(temporary).glob("runs/**/summary.json")))
            self.assertTrue(list(Path(temporary).glob("library/**/INDEX.md")))
            for source in Path(temporary).glob("runs/**/context/source/episode.json"):
                self.assertNotIn("expected", json.loads(source.read_text()))


class GatedExecutionTests(unittest.TestCase):
    @staticmethod
    def response(task="synthetic-mail", event="synthetic-event-mail", policy="draft_only", step="review_draft"):
        answer = {"schema_version": "1.0", "episode_id": task, "authority": "advisory_only",
                  "policy": policy, "next_step": step, "evidence_event_ids": [event]}
        stream = json.dumps({"type": "item.completed", "item": {
            "id": "synthetic-item", "type": "agent_message", "text": json.dumps(answer)}}) + "\n"
        return SimpleNamespace(returncode=0, stdout=stream, stderr="")

    def test_default_gate_never_calls_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = []
            profile = ExecutionProfile(Path(temporary), "example/codex@sha256:" + "a" * 64, "model")
            executor = GatedDockerExecution(profile, lambda *a, **k: calls.append(a))
            with self.assertRaisesRegex(RuntimeError, "allow_model_run"):
                executor.preflight()
            self.assertEqual(calls, [])

    def test_connected_upstream_adapter_executes_once_and_resumes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []
            def transport(argv, **kwargs):
                calls.append(argv)
                self.assertNotIn("HOME", kwargs["env"])
                return self.response()
            profile = ExecutionProfile(root / "model", "example/codex@sha256:" + "a" * 64,
                                       "synthetic-model", True, "synthetic-approval")
            adapter = BusinessCodexAdapter(root, Path("examples/business/synthetic.json"), GatedDockerExecution(profile, transport))
            self.assertIsInstance(adapter, BenchmarkAdapter)
            directory = adapter.execute("synthetic-mail", None, "connected/one")
            self.assertTrue(adapter.delivered(directory))
            self.assertTrue(adapter.score(directory, "synthetic-mail")["all_pass"])
            self.assertEqual(adapter.execute("synthetic-mail", None, "connected/one"), directory)
            self.assertEqual(len(calls), 1)
            self.assertIn("--pull", calls[0])
            self.assertNotIn("--privileged", calls[0])

    def test_timeout_is_terminal_and_stops_only_own_container(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []
            def transport(argv, **kwargs):
                calls.append(argv)
                if "run" in argv:
                    raise subprocess.TimeoutExpired(argv, 1)
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            profile = ExecutionProfile(root / "model", "example/codex@sha256:" + "a" * 64,
                                       "synthetic-model", True, "synthetic-approval")
            adapter = BusinessCodexAdapter(root, Path("examples/business/synthetic.json"), GatedDockerExecution(profile, transport))
            with self.assertRaises(subprocess.TimeoutExpired):
                adapter.execute("synthetic-mail", None, "timeout/one", timeout=1)
            with self.assertRaisesRegex(RuntimeError, "never auto-retry"):
                adapter.execute("synthetic-mail", None, "timeout/one", timeout=1)
            self.assertEqual(sum("run" in call for call in calls), 1)
            launched = calls[0][calls[0].index("--name") + 1]
            self.assertTrue(launched.startswith("h2-business-"))
            self.assertEqual(calls[1][-1], launched)
            attempt = json.loads((root / "model/executions/timeout/one/attempt.json").read_text())
            self.assertEqual(attempt["cleanup"], "stopped")
            self.assertEqual(attempt["status"], "uncertain_or_rejected")

    def test_isolated_network_gateway_and_result_policy_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []
            network = {"Internal": True, "Driver": "bridge", "EnableIPv6": False,
                       "Options": {"com.docker.network.bridge.gateway_mode_ipv4": "isolated"},
                       "Containers": {"gateway": {"Name": "business-model-gateway", "IPv4Address": "172.30.1.2/24"}}}
            def transport(argv, **kwargs):
                calls.append(argv)
                if "inspect" in argv:
                    return SimpleNamespace(returncode=0, stdout=json.dumps([network]), stderr="")
                if "stop" in argv:
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                return self.response("synthetic-refusal", "synthetic-event-refusal")
            profile = ExecutionProfile(root / "model", "example/codex@sha256:" + "a" * 64,
                                       "synthetic-model", True, "synthetic-approval", "synthetic-network")
            adapter = BusinessCodexAdapter(root, Path("examples/business/synthetic.json"), GatedDockerExecution(profile, transport))
            with self.assertRaisesRegex(ValueError, "overrule"):
                adapter.execute("synthetic-refusal", None, "invalid/one")
            launched = next(call for call in calls if "run" in call)
            self.assertEqual(launched[launched.index("--network") + 1], "synthetic-network")
            self.assertIn('model_providers.business_gateway.base_url="http://172.30.1.2:8765/v1"', launched)
            self.assertFalse((root / "model/executions/invalid/one/answer.json").exists())

    def test_internal_bridge_without_isolated_gateway_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            network = {"Internal": True, "Driver": "bridge", "EnableIPv6": False,
                       "Containers": {"gateway": {"Name": "business-model-gateway", "IPv4Address": "172.30.1.2/24"}}}
            transport = lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps([network]), stderr="")
            profile = ExecutionProfile(Path(temporary), "example/codex@sha256:" + "a" * 64,
                                       "synthetic-model", True, "synthetic-approval", "synthetic-network")
            with self.assertRaisesRegex(ValueError, "isolated"):
                GatedDockerExecution(profile, transport).preflight()

    def test_explicit_gate_executes_container_and_validates_codex_stream(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = BusinessAdapter(Path(temporary) / "replay", Path("examples/business/synthetic.json"))
            task = "synthetic-mail"
            episode = adapter.cases[task]["episode"]
            calls = []
            answer = {"schema_version": "1.0", "episode_id": task, "authority": "advisory_only",
                      "policy": "draft_only", "next_step": "review_draft",
                      "evidence_event_ids": [episode["event"]["event_id"]]}
            stream = json.dumps({"type": "item.completed", "item": {
                "id": "synthetic-item", "type": "agent_message", "text": json.dumps(answer)}}) + "\n"
            def transport(argv, **kwargs):
                calls.append(argv)
                return SimpleNamespace(returncode=0, stdout=stream, stderr="")
            profile = ExecutionProfile(Path(temporary) / "model", "example/codex@sha256:" + "a" * 64,
                                       "synthetic-model", True, "synthetic-approval")
            executor = GatedDockerExecution(profile, transport)
            install = adapter.substrate.materialise(adapter.base_harness(), adapter.spec, {})
            runs = executor.execute(adapter.substrate, adapter.task_files(task) / "episode.json", install, ["one"], 5)
            self.assertEqual(json.loads((runs[0] / "answer.json").read_text()), answer)
            self.assertTrue(any("run" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
