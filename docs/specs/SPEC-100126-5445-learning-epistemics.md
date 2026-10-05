---
id: SPEC-100126-5445
title: "Learning epistemics — applicability, evidence-gated promotion, durable provenance (M4-B3)"
repo: maistro-engine
kind: spec
status: Tests Passing
created: 2026-10-01
accepted: 2026-10-01
history:
  - status: Proposed
    date: 2026-10-01
  - status: Accepted
    date: 2026-10-01
  - status: Tests Passing
    date: 2026-10-01
substrate:
  - maistro-engine#ADR-100126-5445
  - maistro-engine#ADR-015
  - maistro-engine#ADR-013
  - maistro-engine#ADR-080
  - maistro-engine#ADR-083026-a91e
implements:
  - maistro-engine#ADR-100126-5445
related:
  - maistro-engine#SPEC-216
  - maistro-engine#SPEC-243
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/memory/learnings/test_applicability.py
  - packages/maistro-core/tests/memory/learnings/test_evidence_promotion.py
  - packages/maistro-core/tests/memory/learnings/test_learning_store.py
  - packages/maistro-core/tests/persistence/test_learning_contract.py
  - tests/memory/learnings/test_learning_store.py
source:
  - packages/maistro-core/src/maistro/memory/learnings/evidence.py
  - packages/maistro-core/src/maistro/memory/learnings/store.py
  - packages/maistro-core/src/maistro/memory/learnings/wisdom.py
  - packages/maistro-core/src/maistro/memory/learnings/extractor.py
  - packages/maistro-core/src/maistro/persistence/learning_contract.py
  - alembic/versions/054_learning_applicability_epistemics.py
layer: Memory
ac-modules:
  AC-1: maistro.memory.learnings.wisdom
  AC-2: maistro.memory.learnings.store
  AC-3: maistro.memory.learnings.evidence
  AC-4: maistro.memory.learnings.evidence
  AC-5: maistro.memory.learnings.extractor
  AC-6: maistro.persistence.learning_contract
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-100126-5445: Learning epistemics — applicability, evidence-gated promotion, durable provenance (M4-B3)

The testable face of ADR-100126-5445. A reusable learning stops being one
string plus counters: it carries where the claim holds (`works_when`) and
fails (`avoid_in`), how the record claims to know (`epistemic_type`), how
strong the evidence is (`confidence`, measured from recorded outcomes), and
which executions supplied it (`run_id`, `evidence_run_ids`,
`evaluation_ids`). Promotion keys on that evidence, not on retrieval
frequency; provenance survives every consolidation that rewords the text.

Out of bounds: the episodic tiers (ADR-080/ADR-013 remain the weight axis for
episodes), the approval consumption surface (`maistro.memory.learnings.approval`,
banked unreachable), and any UI.

## Acceptance Criteria

- An imported CoinSwarm wisdom lesson maps its `excels_in`/`avoid_in` onto
  structured `works_when`/`avoid_in` lists (clamped, junk-tolerated), carries
  the swarm's confidence as a `reported` prior, and cannot promote on that
  assertion alone — confidence without a source Run or evaluation id is not
  evidence. **AC-1**
- Every learning row states its epistemic type explicitly, and retrieval uses
  it only as a bounded tie-break: the bonus reorders keyword ties and can
  never let a less relevant learning outrank a more relevant one; the type
  survives a persistence round trip intact. **AC-2**
- Promotion requires evidence, not hits: the shared
  `promotion_blockers` verdict demands a source Run or evaluation id, a
  measured `confidence` at or above the floor (`NULL` — never measured — is a
  blocker), and a strict majority of recorded outcomes in favour; a learning
  at the hit threshold with no evidence stays `active`. **AC-3**
- Epistemic type raises the bar where the claim is weaker: a `counterfactual`
  learning additionally requires an evaluation id, because only an evaluation
  can test what would have happened; an `inferred` learning needs only the
  ordinary evidence set. **AC-4**
- Distillation is wording, never warrant: an LLM-distilled RCA learning lands
  `inferred` and cannot self-promote; it promotes only once a real Run or
  evaluation backs it and the outcome counters measure it. **AC-5**
- Provenance survives consolidation: rewording keeps the union of
  applicability and evidence, SQL dedup folds the incoming producer into
  `evidence_run_ids`, the first measured outcome overwrites a `reported`
  prior with a measurement, and both SQL twins declare the same complete
  persistence contract for every Learning field (legacy files upgrade in
  place). **AC-6**

## Validation

`@pytest.mark.ac("SPEC-100126-5445/AC-N")` markers name the proving tests:
AC-1/AC-2/AC-6 in `test_applicability.py`, AC-3/AC-4/AC-5 in
`test_evidence_promotion.py` plus the store-level promotion tests in
`test_learning_store.py` (package suite and its root `tests/` twin), and the
twin-parity machine checks in `test_learning_contract.py`. The PostgreSQL DDL
half is migration `055_learning_applicability_epistemics` (single linear head,
see the chain test; renumbered past develop's `052_learning_stage_ladder` and
this branch's `053_backlog_work_source` / `054_learning_lifecycle_columns`, all
of which the develop syncs brought onto the same parent); the SQLite twin
upgrades in place.
