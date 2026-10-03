---
id: ADR-100126-5445
title: "A learning promotes on evidence, not on hits"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-10-01
accepted: 2026-10-01
history:
  - status: Proposed
    date: 2026-10-01
  - status: Accepted
    date: 2026-10-01
substrate:
  - maistro-engine#ADR-015
  - maistro-engine#ADR-013
  - maistro-engine#ADR-080
implements: []
related:
  - maistro-engine#ADR-083026-a91e
  - maistro-engine#ADR-081226-bb3a
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-core/tests/memory/learnings/test_evidence_promotion.py
  - packages/maistro-core/tests/memory/learnings/test_applicability.py
  - packages/maistro-core/tests/persistence/test_learning_contract.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# ADR-100126-5445: A learning promotes on evidence, not on hits

## Context

A reusable learning was one string plus counters. Nothing on the record said
where the claim holds or fails (`works_when` / `avoid_in`), how strong the
evidence behind it is (`confidence`), which executions supplied that evidence,
or whether the claim was measured, distilled by an LLM, counterfactual, or
imported from an external source such as CoinSwarm's wisdom JSON. Two
consequences followed.

Retrieval could not distinguish a tested correction from a plausible-sounding
one, and promotion keyed on `hit_count` — a count of how often the text was
*retrieved*. A learning promoted for being retrieved often is a claim promoted
on popularity: the system handed it permanent influence over future prompts and
skill mutations without ever asking whether anything had validated it.

## Decision

The `Learning` record gains an epistemic qualification, and promotion is
gated on evidence rather than frequency.

**Structured applicability.** `works_when` and `avoid_in` hold the contexts a
claim is known to hold in and to fail in — the shape CoinSwarm's wisdom JSON
already ships (`excels_in` / `avoid_in`). They are lists, not prose, so they
merge.

**Epistemic type.** `EpistemicType` states how the record claims to know what
it says: `observed` (measured from a real execution), `tested` (validated by an
evaluation), `inferred` (derived or LLM-distilled), `counterfactual` (a claim
about what *would have* happened), `reported` (imported/asserted). It is
persisted on every row and used by retrieval as a bounded tie-break: each type
carries a bonus below 1.0, so the epistemic type reorders keyword ties and can
never let a less relevant learning outrank a more relevant one. This is the
justification axis; the episodic memory tiers (ADR-080, ADR-013) remain the
weight axis for episodes and neither derives from the other.

**Evidence is required for promotion.** The one verdict lives in
`memory.learnings.evidence.promotion_blockers`, shared by the in-memory store,
both SQL twins and the promoter: promotion requires at least one source Run or
evaluation id, a measured `confidence` at or above the floor (strict majority
of recorded outcomes in favour; `NULL` — never measured — is a blocker, per
the rule ADR-083026-a91e set for metrics), and, additionally for a
`counterfactual` claim, an evaluation id, because only an evaluation can test
what would have happened. `min_confidence` is a parameter of the promoter and
the store promotion path, not an unread config field.

**Distillation is wording, never warrant.** An LLM may distill or diagnose
(the RCA extractor does), and its output is stored `inferred`. Distillation
cannot substitute for validation evidence: an inferred learning promotes like
any other — only when a Run or evaluation backs it and the outcome counters
measure it. Imported wisdom lands `reported` for the same reason: the
swarm's confidence is a prior, and the first recorded outcomes overwrite it
with a measurement.

**Provenance survives consolidation.** `run_id` names the one Run that
produced the surviving text; `evidence_run_ids` names every Run whose outcome
supports the claim, and it unions across dedup and rewording. When the
in-memory store rewords a row, the outgoing producer joins `evidence_run_ids`
so the Run that taught a replaced version stays answerable. When the SQL twins
dedup, the incoming producer folds into the evidence list. A reworded claim is
accountable to everything that ever taught it.

## Alternatives considered

- **Promote on hit_count with a higher threshold.** Rejected: frequency of
  retrieval does not converge to correctness, and a wrong learning that
  matches common queries promotes *faster*.
- **Derive epistemic type from the episodic tier.** Rejected: the tiers grade
  confidence weight for episodes; learnings need a justification axis, and
  forcing one through the other would make "imported with high confidence"
  indistinguishable from "validated by an evaluation".
- **LLM-judged confidence at promotion time.** Rejected: it substitutes
  generated judgement for the outcome evidence the counters already hold
  (ADR-083026-5e62).

## Consequences

- Learnings stored before this change read back `observed` with no
  applicability and `confidence = NULL`; they stop promoting until evidence
  accrues through `mark_outcome`. That is the intended strictness, not a
  migration bug.
- Both SQL twins persist the new fields (contract in
  `persistence/learning_contract.py`, PostgreSQL migration 051 — renumbered
  from 048 after develop's `048_canvas_job_retry_backoff` claimed that id on
  the same parent, SQLite in-place upgrade), and the conformance test fails
  if a future field lands in one twin only.
- The wisest import path (`memory.learnings.wisdom.learning_from_wisdom`)
  maps CoinSwarm wisdom JSON onto the record without granting it promotion.
