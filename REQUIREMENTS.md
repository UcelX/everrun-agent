# RelayCore v0.1 Traceability

| Requirement | Acceptance evidence | Status |
|---|---|---|
| Hash-chained append-only events detect tampering | `test_event_chain_detects_tampering` | VERIFIED |
| Mission state projects deterministically from events | `test_projection_rebuilds_semantic_state` | VERIFIED |
| SQLite persistence survives process restart | `test_sqlite_roundtrip_and_sequence` | VERIFIED |
| Checkpoints seal projected state | `test_checkpoint_detects_modified_payload` | VERIFIED |
| Duplicate actions never fire twice | `test_completed_action_is_idempotent` | VERIFIED |
| Interrupted effects become uncertain | `test_started_action_blocks_blind_retry` | VERIFIED |
| Recovery emits exactly one safe next action | `test_recovery_requires_reconciliation_first` | VERIFIED |
| File/HTTP/command evidence can be verified | verifier tests | VERIFIED |
| Capsules export/import without credentials | capsule tests | VERIFIED |
| Crash demo completes with zero duplicate work | `test_crash_demo_end_to_end` | VERIFIED |
