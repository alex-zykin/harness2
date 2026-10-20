"""Operator-gated container transport for a real Codex CLI; no credentials discovery."""

import ipaddress
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..core import runmark
from ..substrate.codex import final_message
from .adapter import digest, write_json
from .contract import validate_episode, validate_result


@dataclass(frozen=True)
class ExecutionProfile:
    output_root: Path
    image: str
    model: str
    allow_model_run: bool = False
    budget_approval_ref: str = ""
    network: str = "none"
    gateway_name: str = "business-model-gateway"


class GatedDockerExecution:
    """A single non-retrying model attempt, with a container-only execution boundary.

    Transport injection is for deterministic tests. The default is real subprocess.run.
    A non-none network must be an internal bridge with exactly one operator-managed
    gateway. That gateway owns provider credentials, allowed endpoints/models and budget.
    """

    def __init__(self, profile, transport=subprocess.run):
        self.profile = profile
        self.transport = transport
        self.root = Path(profile.output_root).resolve()

    def _call(self, argv, *, timeout):
        self.root.mkdir(parents=True, exist_ok=True)
        config = self.root / "docker-client-config"
        config.mkdir(exist_ok=True)
        if config.is_symlink() or any(config.iterdir()):
            raise ValueError("Docker client configuration directory must remain empty")
        # Never inherit Docker auth/config, provider keys, HOME or CODEX_HOME.
        env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP")
               if key in os.environ}
        binary = shutil.which("docker") or "docker"
        return self.transport(
            [binary, "--config", str(config), *argv[1:]],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=timeout, check=False, env=env,
        )

    def preflight(self):
        profile = self.profile
        if profile.allow_model_run is not True or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", profile.budget_approval_ref
        ):
            raise RuntimeError("Explicit allow_model_run and a reviewed budget approval reference are required")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9./_-]*@sha256:[a-f0-9]{64}", profile.image):
            raise ValueError("Codex image must be pinned by digest")
        if profile.network == "none":
            return None  # Offline CLI/container tests; a remote model cannot be reached.
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", profile.network):
            raise ValueError("Invalid isolated network name")
        response = self._call(["docker", "network", "inspect", profile.network], timeout=15)
        if response.returncode:
            raise RuntimeError("Cannot inspect the operator-provided isolated Docker network")
        networks = json.loads(response.stdout)
        if not isinstance(networks, list) or len(networks) != 1:
            raise ValueError("Expected exactly one isolated network")
        network = networks[0]
        containers = list((network.get("Containers") or {}).values())
        if network.get("Internal") is not True or network.get("Driver") != "bridge":
            raise ValueError("Model egress requires an internal Docker bridge")
        if network.get("Options", {}).get("com.docker.network.bridge.gateway_mode_ipv4") != "isolated" or network.get("EnableIPv6") is not False:
            raise ValueError("Model egress requires isolated IPv4 gateway mode and disabled IPv6")
        if len(containers) != 1 or containers[0].get("Name") != profile.gateway_name:
            raise ValueError("Internal network must contain only the reviewed model gateway")
        address = ipaddress.IPv4Interface(containers[0]["IPv4Address"]).ip
        if not address.is_private:
            raise ValueError("Gateway must have a private internal address")
        return f"http://{address}:8765/v1"

    def execute(self, substrate, task_ref, install, run_ids, timeout):
        if len(run_ids) != 1 or not all(
            re.fullmatch(r"[a-zA-Z0-9_-][a-zA-Z0-9_.-]*", part)
            for part in run_ids[0].split("/")
        ):
            raise ValueError("Gated execution requires one safe run ID per attempt")
        if type(timeout) is not int or not 1 <= timeout <= 3600:
            raise ValueError("Execution timeout must be 1..3600 seconds")
        # Gates are checked even on cache access; no operator profile comes from a candidate.
        gateway = self.preflight()
        episode = validate_episode(json.loads(Path(task_ref).read_text(encoding="utf-8")))
        source = install.staging_dir
        if runmark.fingerprint(source) != install.fingerprint:
            raise ValueError("Materialised harness changed after validation")
        prompt = (source / "AGENTS.md").read_text(encoding="utf-8")
        identity = {"episode_sha256": digest(episode), "harness_sha256": digest(prompt),
                    "image": self.profile.image, "model": self.profile.model,
                    "network": self.profile.network, "budget_approval_ref": self.profile.budget_approval_ref}
        run = self.root / "executions" / run_ids[0]
        if run.exists():
            record = json.loads((run / "attempt.json").read_text())
            if record.get("identity") != identity:
                raise ValueError("Run ID belongs to different inputs or execution profile")
            if record.get("status") != "complete":
                raise RuntimeError("Previous attempt may have incurred cost; operator review required, never auto-retry")
            answer = json.loads((run / "answer.json").read_text())
            validate_result(answer, episode)
            if record.get("answer_sha256") != digest(answer):
                raise ValueError("Cached model answer changed")
            return [run]
        workspace = run / "input"
        workspace.mkdir(parents=True)
        (workspace / "AGENTS.md").write_text(prompt, encoding="utf-8")
        write_json(workspace / "episode.json", episode)
        mission = "Analyse episode.json. Return only JSON matching: " + json.dumps({
            "schema_version": "1.0", "episode_id": episode["episode_id"],
            "authority": "advisory_only", "policy": "draft_only|suppress|insufficient",
            "next_step": "review_draft|record_opt_out|request_details|verify_signal|request_permission",
            "evidence_event_ids": [episode["event"]["event_id"]],
        })
        argv = substrate.container_plan(self.profile.image, workspace, mission, self.profile.model)
        if gateway:
            argv[argv.index("--network") + 1] = self.profile.network
            index = argv.index("--")
            argv[index:index] = [
                "-c", 'model_provider="business_gateway"',
                "-c", 'model_providers.business_gateway.name="Reviewed business gateway"',
                "-c", f'model_providers.business_gateway.base_url="{gateway}"',
                "-c", 'model_providers.business_gateway.wire_api="responses"',
                "-c", 'model_providers.business_gateway.requires_openai_auth=false',
            ]
        container = "h2-business-" + uuid.uuid4().hex
        argv[2:2] = ["--name", container]
        record = {"schema_version": "1.0", "identity": identity,
                  "container": container, "status": "attempted", "automatic_retry": False}
        write_json(run / "attempt.json", record)
        try:
            result = self._call(argv, timeout=timeout)
            (run / "events.jsonl").write_text(result.stdout, encoding="utf-8")
            if result.returncode:
                raise RuntimeError("Codex container failed; inspect the local attempt, do not auto-retry")
            answer = validate_result(json.loads(final_message(run / "events.jsonl")), episode)
            write_json(run / "answer.json", answer)
            (run / "trajectory.md").write_text(substrate.read_trajectory(
                run / "events.jsonl", obs_trunc=50000, max_chars=200000), encoding="utf-8")
            write_json(run / "attempt.json", {**record, "status": "complete", "answer_sha256": digest(answer)})
        except Exception as failure:
            failed = {**record, "status": "uncertain_or_rejected",
                      "failure_type": type(failure).__name__, "cleanup": "unconfirmed"}
            write_json(run / "attempt.json", failed)
            # A Docker client timeout may leave its container running. Stop only our exact name.
            try:
                stopped = self._call(["docker", "stop", "--timeout", "1", container], timeout=15)
                failed["cleanup"] = "stopped" if stopped.returncode == 0 else "unconfirmed"
            except Exception as cleanup_failure:
                failed["cleanup_failure_type"] = type(cleanup_failure).__name__
            write_json(run / "attempt.json", failed)
            raise
        return [run]
