# EverRun Agent

<p align="center">
  <strong>Agents stop. Missions keep running.</strong>
</p>

<p align="center">
  Durable mission state, crash-safe side effects, and verified recovery for long-running AI agents.
</p>

<p align="center">
  <em>When an agent stops, the mission should not disappear with the transcript.</em>
</p>

<p align="center">
  <a href="https://github.com/UcelX/everrun-agent/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/UcelX/everrun-agent/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB">
  <img alt="License Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue">
  <img alt="Status alpha" src="https://img.shields.io/badge/status-alpha-orange">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#how-recovery-works">How it works</a> ·
  <a href="#hermes-agent-integration">Hermes integration</a> ·
  <a href="#security-boundary">Security</a> ·
  <a href="#limitations">Limitations</a>
</p>

EverRun Agent is a local durability layer for autonomous agents. It stores mission progress outside the conversation, records external effects before they run, and calculates the safest recovery action after a crash, restart, or handoff.

## Clone to ready

On a server with Python 3.11 or newer, clone the repository and run one command:

```bash
git clone https://github.com/UcelX/everrun-agent.git
cd everrun-agent
./install.sh
```

The bootstrapper creates an isolated virtual environment, installs EverRun with MCP support,
creates private state storage, detects Hermes when available, installs the profile-local MCP
server and lifecycle policy, then runs an authoritative readiness check. It exits nonzero unless
every selected component is ready.

For unattended servers:

```bash
./install.sh --agent hermes --profile default --non-interactive
```

Core-only installation, without an agent integration:

```bash
./install.sh --agent none --non-interactive
```

The installed CLI path and machine-readable report are printed at the end. Verify again anytime:

```bash
~/.local/share/everrun-agent/venv/bin/everrun doctor \
  --agent hermes --profile default \
  --state-dir ~/.local/share/everrun-agent/state
```

Upgrade idempotently by pulling the repository and rerunning `./install.sh --upgrade`. Safe
uninstall removes the managed runtime and unchanged EverRun integration while preserving mission
state:

```bash
./install.sh --agent hermes --profile default --uninstall --non-interactive
```

It is built for work that cannot safely restart from the beginning: deployments, publishing, batch processing, infrastructure changes, payments, and other multi-step operations with real side effects.

> **EverRun is not another agent.** It is the durable mission layer underneath an agent you already run.

## Why EverRun?

| Without durable state | With EverRun |
|---|---|
| Progress lives in a fragile transcript | Progress lives in an integrity-checked event store |
| A timeout makes the last effect ambiguous | The effect becomes explicitly `uncertain` and requires reconciliation |
| Retry may duplicate a publish, charge, or deploy | Claim-before-fire blocks blind replay |
| A new session starts from notes or memory | A fresh process discovers the mission and its next safe action |
| “Done” is inferred from a counter | Completion requires explicit, fail-closed closure |

## What it is for

- Long-running coding-agent tasks that may cross sessions
- Deployments and infrastructure changes
- Content production with approval gates
- Batch processing and data pipelines
- Payments, notifications, and other external side effects
- Agent handoff between profiles or processes

## What it is not

- A hosted orchestration platform
- A replacement for your agent, queue, database, or provider
- A guarantee that an unknown external system executed exactly once
- An operating-system sandbox
- A cloud synchronization service

## The problem

An agent can lose its context while the world keeps changing. A process may die after an API call succeeds but before the result reaches the transcript. Retrying blindly can publish twice, charge twice, or repeat an infrastructure change.

EverRun separates three things that normal agent transcripts mix together:

- what the agent intended to do;
- what the durable event log proves happened;
- what still needs an authoritative check.

After an interruption, EverRun returns one recovery mode and one next safe action. An unresolved effect becomes `reconcile`, never an assumed success or an automatic retry.

## Core guarantees

| Guarantee | Enforcement |
|---|---|
| Append-only mission history | Hash-chained SQLite events, immutable triggers, and a persisted chain-head anchor |
| Atomic state changes | Mission creation, claims, completions, reconciliation, and checkpoints each use one transaction |
| Crash-safe side effects | Claim-before-fire action ledger with explicit uncertain state |
| No blind replay | An interrupted action blocks retry until reality is checked |
| Verified completion | Agent-reported progress requires separate operator approval |
| Safe handoff | A mission cannot transfer while an external effect is unresolved |
| Tamper detection | Recovery contracts, checkpoints, and capsules carry integrity digests |
| Secret-safe evidence | Credential-shaped values are redacted before evidence or share-only export |
| Fail-closed tooling | Unknown tools, unauthenticated mutation, invalid state, and corrupt chains are rejected |

