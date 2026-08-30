# RelayCore v0.1 Traceability

| Requirement | Acceptance evidence | Status |
|---|---|---|
| Hash-chained append-only events detect tampering | `test_event_chain_detects_tampering` | RED |
| Mission state projects deterministically from events | `test_projection_rebuilds_semantic_state` | RED |
| SQLite persistence survives process restart | `test_sqlite_roundtrip_and_sequence` | RED |
| Checkpoints seal projected state | `test_checkpoint_detects_modified_payload` | RED |
| Duplicate actions never fire twice | `test_completed_action_is_idempotent` | RED |
| Interrupted effects become uncertain | `test_started_action_blocks_blind_retry` | RED |
| Recovery emits exactly one safe next action | `test_recovery_requires_reconciliation_first` | RED |
| File/HTTP/command evidence can be verified | verifier tests | RED |
| Capsules export/import without credentials | capsule tests | RED |
| Crash demo completes with zero duplicate work | `test_crash_demo_end_to_end` | RED |
