---
name: everrun-lifecycle
version: 0.1.0
---
# EverRun lifecycle policy

Use EverRun for multi-step work, work expected to cross sessions, or any operation with an irreversible external effect. Do not create missions for trivial one-step questions.

1. At session start call `everrun_list_missions`; inspect and resume relevant active/blocked work.
2. Start a durable mission before qualifying work.
3. Before every irreversible effect call `everrun_claim_action`; never fire first.
4. Record verified work promptly and checkpoint at semantic milestones.
5. On uncertainty stop and reconcile using an authoritative probe; never retry blindly.
6. Never self-confirm. Stop at `request_review`; an operator approves through the trusted CLI.
7. Explicitly close only when EverRun reports `close_mission`.

The worker MCP surface intentionally cannot mint or redeem operator approval requests.