## How recovery works

```text
agent starts mission
        |
        v
record progress and checkpoints
        |
        v
claim external effect before firing it
        |
        +---- process survives ----> complete action
        |
        +---- process dies --------> action remains uncertain
                                          |
                                          v
                                 fresh agent inspects reality
                                          |
                                          v
                                 reconcile occurred / not occurred
                                          |
                                          v
                                 operator review and explicit close
```

Recovery precedence is conservative:

```text
corrupt chain       -> abort
uncertain effect    -> reconcile
unconfirmed work    -> request_review
goal reached        -> close_mission
otherwise           -> continue_work
```

## Installation

EverRun requires Python 3.11 or newer. It is a local library: mission data stays on the machine where the agent runs.

### From a checkout

```bash
git clone https://github.com/UcelX/everrun-agent.git
cd everrun-agent
python3 -m venv .venv
. .venv/bin/activate
python -m pip install '.[mcp]'
```

### For development

```bash
python -m pip install '.[dev]'
pytest -q
```

The `mcp` extra is required only for the native MCP server and Hermes integration. The core library has no runtime dependency.

### Editable development install

```bash
python -m pip install -e '.[mcp]'
```

### Development environment

```bash
python -m pip install -e '.[dev]'
pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
mypy src/everrun_agent
python -m build
```

## Quick start

Create a mission and record progress:

```bash
everrun init release-1 "Ship the release" --total 3
everrun record-decision release-1 restart-policy "Do not restart production during traffic"
everrun complete-work release-1 build
everrun checkpoint release-1 --reason milestone
everrun status release-1 --json
everrun resume release-1 --json
```

`resume` exits with code `0` only when the returned state is safe. Unsafe, corrupt, review-required, or reconciliation states use a nonzero exit code, so shell automation can fail closed:

```bash
everrun resume release-1 && ./continue-agent.sh
```

A mission reaches `verified_complete` only through explicit closure:

```bash
everrun close release-1
```

Closure is rejected if progress is incomplete, the chain is invalid, agent-reported work is unconfirmed, a success contract is unmet, or any side effect remains unresolved.

## External effects

Use the action ledger for anything that changes another system.

```python
from everrun_agent import ActionLedger, EverRunStore, Mission
from everrun_agent.gate import protected_call

with EverRunStore("mission.db") as store:
    store.create_mission(Mission("deploy-1", "Deploy the service", 1))
    ledger = ActionLedger(store, "deploy-1")

    result = protected_call(
        ledger,
        "deploy.production",
        {"commit": "abc123"},
        run_deploy,
    )
```

If the process dies after `run_deploy()` changes production but before completion is recorded, a fresh process receives `reconcile`. It must inspect production and settle the action before continuing.

## Hermes Agent integration

Install and verify the native MCP integration with one command:

```bash
everrun integrate hermes --profile default
```

For another Hermes profile:

```bash
everrun integrate hermes --profile creator
```

The installer first verifies the MCP dependency, then creates profile-local state, pins the authenticated stdio identity, registers the exact 13-tool contract, installs the `everrun-lifecycle` policy skill, and rolls back its newly-created MCP/skill assets if verification fails. The skill makes normal multi-step prompts discover/start/checkpoint automatically; users do not need to dictate EverRun tool names. Install with `everrun-agent[mcp]` (or source extra `.[mcp]`) before running integration.

Useful integration commands:

```bash
# Preview without changing Hermes
everrun integrate hermes --profile creator --dry-run

# Remove the EverRun MCP entry and unchanged EverRun-owned lifecycle skill
everrun integrate hermes --profile creator --uninstall
```

At the start of a fresh session, the agent can discover work without knowing a mission ID:

```bash
everrun list-missions --status blocked --json
everrun inspect <mission-id> --json
```

## Operator approval

Agent progress is not self-certifying. The operator creates a digest-bound approval request through a separate trusted surface:

```bash
everrun approval-request release-1 --ttl 300
```

