# EverRun Agent dogfood findings

This document records failures, friction, and next development gates discovered by running
EverRun against a real Hermes Agent profile. A green test suite is not enough for public release.

## Run 001: Hermes Creator profile

- Date: 2026-08-31
- Profile: `creator`
- Mission: `creator-dogfood-001`
- Hermes processes: three fresh processes without transcript continuity
- Store: profile-isolated SQLite, mode `0600`
- External-effect marker: one line written exactly once
- Final state: `verified_complete`, `safe=true`, chain trusted through sequence 11

### Proven working

1. Native MCP discovery exposes 11 EverRun tools to Hermes.
2. Mission state survives fresh Hermes processes without transcript continuity.
3. A claimed but unresolved external effect forces `reconcile` and `safe=false`.
4. An authoritative negative probe permits a controlled retry.
5. The retried side effect completes once; the marker remains exactly one line.
6. External-agent progress forces `request_review`; the agent does not self-confirm.
7. Operator confirmation from a separate CLI authority unlocks `close_mission`.
8. Explicit close reaches `verified_complete`; chain verification remains valid.

## Defects found and fixed

### DF-001: advertised MCP server was not MCP-compatible — FIXED

**Observed:** Hermes handshake failed with `method not found` even though unit tests passed.

**Root cause:** `everrun-mcp` implemented a private JSON-RPC shape rather than the MCP
initialize/list-tools/call-tools protocol.

**Fix:** a native MCP 1.x stdio adapter backed by the authenticated `ToolServer`, plus an
`everrun-agent[mcp]` optional dependency and a discovery regression test.

**Proof:** `hermes -p creator mcp test everrun-dogfood` connects and discovers 11 tools.

## Development gaps discovered

### P0 — required before public beta

#### DF-002: no mission discovery tool

A fresh process could resume only because the prompt supplied `creator-dogfood-001`. If the
conversation and operator notes are lost, the agent cannot discover active, blocked, or recently
updated missions through MCP.

**Build:**
- `everrun_list_missions` MCP/CLI operation
- filters: active, blocked, review-required, completed
- stable ordering by most recently updated
- compact fields: mission id, goal, mode, progress, next safe action, updated time

**Acceptance:** a fresh Hermes process receives no mission id, calls list-missions, selects the
only blocked mission, and resumes it correctly.

#### DF-003: no first-class operator approval workflow in Hermes

The safety split worked, but confirmation required leaving Hermes and invoking a raw CLI command.
The agent then emitted conversational text asking the operator to type `confirm`, although that
specific process had already exited and could not consume the reply.

**Build:**
- operator-only approval command/surface that mints and redeems a one-use ticket
- approval request contains mission, exact progress, pending risks, digest, expiry
- never expose approval authority to the worker MCP process
- deterministic post-approval status returned to the operator

**Acceptance:** worker stops at review; operator approves from a separate trusted surface; a new
worker process sees `close_mission`; ticket replay fails.

#### DF-004: fresh-process test is not a real Hermes process-death test

Run 001 used separate clean processes but did not SIGKILL Hermes while an MCP tool call or mission
step was in flight. The library core has a SIGKILL harness, but the Hermes integration does not.

**Build:** integration harness that kills the real Hermes process at boundaries:
- after mission start
- after filesystem work but before record-work
- after action claim but before side effect
- after side effect but before action completion
- during checkpoint creation / MCP disconnect

**Acceptance:** every boundary recovers fail-closed, chain remains valid, completed work is not
repeated, and the external marker occurs once.

#### DF-005: install/configuration is too manual and easy to misconfigure

The dogfood needed a long `hermes mcp add` command with absolute Python path and three environment
variables. A user can accidentally run read-only, pin the wrong client identity, use a non-profile
DB path, or install MCP 2.x against the v1 adapter.

**Build:**
- `everrun integrate hermes --profile <name>` installer
- detect Hermes and profile paths
- install the compatible MCP extra
- create a profile-local `0600` state directory
- configure transport-pinned identity
- run handshake/tool discovery
- reversible uninstall and dry-run modes

**Acceptance:** clean Hermes profile goes from no EverRun to an 11-tool verified connection with
one command; rerun is idempotent; uninstall removes only EverRun-owned configuration.

#### DF-006: no automated end-to-end dogfood regression

The successful three-process scenario is documented but not executable in CI. Future MCP,
recovery, or Hermes changes could silently break it again.

**Build:** `tests/integration/test_hermes_dogfood.py` or a standalone deterministic harness using
an actual installed Hermes CLI when available, with a protocol-level fallback in normal CI.

**Acceptance:** machine-readable report asserts transitions
`reconcile -> request_review -> continue/close_mission -> verified_complete`, marker count 1,
and valid chain.

