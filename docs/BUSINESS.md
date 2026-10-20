# Portable business replay and gated Codex connector (release 0.1.0)

This fork preserves Google Harness² and Apache-2.0. The addition is a small adapter,
not a CRM, sender, replacement coding agent or trained model. It works with external
products through data-only JSON and opaque instance/product/contact/thread IDs.
No OSMEE implementation, customer data, tokens or local configuration is included.

## What is actually integrated

`BusinessAdapter` implements the real upstream `BenchmarkAdapter` protocol and supplies
`BenchSpec(install_mode="codex_root")` plus a restricted `CodexSubstrate` implementation.
`python -m harness2.business.demo` invokes upstream `core.schedule.run_domain`, proposal
validation, executions, composition, selection, the persistent library and evidence trees.
The deterministic `BusinessProposer` and typed-event responder are test doubles: they prove
the seam and orchestration, not model intelligence, natural-language analysis or production
conversion performance. They never execute proposed Python, tools or hooks.

The five dev episodes cover mail, reply, refusal, quote request and an ambiguous click.
A scripted prompt candidate treats clicks as insufficient evidence. Three holdout cases
cover a new click, an instruction-injection text with unknown permission, and suppression.
Expected labels stay outside source/context; holdout episodes never enter the improvement
library. The candidate is frozen before holdout judging. This small, known synthetic set
is an integration regression, not a statistically independent efficacy benchmark.

## Run without dependencies, credentials or network

Linux Python 3.12/3.13 is the upstream-supported runtime. Set the opt-out **before importing
upstream core**, so its configuration loader cannot read a checkout `.env`:

```sh
export HARNESS2_NO_DOTENV=1
python -B -m unittest discover -s tests -p 'test_*.py'
python -B -m harness2.cli.demo --output .run/upstream-demo --k 1
python -B -m harness2.business.demo --dataset examples/business/synthetic.json --output .run/business-demo
```

No `pip install`, Node, auth login, model/provider endpoint or mailbox is required. On
Windows with an older Python, use the pinned official Python image in `UPSTREAM.json`.
The following PowerShell example mounts source read-only and only this fork's ignored
output directory writable. It does not mount Docker's socket, a home or any credentials.

```powershell
New-Item -ItemType Directory -Force .run\tmp | Out-Null
$businessImage = (Get-Content UPSTREAM.json | ConvertFrom-Json).offline_python_image
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges `
  --user 65532:65532 --pids-limit 128 --memory 512m --cpus 2 `
  --mount "type=bind,source=$((Get-Location).Path),target=/src,readonly" `
  --mount "type=bind,source=$((Get-Location).Path)\.run,target=/out" `
  --workdir /src -e HARNESS2_NO_DOTENV=1 -e PYTHONDONTWRITEBYTECODE=1 -e TMPDIR=/out/tmp `
  $businessImage python -B -m harness2.business.demo --dataset examples/business/synthetic.json --output /out/business-demo
```

Pull the exact pinned image separately when needed; execution uses `--network none`.
Only use a component checkout with no private files; do not mount a product checkout.
Use the same container prefix for the test command and original upstream demo.

## JSON v1 boundary and evidence

Inputs conform to [`episode-v1.schema.json`](../schemas/episode-v1.schema.json); outputs
conform to [`result-v1.schema.json`](../schemas/result-v1.schema.json). Both reject unknown
fields. `schema_version` is `"1.0"`; this release requires `synthetic: true`.
`validate_episode(document)` and `validate_result(document, episode)` validate the same
schemas without dependencies; unsupported versions, authority fields, mismatched episode
or event evidence, suppression overrides and permission grants are rejected.

The external product exports only the minimum de-identified facts into a synthetic replay
case. Inbound text is data, never authorization. A consumer must keep its own deterministic
consent, suppression, ownership, finance, rate, duplicate and sending checks. An advisory
`record_opt_out` does not itself update suppression; the product must own the actual event.
There is deliberately no send endpoint, transport, credentials field or CRM mutation API.

Each dataset row has `episode`, `expected: {policy,next_step}` and `split: dev|holdout`.
See [the synthetic fixture](../examples/business/synthetic.json). Product/instance IDs are
opaque routing evidence, not authorization or tenant isolation: never combine customer
datasets/output directories without a separately reviewed isolation contract.

Every output directory retains `inputs.json` (dataset/baseline SHA-256), `baseline/`,
upstream `runs/` and `library/`, executions with input/harness identities, `candidate.json`
and `business-demo.json`. Reusing an output directory with changed inputs fails. Reusing
the same execution ID with another candidate fails. These artifacts remain local and
ignored. They may contain input text; do not publish them. No automatic production promotion
occurs. Choose a newly reviewed candidate explicitly; rollback means selecting the previously
accepted prompt/version in the external product, which this component cannot modify.

## Codex profile, runnable connector and remaining preflight

`SafeCodexSubstrate` reuses the real Codex surface but permits only nonempty `AGENTS.md`.
It rejects scripts, skills, hooks, `.codex` configuration and symlinks. `exec_argv` provides
`--sandbox read-only`, `--ask-for-approval never` and an option terminator before the prompt;
it has neither upstream bypass flag. `exec_env` allowlists an empty container HOME/CODEX_HOME,
not the host environment. `container_plan(image, source, prompt, model)` returns a pinned,
non-root, resource-limited, read-only Docker argv with no network and only two regular input
files: `AGENTS.md` and `episode.json`. The plan itself does not execute anything.

`BusinessCodexAdapter` connects the same real `BenchmarkAdapter` methods to
`SafeCodexSubstrate.execute`, backed by `GatedDockerExecution`. This is runnable container
code, with a dependency-injected subprocess transport for offline tests. It defaults closed:
an immutable operator `ExecutionProfile` must specify `allow_model_run=True`, a nonempty
`budget_approval_ref`, model, digest-pinned image, output directory and network. These values
are outside the candidate surface. The transport never invokes host Codex and never reads
host auth files, `.env`, provider keys or Docker auth. Docker gets a separate empty client
config directory, a small environment allowlist and `--pull never`. The operator must prepare
the pinned Codex image separately; no image build or global CLI update is performed here.

The default network is `none`, for offline fake-CLI/container tests. To reach an actual model,
the operator must supply a pre-existing **internal bridge** with
`com.docker.network.bridge.gateway_mode_ipv4=isolated`, IPv6 disabled and exactly one container
named `business-model-gateway`. The launcher checks these properties through Docker network
inspection, disables DNS, and points Codex's Responses provider only at that gateway's
private IPv4 address on port 8765. An ordinary internal bridge still permits access to host
services on the bridge address; isolated gateway mode removes that address, as documented in
[Docker's gateway modes](https://docs.docker.com/engine/network/port-publishing/#gateway-modes).
No network is created or reconfigured by this component. Run one model attempt at a time on
the isolated network; another attached container causes preflight to reject it.

The separately operated gateway must enforce the approved model, Responses endpoints,
hard budget/rate limits and provider authentication; it must not proxy arbitrary URLs or
tools. Its provider credentials never enter the Codex container. `budget_approval_ref` records
an operator decision; it is **not** a dollar meter. A reviewed gateway with enforced spending
limits is a prerequisite to any real model call. This fork does not provision that service
or weaken authentication on an existing service.

For an operator-approved run, the Python wiring is:

```python
from pathlib import Path
from harness2.business.codex_adapter import BusinessCodexAdapter
from harness2.business.execution import ExecutionProfile, GatedDockerExecution

