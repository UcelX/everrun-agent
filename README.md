# RelayCore

> **Agents are temporary. Missions survive.**

RelayCore is a small, local-first foundation for durable AI-agent missions. It records mission facts in a hash-chained event log, projects semantic state deterministically, blocks blind retries of uncertain side effects, verifies reality, and exports portable integrity-checked capsules.

This is **v0.1 foundational core**, not a hosted SaaS or complete agent framework.

## Why

Long-running agents crash, lose context, switch models, and repeat irreversible actions. RelayCore separates temporary conversation context from durable mission state and provides one safe next action after recovery.

## Implemented

- ✅ SQLite append-only event stream with SHA-256 hash chain
- ✅ Deterministic semantic projection: goal, progress, failures, decisions, findings
- ✅ Sealed semantic checkpoints
- ✅ Idempotent action ledger: claim → complete / reconcile
- ✅ Fail-closed recovery for corrupt chains and uncertain actions
- ✅ File, command, and HTTP reality verifiers
- ✅ Portable `.rly` capsule with integrity digest and mode `0600`
- ✅ CLI and real crash-recovery demonstration
- ✅ Tests for tampering, restart, duplicate prevention, recovery, verifier, capsule, CLI, demo

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e .

relay --db .relaycore/relay.db init mission-1 "Process documents" --total 2
relay --db .relaycore/relay.db complete-work mission-1 document-a
relay --db .relaycore/relay.db status mission-1
relay --db .relaycore/relay.db verify mission-1
relay --db .relaycore/relay.db export mission-1 mission.rly
```

## Run the proof

```bash
relay demo --workdir /tmp/relay-demo --total 100 --crash-at 40
```

The demo records 40 items, performs one external side effect, simulates a crash before recording completion, refuses blind continuation, reconciles the effect from reality, and completes all 100 items without duplicates.

Expected shape:

```json
{"chain_valid": true, "completed": 100, "duplicates": 0, "side_effect_count": 1, "unique_outputs": 100}
```

## Safety model

1. Event history is trusted only through the last valid hash.
2. A started but uncompleted external action is **uncertain**, never assumed failed or successful.
3. Recovery returns one `next_safe_action`; uncertain effects are reconciled before work continues.
4. Capsules contain mission state and evidence metadata, never credentials.
5. Unknown/corrupt state fails closed.

## Architecture

```text
CLI / future MCP adapters
          │
    Recovery Kernel
      ├── Semantic Projector
      ├── Checkpoints
      ├── Action Ledger
      └── Reality Verifiers
          │
  Hash-chained SQLite Event Store
          │
    Portable .rly Capsules
```

## Honest limitations

- Single-host SQLite; no distributed consensus.
- No MCP server, hosted control plane, encryption, RBAC, or agent handoff yet.
- Command verifier executes only explicit argv and is not a sandbox.
- Exactly-once external effects are impossible in the crash gap; RelayCore provides mandatory reconciliation instead.
- Capsule integrity is a digest, not yet a public-key signature.

## Roadmap

- v0.2: MCP server, execution permits, structured reconcilers
- v0.3: Hermes / Claude Code / Codex lifecycle adapters
- v0.4: signed capsules and cross-agent handoff compiler
- v0.5: PostgreSQL, encrypted sync, mission dashboard

## Origin and license

RelayCore is an independent implementation inspired by durable execution and semantic recovery concepts demonstrated by [Cyrax321/CONTINUUM](https://github.com/Cyrax321/CONTINUUM). No CONTINUUM source files are copied into this repository.

Licensed under Apache License 2.0.
