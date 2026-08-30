# EverRun Agent

> **Agents stop. Missions keep running.**

EverRun Agent is a local-first durability layer for long-running AI agents. It keeps mission state in a hash-chained append-only log, refuses to repeat uncertain side effects, verifies claims against reality, and can hand a mission to a different agent without losing verified progress.

Version 0.1 is a complete local core. It is not a hosted service.

## Why

Long agent runs crash, lose context, switch models, and repeat irreversible actions. EverRun separates temporary conversation context from durable mission state, then answers one question after every interruption:

> Given what is actually true right now, what is the single safest next action?

## Implemented and verified

| Capability | What it guarantees |
|---|---|
| Append-only event chain | SHA-256 chain plus persisted head anchor; updates and deletes are refused by database triggers, and a truncated tail is detected |
| Deterministic projection | The same event prefix always yields the same semantic state |
| Immutable checkpoints | Sealed state digests, restore replays only post-checkpoint events |
| Atomic writes | Mission creation, action claim, completion, reconciliation, and checkpointing are single transactions |
| Idempotent action ledger | A completed effect never fires twice; an interrupted effect becomes uncertain, never assumed |
| Structured reconcilers | Uncertain effects are settled by registered probes that inspect reality, never by assumption |
| Admission gate | `protected_call` refuses to run a side effect that has no live claim |
| Retry budgets | Per-kind attempt caps are enforced at claim time |
| Provenance | Every event records its origin and is signed into the chain |
| Anti self-certification | Agent-reported progress cannot complete a mission without human confirmation |
| Sealed recovery contract | Mode, safety, reasons, timestamp, and digest; tampering is detectable |
| Success contracts | Completion is evaluated from recorded evidence, not from agent claims |
| Durable evidence | File, command, and HTTP evidence stored as events with secret redaction |
| Hardened verifiers | HTTP refuses private, loopback, link-local, and metadata targets and revalidates redirects; commands run from an allowlist with bounded output |
| Portable capsules | Integrity-checked `.rly` export/import, atomic and rollback-safe, mode `0600` |
| Signed attestation | Capsules carry signer identity and signature; unknown signer or altered body is rejected |
| Cross-agent handoff | Refused while an effect is uncertain; capsule is sealed and authority transfer is recorded |
| Context-aware briefing | Critical sections are never dropped under a token budget |
| Tool surface | 11 tools split read-only versus mutating, deny-by-default, separate confirmation authority, JSON-RPC and stdio |
| Lifecycle hooks | Idempotent, reversible installers for Hermes, Claude Code, and Codex |
| Storage contract | Explicit backend protocol so other databases can be added without touching the kernel |
| Crash proof | Real `SIGKILL` fault injection at multiple boundaries: zero duplicate work, one side effect, valid chain |

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Run every gate:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src/everrun_agent
```

## Quick start

```bash
everrun init release-1 "Ship the release" --total 3
everrun record-decision release-1 d1 "no production restart during traffic"
everrun complete-work release-1 build
everrun checkpoint release-1 --reason milestone
everrun status release-1
everrun resume release-1
everrun briefing release-1 --context-tokens 4000
```

Exit codes are a safety contract: only a verified-safe mission exits `0`, so this cannot launch onto unsafe state:

```bash
everrun resume release-1 && ./start-agent.sh
```

## Run the crash proof

```bash
everrun demo --workdir /tmp/everrun-demo --total 100 --crash-at 40
```

```json
{"chain_valid": true, "completed": 100, "duplicates": 0, "side_effect_count": 1, "unique_outputs": 100}
```

The fault-injection suite goes further: it kills a real worker process with `SIGKILL` at several boundaries, then requires a fresh process to refuse a blind resume, reconcile the effect from reality, and finish with no duplicates.

## Side effects: claim before you fire

```python
from everrun_agent import ActionLedger, EverRunStore, Mission
from everrun_agent.gate import protected_call

with EverRunStore("mission.db") as store:
    store.create_mission(Mission("deploy-1", "Deploy the service", 1))
    ledger = ActionLedger(store, "deploy-1")
    protected_call(ledger, "deploy.production", {"commit": "abc123"}, run_deploy)
```

If the process dies between the claim and the record, the next run reports `reconcile` and refuses to deploy again until a probe checks the real system.

## Hand a mission to another agent

```bash
everrun handoff release-1 hermes --context-tokens 8000
```

The receiving agent gets goal, verified progress, uncertain effects, the next safe action, and what it must not do. It does not get the transcript. Handoff is refused while any effect is unresolved.

## Agent integration

```bash
everrun hooks install claude-code
EVERRUN_MUTATING_CLIENTS=claude-code EVERRUN_CONFIRM_TOKEN=operator-secret everrun-mcp
```

Mutating tools deny unknown clients, and a client that reports progress cannot also confirm it.

## Capsule attestation

```bash
everrun keygen --out signer.key
everrun export release-1 mission.rly
everrun sign mission.rly --key signer.key --signer workstation
everrun verify-capsule mission.rly --key signer.key --signer workstation
```

## Safety model

1. History is trusted only through the last valid hash, and the chain head is anchored.
2. A started but unrecorded external effect is uncertain and blocks resume.
3. Uncertainty is settled by evidence, never by assumption.
4. Agent-reported state is not self-certifying.
5. Recovery names exactly one next safe action.
6. Capsules carry state and evidence metadata, never credentials.
7. Unknown, corrupt, or unverifiable state fails closed.

## Honest limitations

- Single-host SQLite. PostgreSQL is a contract, not yet an implementation.
- v0.1 attestation is HMAC-based; asymmetric Ed25519 signing is planned for v0.2.
- The command verifier enforces policy but is not an OS sandbox.
- The gate protects structured tool calls; it cannot see inside arbitrary shell strings.
- Exactly-once external effects are impossible across a crash gap. EverRun provides mandatory reconciliation instead.
- No dashboard, cloud sync, RBAC, or multi-tenant control plane yet.
- Capsules are integrity-protected, not encrypted at rest.

## Roadmap

- v0.2: local mission dashboard with operator approvals, Ed25519 attestation, log compaction
- v0.3: PostgreSQL backend, mission families and parallel branches
- v0.4: encrypted capsule sync across devices
- v0.5: outcome verification service and team workflows

## Origin and license

EverRun Agent is an independent implementation. Its problem framing was informed by durable execution and semantic recovery work demonstrated in [Cyrax321/CONTINUUM](https://github.com/Cyrax321/CONTINUUM) (Apache-2.0). No upstream source files are included in this repository.

Licensed under the Apache License 2.0.
