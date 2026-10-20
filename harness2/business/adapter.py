"""A genuine upstream BenchmarkAdapter for data-only deterministic business replay."""

import hashlib
import json
import re
from pathlib import Path

from ..core import tree
from ..core.spec import BenchPrompts, BenchSpec, ChannelSpec
from .contract import EXPECTED_SCHEMA, VERSION, validate, validate_episode, validate_result
from .safe_codex import SafeCodexSubstrate

BASE_PROMPT = "Analyse the synthetic episode. Return an advisory policy and next step.\n"
CLICK_RULE = "Treat click events as ambiguous evidence.\n"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def analyse(episode, prompt):
    """Reference offline responder, NOT a model or production message classifier.

    Typed fixture events drive this responder. Free text is untrusted and never executed.
    One prompt-dependent click behaviour gives the real recursion a visible contrast.
    """
    kind = episode["event"]["kind"]
    if episode["suppressed"] or episode["permission"] == "denied" or kind == "unsubscribe":
        policy, step = "suppress", "record_opt_out"
    elif kind == "click" and CLICK_RULE.strip() in prompt:
        policy, step = "insufficient", "verify_signal"
    elif episode["permission"] != "allowed":
        policy, step = "insufficient", "request_permission"
    elif kind == "quote_request":
        policy, step = "draft_only", "request_details"
    else:
        policy, step = "draft_only", "review_draft"
    return validate_result({
        "schema_version": VERSION, "episode_id": episode["episode_id"],
        "authority": "advisory_only", "policy": policy, "next_step": step,
        "evidence_event_ids": [episode["event"]["event_id"]],
    }, episode)


class BusinessAdapter:
    """No CRM import, transport, sender, model call or executable candidate surface."""

    def __init__(self, root: Path, dataset: Path):
        self.root = Path(root).resolve()
        rows = json.loads(Path(dataset).read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows:
            raise ValueError("Dataset must be a nonempty list of synthetic cases")
        self.cases = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"episode", "expected", "split"}:
                raise ValueError("Each case requires only episode, expected and split")
            episode = validate_episode(row["episode"])
            validate(EXPECTED_SCHEMA, row["expected"])
            if row["split"] not in ("dev", "holdout"):
                raise ValueError("Unknown dataset split")
            task_id = episode["episode_id"]
            if task_id in self.cases:
                raise ValueError("Duplicate episode id")
            self.cases[task_id] = row
        self.substrate = SafeCodexSubstrate()
        channel = ChannelSpec("opencode", "local/deterministic-business")
        self.spec = BenchSpec(
            name="business", runs_root=self.root / "runs", install_mode="codex_root",
            prompts=BenchPrompts(work="analyse synthetic correspondence and suggest an advisory next step"),
            channels={"proposer": channel, "selector": channel},
            allow_subagents=False, leak_globs=("*expected*", "*holdout*"),
        )
        manifest = {"schema_version": VERSION, "dataset_sha256": digest(rows),
                    "baseline_sha256": digest(BASE_PROMPT), "synthetic": True}
        path = self.root / "inputs.json"
        if path.exists() and json.loads(path.read_text()) != manifest:
            raise ValueError("Frozen inputs changed; use a new output directory")
        write_json(path, manifest)
        self.execution_count = 0
        if self.base_harness().exists():
            if (self.base_harness() / "AGENTS.md").read_text() != BASE_PROMPT:
                raise ValueError("Frozen baseline changed; use a new output directory")
        else:
            tree.write_tree(self.substrate.surface(), {"AGENTS.md": BASE_PROMPT}, self.base_harness(), stubs=False)
        for task_id, case in self.cases.items():
            write_json(self.task_files(task_id) / "episode.json", case["episode"])

    def tasks(self, split="all"):
        if split not in ("all", "dev", "holdout"):
            raise ValueError("Unknown split")
        return sorted(k for k, v in self.cases.items() if split == "all" or v["split"] == split)

    def domain_of(self, task_id):
        self.cases[task_id]
        return "correspondence"

    def task_prompt(self, task_id):
        self.cases[task_id]
        return "Analyse episode.json. Return a policy, next step and event evidence; advisory only."

    def task_files(self, task_id):
        self.cases[task_id]
        return self.root / "sources" / task_id

    def base_harness(self):
        return self.root / "baseline"

    def validate_tree(self, harness):
        if set(harness) != {"AGENTS.md"} or not harness["AGENTS.md"].strip():
            raise ValueError("Only nonempty AGENTS.md may change; no tools, hooks, scripts or authority")

    def execute(self, task_id, harness_dir, run_id, *, timeout=None):
        if not isinstance(run_id, str) or not all(
            re.fullmatch(r"[a-zA-Z0-9_-][a-zA-Z0-9_.-]*", part) for part in run_id.split("/")
        ):
            raise ValueError("Invalid run id")
        install = self.substrate.materialise(harness_dir or self.base_harness(), self.spec, {})
        prompt = (install.staging_dir / "AGENTS.md").read_text(encoding="utf-8")
        episode = self.cases[task_id]["episode"]
        identity = {"schema_version": VERSION, "episode_sha256": digest(episode),
                    "harness_sha256": digest(prompt), "run_id": run_id}
        run_dir = self.root / "executions" / run_id
        if run_dir.exists():
            if json.loads((run_dir / "identity.json").read_text()) != identity:
                raise ValueError("Run id already belongs to different frozen inputs")
            validate_result(json.loads(self.deliverable_text(run_dir)), episode)
            return run_dir
        answer = analyse(episode, prompt)
        write_json(run_dir / "answer.json", answer)
        write_json(run_dir / "identity.json", identity)
        (run_dir / "trajectory.md").write_text(
            "[ACTION] Offline typed-event replay; no model, tools or sender\n"
            + "[OBSERVATION] " + json.dumps(answer) + "\n", encoding="utf-8")
        self.execution_count += 1
        return run_dir

    def delivered(self, run_dir):
        try:
            result = json.loads(self.deliverable_text(run_dir))
            validate_result(result, self.cases[result["episode_id"]]["episode"])
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def trajectory(self, run_dir, *, obs_trunc):
        return (run_dir / "trajectory.md").read_text(encoding="utf-8")

    def deliverable_files(self, run_dir):
        return {"answer.json": self.deliverable_text(run_dir)}

    def deliverable_text(self, run_dir):
        return (run_dir / "answer.json").read_text(encoding="utf-8")

    def score(self, run_dir, task_id):
        result = validate_result(json.loads(self.deliverable_text(run_dir)), self.cases[task_id]["episode"])
        expected = self.cases[task_id]["expected"]
        passed = sum(result[k] == v for k, v in expected.items())
        return {"n_passed": passed, "n_criteria": 2, "all_pass": passed == 2}
