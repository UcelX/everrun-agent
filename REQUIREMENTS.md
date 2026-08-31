# EverRun Agent v0.1 Traceability

Every row is proven by an executable test in `tests/`. Run all gates with
`pytest -q`, `ruff check src tests`, and `mypy src/everrun_agent`.

| Requirement | Acceptance evidence | Status |
|---|---|---|
| Hash-chained events reject in-place mutation | `test_event_chain_detects_tampering` | VERIFIED |
| Truncated event tail is detected | `test_deleted_chain_tail_is_detected`, `test_tamper_attempts_are_blocked_or_detected` | VERIFIED |
| Missing mission start or sequence gap fails closed | `test_deleted_chain_tail_is_detected` | VERIFIED |
| Deterministic semantic projection | `test_projection_rebuilds_semantic_state` | VERIFIED |
| Persistence survives process restart | `test_sqlite_roundtrip_and_sequence` | VERIFIED |
| Schema version guard refuses newer databases | `test_schema_version_is_migrated_and_rejected_if_newer` | VERIFIED |
| Mission creation is atomic | `test_mission_and_start_event_are_atomic` | VERIFIED |
| Action claim is atomic | `test_action_claim_and_event_are_atomic` | VERIFIED |
| Action completion is atomic | `test_action_completion_and_event_are_atomic` | VERIFIED |
| Checkpoint plus anchor is atomic and immutable | `test_checkpoint_and_anchor_are_atomic_and_immutable` | VERIFIED |
| Checkpoints seal state and detect tampering | `test_checkpoint_detects_modified_payload` | VERIFIED |
| Checkpoint restore replays only the gap | `test_checkpoint_restore_replays_events_after_checkpoint` | VERIFIED |
| Completed effects are idempotent | `test_completed_action_is_idempotent` | VERIFIED |
| Interrupted effects become uncertain | `test_started_action_blocks_blind_retry` | VERIFIED |
| Recovery names exactly one safe next action | `test_recovery_requires_reconciliation_first` | VERIFIED |
| Uncertain effects outrank review escalation | `test_unresolved_action_outranks_external_progress_review` | VERIFIED |
| Recovery contract is sealed and tamper-evident | `test_recovery_contract_is_sealed_and_tamper_evident` | VERIFIED |
| Agent-reported progress cannot self-certify | `test_external_agent_progress_cannot_self_certify_completion` | VERIFIED |
| Human confirmation clears review | `test_external_agent_work_forces_review_and_confirm_clears_it` | VERIFIED |
| Success contract evaluated from evidence | `test_authoritative_evidence_can_satisfy_success_contract` | VERIFIED |
| Evidence is durable and redacted | `test_evidence_redacts_secret_like_detail` | VERIFIED |
| Probes settle uncertainty from reality | `test_probe_reconciler_settles_uncertain_action_from_reality` | VERIFIED |
| No probe means unresolved, not assumed | `test_reconciler_without_probe_stays_unresolved` | VERIFIED |
| Unclaimed side effects are refused | `test_unclaimed_side_effect_is_refused_before_it_fires` | VERIFIED |
| Retry budgets block runaway attempts | `test_retry_budget_blocks_runaway_attempts` | VERIFIED |
| HTTP verifier refuses private and metadata targets | `test_http_verifier_refuses_private_targets_by_default` | VERIFIED |
| Command verifier enforces allowlist and redacts | `test_command_verifier_enforces_allowlist_and_redacts_output` | VERIFIED |
| Environment drift propagates to dependents | `test_environment_drift_propagates_to_dependent_facts` | VERIFIED |
| Concurrent writers keep contiguous sequences | `test_concurrent_stores_allocate_unique_sequences`, `test_environment_variable_workers_do_not_corrupt_sequences` | VERIFIED |
| Capsules exclude credentials and round-trip | `test_capsule_roundtrip_excludes_credentials` | VERIFIED |
| Invalid capsule import rolls back | `test_invalid_capsule_import_rolls_back` | VERIFIED |
| Signed capsule verifies with a known key | `test_signed_capsule_verifies_with_known_key` | VERIFIED |
| Tampered signed capsule is rejected | `test_tampered_signed_capsule_is_rejected` | VERIFIED |
| Unknown signer is not trusted | `test_unknown_signer_is_not_trusted` | VERIFIED |
| Storage backend contract is explicit | `test_storage_backend_contract_is_explicit` | VERIFIED |
| Read-only tools need no mutation grant | `test_read_only_tools_are_allowed_without_mutation_grant` | VERIFIED |
| Mutating tools deny unknown clients | `test_mutating_tools_deny_unknown_clients` | VERIFIED |
| Confirmation requires separate authority | `test_confirm_requires_separate_authority`, `test_ticket_is_single_use_and_hash_only`, `test_ticket_is_scoped_to_its_mission`, `test_agent_cannot_forge_a_ticket` | VERIFIED |
| MCP mutation identity is authenticated, not self-asserted | `test_mcp_server_requires_transport_identity_beyond_allowlist`, `test_mcp_server_honours_transport_pinned_allowlist`, `test_transport_pinned_identity_ignores_self_asserted_client`, `test_multiplexed_identity_requires_per_client_token`, `test_json_rpc_forwards_client_token_for_authenticated_identity` | VERIFIED |
| Tool-reported work is marked external | `test_agent_reported_work_is_marked_external` | VERIFIED |
| Tool actions refuse duplicate effects | `test_two_phase_action_tools_refuse_duplicate_effects` | VERIFIED |
| Unknown tool and bad payload fail closed | `test_unknown_tool_and_malformed_payload_fail_closed` | VERIFIED |
| JSON-RPC and stdio transport work | `test_jsonrpc_dispatch_round_trip`, `test_stdio_loop_serves_requests_and_stops_at_eof` | VERIFIED |
| Native MCP handshake and tool discovery work | `test_native_mcp_server_exposes_real_tools`; live `hermes -p creator mcp test everrun-dogfood` discovered 11 tools | VERIFIED + DOGFOODED |
| Cross-process Hermes mission preserves recovery gates | Creator dogfood `creator-dogfood-001`: reconcile → request_review → verified_complete, one side-effect line, chain trusted through sequence 11 | DOGFOODED |
| Unauthorized JSON-RPC client is rejected | `test_unauthorized_client_is_rejected_over_jsonrpc` | VERIFIED |
| Adapter claims before firing and records evidence | `test_generic_adapter_claims_before_firing_and_records_evidence` | VERIFIED |
| Handoff refused while an effect is uncertain | `test_handoff_refuses_while_side_effect_is_uncertain` | VERIFIED |
| Handoff transfers authority and is sealed | `test_handoff_transfers_authority_and_records_events` | VERIFIED |
| Briefing keeps critical sections under budget | `test_briefing_respects_token_budget_but_keeps_critical_sections` | VERIFIED |
| Hook installer is reversible and idempotent | `test_hook_installer_is_reversible_and_idempotent` | VERIFIED |
| CLI lifecycle works end to end | `test_full_cli_lifecycle` | VERIFIED |
| Corrupt chain blocks status with unsafe exit | `test_corrupt_chain_blocks_status_with_unsafe_exit` | VERIFIED |
| CLI signs and verifies capsules | `test_capsule_sign_and_verify_via_cli` | VERIFIED |
| CLI handoff and hooks work | `test_handoff_and_hooks_via_cli` | VERIFIED |
| CLI lists and reconciles uncertain effects | `test_actions_command_lists_uncertain_effects` | VERIFIED |
| Hard kill leaves no duplicate work or effects | `test_hard_kill_recovery_has_no_duplicate_work_or_effects` | VERIFIED |
| Fault injection never yields unsafe resume | `test_fault_injection_matrix_never_yields_unsafe_resume` | VERIFIED |
| Naive replay baseline does duplicate | `test_naive_replay_baseline_does_duplicate_the_side_effect` | VERIFIED |
| Crash demo completes with zero duplicates | `test_crash_demo_end_to_end`, `test_cli_demo_accepts_root_alias_and_explicit_json` | VERIFIED |
| Clean-installed MCP CLI exposes help without starting the server | `test_mcp_cli_help_does_not_start_server` | VERIFIED |

