"""Deterministic upstream recursion over synthetic business cases."""

import argparse
import json
from pathlib import Path

from ..core.judge import judge_one
from ..core.proposer import Proposer, Reply
from ..core.schedule import ns, run_domain
from .adapter import CLICK_RULE, BusinessAdapter, digest, write_json


class BusinessProposer(Proposer):
    """Scripted prompt edit for integration testing, NOT an intelligent optimizer."""

    def call(self, mission, context_dir, label, **kwargs):
        context = Path(context_dir)
        workspace = None
        if label.startswith("select."):
            # k=1 selection is trivial in upstream; keep a deterministic generic fallback.
            selected = sorted((context / "candidates").glob("*.md"))[0].stem
            text = f"<why>Deterministic fixture selection.</why>\n```choice\n{selected}\n```"
        elif label.startswith("experience."):
            text = "NO_ENTRY"
            adopted = json.loads((context / "adoption.json").read_text())["chosen_label"]
            before = json.loads((context / "deliverables/base1/answer.json.txt").read_text())
            after = json.loads((context / f"deliverables/{adopted}/answer.json.txt").read_text())
            if before["policy"] != after["policy"]:
                text = (
                    "<edits>\ncomponent: AGENTS.md\ncandidates: inv1\n"
                    "change: require verification of ambiguous click events\n"
                    "observed: base1 advised draft_only; adopted output advised insufficient\n"
                    "verdict: changed the observed synthetic response\n</edits>\n"
                    "<experience>\ncue: A typed click event has no human intent evidence\n"
                    "lesson: Keep the click ambiguous and request verification.\n"
                    "evidence: AGENTS.md changed; base1 and the adopted deliverable differ "
                    "on draft_only versus insufficient for the same source event.\n"
                    "confidence: limited to this deterministic synthetic contrast\n</experience>"
                )
        else:
            workspace = context / "harness"
            path = workspace / "AGENTS.md"
            current = path.read_text(encoding="utf-8")
            if CLICK_RULE.strip() not in current:
                path.write_text(current + CLICK_RULE, encoding="utf-8")
            text = "<notes>Require verification of ambiguous click events.</notes>"
        reply = Reply(label=label, text=text, ok=True, attempts=1, workspace=workspace)
        self._calls.append(reply)
        return reply


def run(root, dataset):
    root = Path(root).resolve()
    adapter = BusinessAdapter(root, dataset)
    proposer = BusinessProposer(adapter.spec.channels["proposer"])
    outcome = run_domain(
        "correspondence", adapter.tasks("dev"), 1, adapter=adapter, prop=proposer,
        runs_root=adapter.spec.runs_root, library_root=root / "library", modes=("agg",),
    )
    if outcome["failed"]:
        return {**outcome, "holdout_passed": 0, "upstream_evidence": False}
    # Freeze the development-selected prompt BEFORE reading holdout expected labels.
    last = adapter.tasks("dev")[-1]
    namespace = ns(adapter.spec.name, adapter.substrate.name, "agg", 1)
    summary = json.loads((adapter.spec.runs_root / namespace / last / "summary.json").read_text())
    selection = summary["selections"]["agg"]
    candidate = adapter.spec.runs_root / namespace / last / "harnesses" / selection["chosen_label"]
    prompt = (candidate / "AGENTS.md").read_text(encoding="utf-8")
    manifest = {"schema_version": "1.0", "candidate_sha256": digest(prompt),
                "upstream_evidence": str(candidate.relative_to(root)),
                "production_promoted": False, "model_calls": 0, "mail_sends": 0}
    write_json(root / "candidate.json", manifest)
    baseline, heldout = [], []
    for task_id in adapter.tasks("holdout"):
        for harness, rows, label in ((None, baseline, "baseline"), (candidate, heldout, "candidate")):
            run_id = f"holdout/{task_id}/{label}"
            directory = adapter.execute(task_id, harness, run_id)
            graded = judge_one(adapter, task_id, "agg", 1, label, run_id, directory,
                               chosen_is_base=label == "baseline")
            if not graded.graded:
                raise ValueError(f"Holdout judge failed: {graded.error}")
            rows.append({"task_id": task_id, **graded.raw})
    result = {**outcome, **manifest, "upstream_evidence": True,
              "holdout_passed": sum(row["all_pass"] for row in heldout),
              "holdout_count": len(heldout), "baseline_holdout": baseline,
              "candidate_holdout": heldout, "execution_count": adapter.execution_count}
    write_json(root / "business-demo.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(args.output, args.dataset)
    print(json.dumps({key: result[key] for key in ("done", "failed", "holdout_passed", "upstream_evidence")}))
    return int(result["failed"] > 0 or result["holdout_passed"] != result.get("holdout_count"))


if __name__ == "__main__":
    raise SystemExit(main())