### P1 — required before wider stable release

#### DF-007: incomplete operator observability

The MCP status response omits event count, last update, checkpoint age, latest confirmation
coverage, and a safe summarized action ledger. The operator had to use CLI `verify` separately.

**Build:** one `inspect` view combining status, chain verification, active checkpoint, unresolved
actions, confirmation boundary, and last events without secret payloads.

#### DF-008: no lifecycle policy telling agents when EverRun is mandatory

EverRun tools were available, but the dogfood prompt explicitly ordered every call. A normal agent
may ignore EverRun, record work too late, or fire an effect without claiming it.

**Build:** integration instructions/skill and optional policy hook:
- start durable missions automatically for qualifying multi-step work
- claim before irreversible external effects
- checkpoint at milestones
- inspect/resume at session start
- never self-confirm

**Acceptance:** an unprompted Hermes mission uses EverRun in the correct order under a published
policy, while trivial one-step questions do not create noise.

#### DF-009: MCP error UX needs structured recovery hints

The adapter currently raises a generic `ValueError` string on domain failures. Agents need stable
codes and machine-readable remediation (`uncertain_action`, `review_required`, `invalid_state`,
`next_safe_action`) rather than parsing prose.

**Build:** MCP tool errors with stable codes and structured data; preserve secret-safe messages.

#### DF-010: compatibility matrix is unproven

Dogfood covers one Hermes version, Linux ARM64, Python 3.11, and MCP 1.26. It does not yet prove
Python 3.12/3.13, x86_64, Windows, macOS, Claude Code, Codex, or MCP 2.x.

**Build:** CI matrix plus explicit MCP-version strategy. Either support MCP 2.x or fail installation
with a clear compatibility message; never silently install an incompatible major version.

### P2 — later product improvements

- Local mission dashboard and approval inbox
- Ed25519 asymmetric attestations
- Encrypted capsule sync
- PostgreSQL backend and multi-host coordination
- Log compaction/archival
- Team RBAC and multi-tenant control plane

## Implementation traceability (Run 002 engineering)

| Item | Status | Proof |
|---|---|---|
| DF-002 mission discovery | IMPLEMENTED | `test_fresh_agent_discovers_blocked_mission_without_id`, `test_mcp_list_missions_is_read_only_and_needs_no_mission_id` |
| DF-003 operator approval | IMPLEMENTED | `test_operator_approval_request_is_digest_bound_and_replay_safe`, `test_approval_rejects_state_changed_after_request` |
| DF-004 real Hermes SIGKILL | VERIFIED LIVE | Creator mission `literal-sigkill-005`: literal process exit `-9`; fresh process discovered it without an id, reconciled the one existing marker without replay, chain valid, approval replay refused, final `verified_complete` |
| DF-005 Hermes integrator | IMPLEMENTED | `test_hermes_dry_run_is_profile_local_and_non_mutating`; `everrun integrate hermes` |
| DF-006 automated dogfood | IMPLEMENTED | `test_protocol_fallback_dogfood_transitions_once_and_valid_chain`; `scripts/dogfood_harness.py` |
| DF-007 inspect | IMPLEMENTED | `test_inspect_combines_integrity_checkpoint_review_and_actions` |
| DF-008 lifecycle policy | IMPLEMENTED | `integrations/hermes/SKILL.md` |
| DF-009 structured errors | IMPLEMENTED | `test_mcp_error_preserves_structured_recovery_data` |
| DF-010 compatibility | IMPLEMENTED | `test_mcp_dependency_is_pinned_to_supported_major`; `.github/workflows/ci.yml` |

## Public-release decision

**Current verdict: ALL P0 ENGINEERING AND LIVE ACCEPTANCE GATES PASSED; KEEP PRIVATE FOR FINAL SOAK.**

The durable kernel, native MCP path, discovery, operator approval, profile-safe integration, automated fallback harness, and literal Hermes SIGKILL recovery have all passed. The repository remains private for a final soak period and cross-platform CI before any public-release decision.

## Run 002 result

1. One-command Creator integration exposed 13 tools and was profile-local (`0700`).
2. Fresh recovery discovered the blocked mission without a supplied id.
3. The parent Hermes process was killed with literal `SIGKILL`; observed exit code was `-9`.
4. The already-fired effect remained exactly one line and was reconciled, never replayed.
5. Digest-bound separate operator approval succeeded; replaying its ticket was refused.
6. Final mode was `verified_complete`, `safe=true`, with a valid event chain.
7. The deterministic protocol fallback is executable in CI through `scripts/dogfood_harness.py`.

Live integration also found and fixed four defects: private JSON-RPC instead of MCP, false-positive handshake verification, command/args serialization, and repeated `--env` serialization dropping the mutation allowlist.
