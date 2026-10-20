"""Restricted Codex seam; execution requires a separate, explicit operator gate."""

import re
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from ..core import runmark, tree
from ..substrate.base import Install
from ..substrate.codex import CODEX_SURFACE, CodexSubstrate


class SafeCodexSubstrate(CodexSubstrate):
    """Use the real Codex surface without inheriting benchmark execution privileges."""

    name = "business-offline"

    def __init__(self, execution=None):
        super().__init__()
        self.execution = execution
        if execution is not None:
            self.name = "business-codex"

    def surface(self):
        return replace(CODEX_SURFACE, hooks_file=None, stubs=())

    def materialise(self, tree_dir: Path, spec, ctx: Mapping[str, str]) -> Install:
        if spec.install_mode != "codex_root" or ctx:
            raise ValueError("Business install requires codex_root and no extra configuration")
        root = Path(tree_dir).resolve()
        files = list(root.rglob("*"))
        if any(p.is_symlink() for p in files):
            raise ValueError("Business harness cannot contain symlinks")
        if {p.relative_to(root).as_posix() for p in files if p.is_file()} != {"AGENTS.md"}:
            raise ValueError("Only AGENTS.md is editable; scripts, hooks and config are forbidden")
        contents = tree.read_tree(self.surface(), root)
        tree.validate(self.surface(), contents)
        return Install(root, runmark.fingerprint(root), {"mode": "offline"})

    def exec_argv(self, prompt, workspace, model, *, reasoning_effort="high"):
        # Only run inside an isolated container with an empty HOME/CODEX_HOME.
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,100}", model):
            raise ValueError("Invalid model identifier")
        if reasoning_effort not in ("low", "medium", "high"):
            raise ValueError("Unsupported reasoning effort")
        return [
            "codex", "--ask-for-approval", "never", "exec",
            "--sandbox", "read-only", "--json", "--skip-git-repo-check",
            "--model", model, "-c", f'model_reasoning_effort="{reasoning_effort}"',
            "-C", str(workspace), "--", prompt,
        ]

    def exec_env(self, base_env, *, codex_home):
        return {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
                "HOME": "/tmp/home", "CODEX_HOME": str(codex_home)}

    def container_plan(self, image: str, source: Path, prompt: str, model: str) -> list[str]:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9./_-]*@sha256:[a-f0-9]{64}", image):
            raise ValueError("Codex image must be pinned by digest")
        source = Path(source).resolve(strict=True)
        if "," in str(source) or "\n" in str(source) or "\r" in str(source):
            raise ValueError("Input path contains Docker mount delimiters")
        # Never mount a checkout, home, credential tree or arbitrary product directory.
        if {p.name for p in source.iterdir()} != {"AGENTS.md", "episode.json"}:
            raise ValueError("Input must contain only AGENTS.md and episode.json")
        if any(p.is_symlink() or not p.is_file() for p in source.iterdir()):
            raise ValueError("Input must contain regular files only")
        return [
            "docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
            "--dns", "127.0.0.1",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "65532:65532", "--pids-limit", "64", "--memory", "512m",
            "--cpus", "1", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m,mode=1777",
            "--mount", f"type=bind,source={source},target=/input,readonly",
            "-e", "HOME=/tmp/home", "-e", "CODEX_HOME=/tmp/codex",
            "--workdir", "/input", "--entrypoint", "codex", image,
            *self.exec_argv(prompt, Path("/input"), model)[1:],
        ]

    def execute(self, task_ref, install, run_ids, timeout):
        if self.execution is None:
            raise RuntimeError("Live business Codex execution disabled: configure an explicit operator gate")
        return self.execution.execute(self, task_ref, install, run_ids, timeout)

    def preflight(self, **kwargs):
        # Do not inherit upstream's network/credential preflight.
        if self.execution is None:
            raise RuntimeError("Offline profile only; no live Codex or provider has been accepted")
        return self.execution.preflight()