The response includes a single-use ticket, current recovery digest, expiry, progress, and pending risk count. Approval succeeds only if the mission state still matches that digest:

```bash
everrun approve release-1 <ticket> <digest> --operator release-manager
```

Tickets are stored only as hashes, expire automatically, and cannot be replayed.

## Mission discovery and inspection

```bash
everrun list-missions --status active --json
everrun list-missions --status blocked --json
everrun list-missions --status review-required --json
everrun list-missions --status completed --json
```

The combined inspection view reports progress, recovery mode, next safe action, chain integrity, checkpoint state, approval coverage, recent events, and a secret-safe action summary:

```bash
everrun inspect release-1 --json
```

## Checkpoints, environment pins, and handoff

Seal a checkpoint:

```bash
everrun checkpoint release-1 --reason pre-deploy
```

Pin facts that must remain stable:

```bash
everrun pin-env release-1 dataset=v3 model=opus
everrun declare-dep release-1 index dataset
everrun check-env release-1 dataset=v3 model=opus --json
```

Transfer a mission to another agent:

```bash
everrun handoff release-1 hermes --context-tokens 8000
```

The handoff includes verified progress, unresolved effects, decisions, the next safe action, and forbidden actions. EverRun refuses the handoff while an effect is uncertain.

## Portable capsules

Export, sign, and verify mission state:

```bash
everrun keygen --out signer.key
everrun export release-1 mission.rly
everrun sign mission.rly --key signer.key --signer workstation
everrun verify-capsule mission.rly --key signer.key --signer workstation
```

Unsigned imports are rejected by default. A redacted export is safe to share but intentionally cannot be imported as trusted state.

## Crash verification

Run the deterministic crash-recovery demo:

```bash
everrun demo --root /tmp/everrun-demo --total 100 --crash-at 40 --json
```

Expected invariants:

```json
{
  "chain_valid": true,
  "completed": 100,
  "duplicates": 0,
  "side_effect_count": 1,
  "unique_outputs": 100
}
```

The test suite also performs real process-death fault injection on POSIX systems and verifies recovery at multiple interruption points. A separate opt-in Hermes harness waits for an authoritative boundary marker before sending literal `SIGKILL` and validating state from a fresh process.

## MCP tools

The native MCP server exposes 13 tools:

```text
everrun_start
everrun_record_work
everrun_checkpoint
everrun_claim_action
everrun_complete_action
everrun_reconcile_action
everrun_list_actions
everrun_list_missions
everrun_inspect
everrun_status
everrun_resume
everrun_briefing
everrun_close
```

Mutating tools deny access by default. Stdio integrations must pin a transport identity. Multiplexed transports must prove client identity with a per-client token. Operator approval authority is not exposed through the worker MCP surface.

## Platform support

CI covers:

- Linux, macOS, and Windows;
- Python 3.11, 3.12, and 3.13;
- package build, unit and integration tests, Ruff, and strict Mypy;
- supported MCP 1.x resolution and explicit MCP 2.x conflict detection.

Literal POSIX `SIGKILL` and POSIX permission-bit tests run only on operating systems that provide those semantics. Windows runs the remaining persistence, recovery, integrity, concurrency, and MCP tests.

## Project status

EverRun Agent is currently alpha software. The local durability core and Hermes integration are implemented and tested. Keep backups of important mission databases and evaluate the library in a controlled environment before relying on it for production changes.

See:

- [`ARCHITECTURE.md`](ARCHITECTURE.md) for invariants and modification rules;
- [`REQUIREMENTS.md`](REQUIREMENTS.md) for requirement-to-test traceability;
- [`SECURITY.md`](SECURITY.md) for the security policy;
- [`CONTRIBUTING.md`](CONTRIBUTING.md) for development workflow.

## Limitations

- SQLite is single-host. The PostgreSQL backend is a contract, not an implementation.
- Attestation uses symmetric HMAC in v0.1. Anyone who can verify with the shared key can also sign.
- The command verifier enforces an allowlist but is not an operating-system sandbox.
- Exactly-once execution across an unknown crash gap is impossible. EverRun blocks and requires reconciliation instead.
- Capsules provide integrity, not encryption.
- The package does not include a hosted control plane, dashboard, RBAC, or cloud synchronization.

## License

EverRun Agent is licensed under the Apache License 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
