"""Connect the business BenchmarkAdapter to the operator-gated Codex transport."""

from .adapter import BusinessAdapter
from .safe_codex import SafeCodexSubstrate


class BusinessCodexAdapter(BusinessAdapter):
    def __init__(self, root, dataset, execution):
        super().__init__(root, dataset)
        if execution.root != self.root / "model":
            raise ValueError("Model execution output must be the adapter's own model subdirectory")
        self.substrate = SafeCodexSubstrate(execution)

    def execute(self, task_id, harness_dir, run_id, *, timeout=None):
        self.cases[task_id]
        install = self.substrate.materialise(harness_dir or self.base_harness(), self.spec, {})
        return self.substrate.execute(
            self.task_files(task_id) / "episode.json", install, [run_id], timeout or 120
        )[0]