## Dogfood release gates

| Gate | Evidence target | Status |
|---|---|---|
| Fresh agent discovers blocked mission without supplied id | `test_fresh_agent_discovers_blocked_mission_without_id`; live Run 002 | VERIFIED |
| Separate operator approval is usable and replay-safe | `test_operator_approval_request_is_digest_bound_and_replay_safe`; live replay refusal | VERIFIED |
| Real Hermes SIGKILL integration | Run 002 `literal-sigkill-005`, process exit `-9`, marker count 1, valid chain | VERIFIED LIVE |
| One-command profile-safe Hermes integration | `test_integrator_uses_noninteractive_enable_all_and_requires_discovery`; Creator discovered 13 tools and mutation succeeded | VERIFIED LIVE |
| Hermes integration installs lifecycle policy automatically | `test_hermes_dry_run_is_profile_local_and_non_mutating`, `test_lifecycle_policy_uses_native_tool_names_and_requires_natural_discovery`, natural Creator dogfood mission `ucel-everrun-lifecycle-natural-draft` | VERIFIED LIVE |
| Hermes uninstall removes only unchanged EverRun-owned policy | `test_hermes_uninstall_removes_only_everrun_owned_skill`, `test_hermes_uninstall_preserves_user_modified_skill` | VERIFIED |
| Automated machine-readable Hermes dogfood regression | `test_protocol_fallback_dogfood_transitions_once_and_valid_chain` | VERIFIED |

See `DOGFOOD.md` for observed friction, live acceptance evidence, and remaining P1/P2 soak scope. All P0 rows are closed; public visibility remains an explicit operator decision.

## Deliberately out of scope for v0.1

| Item | Status |
|---|---|
| Local mission dashboard and operator UI | DEFERRED to v0.2 |
| Ed25519 asymmetric attestation | DEFERRED to v0.2 |
| Log compaction and archival | DEFERRED to v0.2 |
| PostgreSQL backend implementation | CONTRACT ONLY |
| Encrypted capsule sync, RBAC, multi-tenant service | DEFERRED |
