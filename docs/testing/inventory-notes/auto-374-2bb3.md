---
inventory-delta:
  tests/: +13
---

# auto-374-2bb3

Reconciliation for the auto-374 lane after merging develop (ba2f1f077) and the
#374 citation repair on top of it.

The merge carried root-suite edits from develop (notably `tests/test_m1_542_diff_coverage_edges.py`,
`tests/test_prepull_copy_sources.py`, `tests/test_verify_wheel_imports.py`) whose collected
node counts moved relative to what each parent's notes had recorded — a merge-shaped drift
the per-change ledger absorbs here rather than on either parent. That drift is −5.

On top of it, this repair parametrized
`test_proposed_related_design_is_marked_historical_not_governing` over the three documents
where an Accepted spec treated a Proposed ADR as governing prose (SPEC-070226-af02/ADR-066,
SPEC-070226-2b70/ADR-055, SPEC-062126-d421/ADR-083): 1 collected node → 3, i.e. +2.

A second develop merge (8bb344e32) then moved the root suite again: new files
(`tests/test_check_durable_table_inventory.py`, `tests/test_ratchet_base_rev_policy.py`,
`tests/migrations/test_audit_scope_migration.py`) and edits to existing ones changed the
collected node set by +2 relative to the ledger as recorded above. All six touched files
collect cleanly (102 nodes, no errors); the drift is merge-shaped, not a silently lost suite.
That +2 absorbs into this same note: −3 + 2.

Net recorded delta: −1. Produced by `check-suite-inventory.py --update`, not estimated.

## Repair follow-up (corpus honesty, second wave)

Independent re-verification flagged that the corpus honesty standard enforced on the three
originally parametrized documents was not applied to seven more specs that received the identical
front-matter-only move (Proposed ADR from `substrate`/`implements` into `related`) with the
present-tense governing prose left intact: SPEC-070226-6489 (ADR-084), SPEC-070226-82ea (ADR-099),
SPEC-070226-b234 (ADR-086), SPEC-070226-b624 (ADR-071), SPEC-070226-c4f8 (ADR-101),
SPEC-070226-cb8d (ADR-079), SPEC-070226-fbe3 (ADR-081). The repair rewords each document's prose
to mark the Proposed ADR as retained design context rather than shipped authority, and extends the
same parametrization over them: 3 collected nodes → 10, i.e. +7. Net for this note: −1 + 7 = +6.
A corpus-wide sweep for `ADR-* (specifies|mandates|says)` against active specs now returns only
these repaired documents plus SPEC-080126-3a7c (itself Superseded — a non-active source, outside
the gate's scope by design). Produced by `check-suite-inventory.py --update`, not estimated.

## Third-wave re-verification and develop-drift merge (1dea30df)

The lane arrived with an in-progress, conflicted merge of develop 1dea30df onto the
#374-repair head 0be75b2d; the single conflict was `docs/architecture/CONVERGENCE-MATRIX.md`.
Resolved to preserve both parents' intents under the #374 rule:

- Skills row keeps the governing cell `ADR-069, ADR-070` (both Accepted). The incoming side's
  `ADR-083` is a Proposed decision and may not be a direct governing authority; it is named only
  as design context in the disposition prose ("trust-policy design context in Proposed ADR-083,
  not shipped authority"), which the matrix scan deliberately does not read as governing.
- Credentials row adopts the incoming #1186 wording (`services.user_credentials`; the merge
  deletes `credential_store_v2.py`, so the parent row would have named a dead module). Its only
  governing citation, ADR-063, is Accepted.

Re-verification evidence on the merged tree: `check-citation-status.py` OK with 0 baselined
exceptions; `tests/test_check_citation_status.py` 64 passed; mypy clean on `maistro-registry`;
`check-convergence-matrix.py` OK (52 subsystems / 1117 modules); `check-suite-inventory.py` OK
(13 suites match); `maistro_registry.cli lint` 407 files clean. A live in-process probe of
`citations.check_citations` reproduced all four diagnostics (Superseded→names active replacement;
forked supersession→contradictory active authority; cycle→reported; Proposed→refused). Grep
confirmations: no active-status document holds ADR-055 or ADR-083 in `substrate`/`implements`;
the only governing-field ADR-083 citations (SPEC-080226-510f, ADR-082226-4478) sit on Proposed
sources, which the gate exempts by design (`test_only_active_sources_claim_live_authority`).

No collected-node change: inventory-delta for this section is +0.

## Repair round: unqualified matrix parentheticals are governing (develop 9e9f5037e merged)

Independent verification of the prior head reproduced the exact bypass the parenthetical
exemption allowed: a matrix governing cell `ADR-001 (ADR-002)` — no historical or supersession
qualifier, just punctuation — dropped ADR-002 from the status gate entirely, so a Proposed
decision cited in a bare parenthetical governed with `problems=[]`.

The repair replaces the blanket `_without_parenthetical_text` strip in
`scripts/check-citation-status.py` with a relation-aware `_governing_ids`: a parenthetical is
exempt only when it names its own relation (`supersedes*`, `historical`, `formerly`,
`previously`, `replaced*`, `proposed in`). IDs in any other parenthetical are checked like the
rest of the governing column. The two real matrix parentheticals — `(supersedes ADR-046)` and
`(tournament contracts Proposed in ADR-070126-6386, SPEC-070126-9d37)` — remain exempt, so the
corpus gate still passes with 0 baselined exceptions.

Tests: +7 collected nodes in `tests/test_check_citation_status.py` — the verifier's probe
(unqualified parenthetical, Proposed target → flagged), the active-target control (no false
positive), four parametrized explicitly-qualified exemptions, and the unqualified Superseded
case naming its active replacement. Also merged develop 9e9f5037e (HITL authorization work,
root-suite neutral: no test files touched). Net recorded delta for this note: +6 + 7 = +13.
Produced by `check-suite-inventory.py --update`, not estimated.
