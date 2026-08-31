# EverRun Agent architecture

## One invariant

Every fact carries its origin, and trust is earned from reality rather than asserted by an agent.

## Layers

```text
CLI  ·  MCP / JSON-RPC tools  ·  Adapters and lifecycle hooks
                    |
              Recovery kernel
   projection · checkpoints · contracts · handoff
                    |
   Action ledger  ·  Reconcilers  ·  Admission gate  ·  Budgets
                    |
   Evidence and verifiers (file · command · HTTP)
                    |
   Hash-chained SQLite event store (+ anchored chain head)
                    |
   Portable, integrity-checked, signable capsules
```

## Module map

| Module | Role |
|---|---|
| `models.py` | Frozen dataclasses, event types, origins, recovery modes, sealed contract |
| `crypto.py` | Canonical serialization and event digests |
| `store.py` | Transactions, append-only enforcement, chain verification, checkpoints, restore |
| `projection.py` | Pure fold from events to semantic state |
| `checkpoint.py` | Sealed, immutable checkpoint creation |
| `ledger.py` | Claim, complete, reconcile, uncertainty, budget enforcement |
| `gate.py` | Claim-before-fire admission control |
| `reconcilers.py` | Probe registry that settles uncertainty from reality |
| `budgets.py` | Per-kind retry caps |
| `evidence.py` | Durable evidence events with secret redaction |
| `contracts.py` | Success contracts evaluated from evidence |
| `environment.py` | Snapshot diffing and staleness propagation |
| `verifier.py` | Policy-guarded file, command, and HTTP verification |
| `recovery.py` | Signal ordering into one sealed contract |
| `handoff.py` | Briefing compiler and cross-agent authority transfer |
| `adapters.py` | Generic in-process facade and hook installers |
| `service.py` | Deny-by-default tool surface plus JSON-RPC and stdio |
| `mcp_server.py` | `everrun-mcp` entrypoint |
| `capsule.py` | Portable export and transactional import |
| `attestation.py` | Capsule signing and signer verification |
| `storage.py` | Backend protocol for future databases |
| `cli.py` | Operator surface with exit codes as a safety contract |
| `demo.py` | Crash-recovery proof |

## Recovery ordering

```text
corrupt chain        -> abort
uncertain effect     -> reconcile
unconfirmed external -> request_review
goal reached         -> verified_complete
otherwise            -> continue
```

The most cautious applicable signal wins, so evaluation order can never produce an unsafe verdict.

## Threat model

| Threat | Control |
|---|---|
| Agent fabricates progress | Origin tagging plus mandatory human confirmation |
| Silent history rewrite | Chain digests, append-only triggers, anchored head |
| Duplicate irreversible effect | Idempotent ledger, admission gate, mandatory reconciliation |
| Assumed success after crash | Uncertainty is a first-class state; no assume-occurred strategy |
| Credential leakage | Redaction in evidence, capsules carry no secrets, `0600` files |
| SSRF via verifier | Scheme allowlist, private and metadata refusal, redirect revalidation |
| Arbitrary command execution | Executable allowlist, clean environment, timeout, bounded output |
|| Unauthorized tool mutation | Deny-by-default mutation, transport-pinned or per-client-token identity, and one-use out-of-band confirmation tickets |
| Forged portable state | Capsule digest plus signer attestation, transactional import |

## Modification rules

1. Never widen a safety default without a failing test that proves the need.
2. Every new event type must be projected and covered by chain verification.
3. Any new external effect must route through the ledger and the gate.
4. Never add an assume-success reconciliation path.
5. Never trust request-supplied client identity without transport pinning or per-client authentication.
6. Keep the core dependency-free; optional features go behind extras.
