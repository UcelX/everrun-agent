# EverRun Agent engineering rules

## Product invariant

EverRun is a local-first durability layer for AI agents. It must fail closed after crashes, preserve mission state outside transcripts, and never repeat an uncertain external side effect without authoritative reconciliation.

## Required workflow

1. Use strict TDD for every behavior change: targeted RED, minimal GREEN, full regression.
2. Keep all public mutations transactional with their audit event.
3. Route irreversible effects through claim-before-fire and reconciliation.
4. Treat agent-reported progress as external and non-self-certifying.
5. Preserve explicit mission closure; reaching a numeric target is not terminal completion.
6. Keep recovery precedence total and conservative: corrupt chain > uncertain effect > review > drift repair > continue/close > verified terminal.
7. Validate public identifiers and payload bounds at store, CLI, and tool boundaries.
8. Do not weaken SSRF, command allowlist, identity, approval-ticket, redaction, or capsule-verification defaults.

## Hermes integration invariants

- Canonical packaged policy: `src/everrun_agent/integrations/hermes/SKILL.md`.
- Repository convenience copy: `integrations/hermes/SKILL.md`; it must remain byte-identical.
- Hermes native tool names are `mcp_everrun_everrun_*`, not bare `everrun_*`.
- `everrun integrate hermes` must install one profile-local MCP entry, one profile-local state DB, and the lifecycle skill.
- Uninstall may remove only an unchanged EverRun-owned skill. User-modified policy must be preserved.
- Never touch another profile's SOUL, memory, `.env`, model/provider, platform credentials, or unrelated MCP entries.
- One production profile should have one `everrun` server; test/dogfood servers must not survive release setup.

## Verification gates

Run separately after the final edit:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/mypy src/everrun_agent
.venv/bin/python -m build
```

Then inspect the wheel for both CLIs, `py.typed`, and the lifecycle skill; install it in a clean venv; run `everrun --help`, `everrun-mcp --help`, and the JSON demo. Run a tracked-file secret scan and require a clean git tree after commit.

## Documentation contract

Every shipped claim must map to an executable test in `REQUIREMENTS.md`. Record real-agent defects and acceptance evidence in `DOGFOOD.md`. README is product-facing: installation, use, guarantees, honest limitations, and supported platforms only. Internal debugging narratives stay outside README.

## Release policy

A private push is backup, not public release. Public visibility, tags, GitHub release, and PyPI publication require explicit operator approval after the full local, clean-wheel, live-agent, and remote CI matrix is green.
