---
id: SPEC-100126-a9c4
title: Canonical promotion contract (M4-A9)
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-10-01
accepted: 2026-10-01
history:
  - status: Proposed
    date: 2026-10-01
    reason: "The scattered candidate-before-promotion disciplines need one stated contract."
  - status: Accepted
    date: 2026-10-01
    reason: "The contract module, its gates and ledger are implemented with regression tests."
  - status: AC Defined
    date: 2026-10-01
    reason: "Seven acceptance scenarios mirror the contract's test classes one-to-one."
substrate:
  - maistro-engine#ADR-100126-a9c4
implements:
  - maistro-engine#ADR-100126-a9c4
related:
  - maistro-engine#SPEC-081226-bb3a
  - maistro-engine#SPEC-082926-a6ab
  - maistro-engine#SPEC-083026-427c
  - maistro-engine#ADR-082926-65bf
  - maistro-engine#ADR-083126-5e62
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/governance/test_promotion_contract.py
source:
  - packages/maistro-core/src/maistro/governance/promotion.py
ac-modules:
  AC-1: maistro.governance.promotion
  AC-2: maistro.governance.promotion
  AC-3: maistro.governance.promotion
  AC-4: maistro.governance.promotion
  AC-5: maistro.governance.promotion
  AC-6: maistro.governance.promotion
  AC-7: maistro.graph.templates
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-100126-a9c4: Canonical promotion contract (M4-A9)

- **Status:** AC Defined
- **Date:** 2026-10-01
- **ADR:** `ADR-100126-a9c4`
- **Technical Area:** Governed promotion — prompts, skills, templates, policies, routing/harness configuration, authorized code

## Purpose

State one promotion contract that every reusable definition family shares,
generalizing the candidate-before-promotion semantics each family already
keeps in its own vocabulary (see the family table in
[ADR-100126-a9c4](../adr/ADR-100126-a9c4-one-governed-promotion-contract.md)).

## Canonical model

```text
CandidateChange (inert value — changes no resolution)
        │  only via PromotionContract.promote, gated
        ▼
PromotionRecord (immutable, append-only ledger)
    ├── evidence: evaluation Run ids + evaluator versions
    ├── approval: approver / authority / approval policy
    ├── rollback: prior version stays addressable & immutable
    ├── effects:  later measurements, each citing Run ids
    └── reversals: append-only ReversalEntry beside the record
```

Execution/activation remains family-owned: template stores
(`promote_audited`), genome stores, skill signing, prompt labels. The
contract owns the gate and the record, never the store.

## Requirements

### R1. Candidacy is inert

Creating a candidate MUST NOT mint a version, move a label, or change what
any resolution returns. The only path from candidate to effect is a gated
promotion.

### R2. Promotion mints a new explicit version

A promotion MUST record a new version number for the subject, greater than
every version previously recorded for it. A version number MUST NOT be
reassigned to different content; a rollback-and-repromote takes the next
number.

### R3. History is immutable

A promotion record MUST NOT be edited. Correcting it happens by appending
another record or a reversal entry. The record cites the prior version and
both content hashes, so the prior version remains addressable as rollback
target.

### R4. The record is complete

A promotion record MUST carry: scope, subject, prior/new version, prior and
new content hash, evaluation evidence citing at least one evaluation Run
id, a version for every evaluator involved, the approval (approver, reason,
deciding authority) and the approval policy that allowed it, and rollback
metadata (target version, reversibility, mechanism).

### R5. A candidate cannot edit its own evaluator or security constitution

A candidate whose changed refs intersect the scope's protected
constituents MUST be refused regardless of approval. Protected-constituent
classification MUST be explicit for every scope at contract construction;
an unclassified scope MUST refuse construction (fail closed).

### R6. No self-approval

The authority deciding a promotion MUST NOT be the path that authored the
candidate.

### R7. No stale or empty promotion

A candidate whose base (by number or hash) is no longer current MUST be
refused. A candidate whose content equals the current content MUST be
refused.

### R8. Traceability

Every promoted version MUST be traceable, through its record, to the
evaluation Runs that justified it and to later effect measurements recorded
against the record; each measurement MUST cite the Run ids that produced it.

## Acceptance Criteria

```gherkin
Feature: One governed promotion contract

  @AC-1
  Scenario: Creating a candidate changes nothing
    Given a contract with a ledger and a subject currently at v1
    When a candidate is created and even gated through evaluate
    Then the ledger holds no record for the subject
    And the candidate value is unchanged
    And only contract.promote produces a record

  @AC-2
  Scenario: Promotion mints the next explicit version and never reuses one
    Given a subject promoted to v2 through the contract
    When the subject is rolled back to v1 by its store and the same candidate
      content is promoted again
    Then the new record mints v3, not a reassigned v2
    And promoting against a base whose hash no longer matches is refused

  @AC-3
  Scenario: The record is complete
    Given a gated promotion
    When the record is read back
    Then it carries scope, subject, prior and new version, both content hashes,
      evaluation Run ids, evaluator versions, approver, reason, deciding
      authority, approval policy, and rollback metadata naming the prior
      version as target with a reversal mechanism

  @AC-4
  Scenario: A candidate cannot edit its own evaluator or security constitution
    Given a scope whose protected constituents include its evaluator surface
    When a candidate's changed refs intersect them
    Then promotion is refused even under a valid external approval
    And a contract constructed without a classification for some scope is
      refused at construction

  @AC-5
  Scenario: No self-approval
    Given a candidate authored by path P
    When an approval whose deciding authority is P gates it
    Then promotion is refused
    And an approval from an authority outside P passes the fence

  @AC-6
  Scenario: Every promoted version traces to evaluation Runs and effect measurements
    Given a promoted version with evidence citing evaluation Run ids
    When later effect measurements are attached citing their own Run ids
    Then trace(scope, subject, version) returns the record, the effects, and
      any reversal entries
    And attaching a measurement to an unknown record, or duplicating a
      measurement id, is refused

  @AC-7
  Scenario: One approval type across families
    Given the template family's promotion gate
    When its approval argument is constructed
    Then it is the canonical PromotionApproval, not a second definition
```

## Family mapping

| Scope | Candidacy today | Gate today | Record adoption |
|---|---|---|---|
| `template` | `lifecycle="candidate"` | canonical `PromotionApproval` (re-exported) | follow-up |
| `code` | patch branch / export | Warden + RLPHD + containment surface | follow-up |
| `prompt` | unlabeled version | label move | follow-up |
| `skill` | trust-tier floor t3 | authenticated signing step | follow-up |
| `policy` | `PolicyDecision` (conformance) | conformance verdict | follow-up |
| `routing_config` | harness config versioning | harness admission | follow-up |

"Follow-up" means the family's store does not write `PromotionRecord`s yet;
it does not mean the family is exempt from the fences — any new promotion
path built for it must route through the contract.

## Non-goals

This spec does not define: evaluator scoring semantics, the RLPHD
prediction model, per-family store schemas, migration of existing stores to
the ledger, or the approval UI.

## References

- `ADR-100126-a9c4`
- `SPEC-081226-bb3a` (R14, AC-11 — candidate-before-promotion for templates)
- `ADR-082926-65bf` (template lifecycle)
- `ADR-083126-5e62` (generated evidence is not the judge)
- `SPEC-082926-a6ab` (contained candidate validation)
- `SPEC-083026-427c` (prompt versions and labels)