root = Path(".run/operator-approved-codex").resolve()
profile = ExecutionProfile(
    output_root=root / "model",
    image="<operator-reviewed-codex-image>@sha256:<resolved-digest>",
    model="<approved-model>", allow_model_run=True,
    budget_approval_ref="<approved-budget-reference>",
    network="<reviewed-isolated-network>",
)
adapter = BusinessCodexAdapter(root, Path("examples/business/synthetic.json"),
                               GatedDockerExecution(profile))
# This is the consequential model invocation. Run only after gateway/budget acceptance:
# adapter.execute("synthetic-mail", None, "operator-attempt-1", timeout=120)
```

The placeholders intentionally fail validation. There is no default provider, approved
budget or Codex image. The same adapter can be handed to upstream `run_domain`; keep its
editor/selector deterministic until separately approving any additional model roles.

Every gated execution validates the final Codex JSON stream against the result contract,
persists input/profile/answer identities and returns an upstream-compatible run directory.
A successful run ID is cached; a failed, timed out, malformed or policy-violating attempt is
terminal and never automatically retried because cost may already have occurred. On failure
the launcher attempts to stop only its own unique container name. Unconfirmed cleanup stays
recorded in the local failed attempt; the operator must inspect it before another decision.

Offline tests exercise the real connector with a fake container transport, including gate
rejection, network isolation, successful stream parsing, cached reuse, timeout cleanup and
suppression override rejection. They do not run Codex or a model. The host CLI 0.104.0 was not
updated or launched. A real pinned image/version, CLI flag compatibility, writable scratch
initialization, sandbox support inside the image and gateway/budget controls still need
separate live acceptance. No API/model quality or mail acceptance is claimed. Do not route
business work through upstream benchmark launchers, which retain their original bypass flags.

## Upstream updates and CI

`UPSTREAM.json` records the accepted upstream commit separately from any available candidate.
Run the GitHub **Read-only upstream candidate check** workflow manually, or execute
`python scripts/business/check_upstream.py`. It reads public Google HEAD without a token and
prints candidate/accepted SHAs. It neither fetches code nor edits accepted state, opens a PR,
merges, invokes a model, or writes to the product. There is no scheduled or paid-model job.

To adopt an update, an operator fetches upstream into a review branch, inspects the source
diff (especially config, substrate, prompts and launchers), resolves conflicts, runs the full
offline CI on Python 3.12/3.13 and reviews both demos. Only then update the accepted SHA and
business release together. Failed checks leave the accepted base unchanged. Review the exact
release diff and keep the previous accepted commit for rollback; never auto-merge upstream.
GitHub Actions are pinned to commits (checkout v4.2.2 and setup-python v5.6.0, verified against
their public tag refs); workflow permissions are read-only and checkout credentials are not
persisted. No package dependencies have been added.

Before publishing, inspect tracked/untracked files and the diff, verify `.run`, `.env`,
credentials, localruns and customer-data are excluded, and review every new example as
synthetic. Ignore rules are a backstop, not a substitute for reviewing the publication set.
