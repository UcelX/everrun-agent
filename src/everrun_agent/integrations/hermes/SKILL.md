---
name: everrun-lifecycle
description: Automatically preserve and resume multi-step missions across crashes and fresh sessions using the EverRun MCP lifecycle.
version: 0.1.0
---
# EverRun lifecycle policy

Use EverRun for multi-step work, work expected to cross sessions, or any operation with an irreversible external effect. Do not create missions for trivial one-step questions.

Hermes exposes this server using native MCP-prefixed tool names. Use `mcp_everrun_everrun_*`; do not wait for the user to name EverRun or its tools.

1. At session start call `mcp_everrun_everrun_list_missions`; inspect and resume relevant active/blocked work.
2. Start a durable mission with `mcp_everrun_everrun_start` before qualifying work.
3. Before every irreversible effect call `mcp_everrun_everrun_claim_action`; never fire first.
4. Record verified work promptly and checkpoint at semantic milestones.
5. On uncertainty stop and reconcile using an authoritative probe; never retry blindly.
6. Never self-confirm. Stop at `request_review`; an operator approves through the trusted CLI.
7. Explicitly close only when EverRun reports `close_mission`.

The worker MCP surface intentionally cannot mint or redeem operator approval requests.
