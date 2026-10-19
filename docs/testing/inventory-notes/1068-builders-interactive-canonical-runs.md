---
# Issue #1068 Builders interactive canonical execution

Issue: #1068
Parent: #49

inventory-delta:
  packages/maistro-core/tests: +5
---

## Claim and collision boundary

The shipped `maistro builders` TUI remains the product entry point and keeps
SPEC-201's ReAct `TurnRunner` as its domain strategy. The new adapter admits
one bounded interactive turn as a canonical Graph/Run and executes the ReAct
strategy as the physical work of its NodeRun/Attempt. No Builders-private Run
store, scheduler, authorization path, or effect provider is introduced.

The CLI uses the existing `wire_execution_spine` backend selection. With no
configured deployment database it uses the CLI's private SQLite scope at
`~/.maistro/builders.db`; configured SQLite/PostgreSQL URLs use the same
canonical stores and inspection identity. Session history stores the exact
canonical `run_id` values rather than treating the local session ID as an
execution identity.

## Evidence

`test_react_turn_is_admitted_as_one_canonical_run_and_physical_attempt` proves
one interactive turn creates a scoped canonical Run, one Builders NodeRun and
one completed Attempt. The failure test proves the ReAct `max_turns` failure
settles the canonical Run and Attempt as failed rather than returning success.

`test_cli_spine_retains_run_identity_across_reopen` runs against the real
SQLite-backed spine from `wire_execution_spine` — no in-memory test shim —
and proves the persisted Run carries the local-operator actor principal
(`builders-local:<user>`, `MAISTRO_BUILDERS_ACTOR_PRINCIPAL`, or an explicit
argument, per `resolve_local_operator_principal`). Develop's #364/#1841 store
boundary rejects admission without a principal, so the shipped TUI path
admits through a real operator identity rather than a test default.
`test_local_operator_principal_resolution_precedence` pins the
explicit-argument > env > OS-user precedence and that the fallback identity is
never empty.

Cancellation remains owned by `run_durable_graph`: its cancellation handler
settles open physical work and the canonical Run before propagating the task
cancellation to Textual.

## Repair round (CI at 21d730b4c, 2026-10-19)

Four required checks failed at the synced head with one root cause: this
branch's matrix edit cited `ADR-099` in the Builders pipeline row's
*Governing ADR/spec* cell, but ADR-099 is `Proposed`, and a Proposed decision
cannot govern an active document (`scripts/check-citation-status.py`:
`matrix#Builders pipeline.governing -> maistro-engine#ADR-099`). The same
unauthorized exception red `test` (3 failures in
`tests/test_check_citation_status.py`, 5371 passed), `Coverage gate` (3
failures, 363 passed), `exact-debt-ledger`
(`check-ratchet-provenance.py`: 0 -> 1 citation exceptions), and `Validate
ADR/spec front-matter` (its `check-citation-status-provenance.py` step).

Repair: dropped `ADR-099` from the governing cell, leaving `ADR-090`
(Accepted, five-stage stage machine) and `SPEC-201` (Accepted, interactive
ReAct UX). This is also the semantics the issue requires — the shipped
interactive path must not sit under the five-stage DAG proposal, which stays
a Proposed direction, not shipped authority. No ledger amendment was used:
a new citation exception cannot be candidate-authorized (the ratchet reads
authorizations from the merge base), and the vulture ledger needed no change
(1321 reviewed identities -> 1320 findings, `unclassified: 0`).

Re-executed evidence at the repaired head: `check-citation-status.py` OK;
`RATCHET_BASE_REV=origin/develop check-citation-status-provenance.py` OK
(0 -> 0); `check-ratchet-provenance.py` all ratchets OK;
`check-shipped-surface-truth.py` OK; `check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'` OK;
`pytest tests/test_check_citation_status.py` 252 passed;
`check-convergence-matrix.py` OK (52 subsystems, 1414 modules);
`maistro-registry lint . --strict` OK; registry job unit battery 194 passed;
builders/cli/retention lane suites 54 passed, 9 skipped.
