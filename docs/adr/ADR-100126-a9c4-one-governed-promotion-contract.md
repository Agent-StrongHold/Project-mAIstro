---
id: ADR-100126-a9c4
title: "One governed promotion contract for every reusable definition family"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-10-01
accepted: 2026-10-01
substrate:
  - maistro-engine#ADR-083126-5e62
implements: []
related:
  - maistro-engine#SPEC-081226-bb3a
  - maistro-engine#ADR-082926-65bf
  - maistro-engine#ADR-092526-4391
  - maistro-engine#ADR-093
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/governance/test_promotion_contract.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-10-01
    reason: "The six family-local promotion disciplines need one stated contract."
  - status: Accepted
    date: 2026-10-01
    reason: "The contract module, its fences and its ledger are implemented and regression-tested in the same change; the template family's approval type is reconciled onto it."
---

# ADR-100126-a9c4: One governed promotion contract for every reusable definition family


## Context

MAIstro keeps its improvement paths on a candidate-before-promotion
discipline, but each family states that discipline in its own vocabulary:

| Family | Candidacy | Gate | Audit | Rollback |
|---|---|---|---|---|
| Graph/Node templates (`maistro.graph`) | `lifecycle="candidate"` (ADR-082926-65bf) | required `PromotionApproval` | `promote_audited` attempt/commit entries | re-promote prior version |
| Pipeline genomes (`maistro-evolve`) | challenger spawn, parent untouched | `approved_for_promotion`, default `False` | `GenomeAuditTrail` + `promote_audited` | `rollback_target_id` |
| RSI code patches (`maistro-rsi`) | patch branch, never the baseline | Warden + RLPHD `promotion_review` | flagged/ queue + harvest PR record | revert-now + saved patch |
| Skills (`maistro.skills`) | unvetted trust-tier floor (t3) | authenticated promotion step | signing (SPEC-005) | canary auto-rollback |
| Prompts (`maistro.prompts`) | unlabeled version | label move (`production`) | version history | re-point the label |
| Learnings | `status='candidate'` | hit-count threshold | status transition | demote |

Six statements of the same five promises: a candidate is not an active
thing; promotion is explicit and someone decided it; the decision is
recorded before the effect; history does not change; what was promoted can
be traced to the evidence that justified it and the measurements that
judged it later. Nothing can check those promises *once*, because no object
in the codebase carries them all. The concrete failures that pattern
already produced: the RSI promotion path let a candidate edit the code that
promotes it until #303/#513 derived the containment surface; the template
family let any caller promote until #589 required an approval argument; the
merge classifier let a candidate weaken its own quality ledger until
ADR-083126-5e62 moved the judge to trusted base. Each fix was local. None
of them could state, in one place, the invariant they were all re-deriving.

M4-A9 (#116) asks for exactly that statement: one canonical promotion
contract shared by prompt, skill, template, policy, routing/harness
configuration, and explicitly authorized code improvements.

## Decision

**`maistro.governance.promotion` is the single statement of the promotion
contract.** It defines the contract's objects; it does not execute
promotions. Activation stays where it is today — each family's store keeps
owning versions, resolution, and its sanctioned `promote_audited`-class
transition — and the contract owns the *decision record* every family maps
onto:

- **`PromotionScope`** — the six families: `prompt`, `skill`, `template`,
  `policy`, `routing_config`, `code`. The list is closed and every
  construction site of a contract must classify *all* of them.
- **`CandidateChange`** — a proposed improvement that by construction
  changes nothing: no version minted, no label moved, no resolution
  altered. Candidacy is a value, not a store state, so "candidate creation
  is distinct from activation" is enforced by what the type *cannot do*,
  not by caller discipline.
- **`PromotionApproval`** — one approval type for the whole codebase. The
  template family's local class is retired to a re-export of this one, so
  there is no second, weaker approval beside it (the same posture
  ADR-082926-65bf took toward `GenomeAuditTrail`). It carries `approver`,
  `reason`, `policy_id` (never empty — a promotion record that cannot say
  what policy allowed it cannot be audited) and `authority` (who decided,
  as distinct from who signed).
- **`PromotionContract.evaluate/promote`** — the gate. Its fences, in
  firing order:
  1. **evidence** — at least one evaluation Run id (canonical
     `Goal -> Graph -> Run` ontology) and a version for every evaluator
     involved;
  2. **own-constitution** — a candidate whose `changed_refs` intersect the
     scope's protected constituents (its evaluators, its security
     constitution) is refused, whatever the approval says. The evaluator or
     constitution change is a separate candidate in its own scope,
     promoted under its own classification — the same separation
     ADR-083126-5e62 drew between evidence and judge, and #303 drew
     between a diff and the classifier that reviews it;
  3. **self-approval** — the deciding authority must not be the authoring
     path (`rsi` approving `rsi` is the refusal the whole RLPHD checkpoint
     review exists to make expensive);
  4. **staleness** — the candidate's base must still be current by number
     *and* hash, so a promotion can never silently overwrite whatever
     moved since the candidate was cut;
  5. **no-op** — content identical to the base is not a promotion.
- **`PromotionRecord` / `PromotionLedger`** — the immutable record (scope,
  subject, prior/new version, both content hashes, evidence, evaluator
  versions, approval policy, rollback metadata) and the append-only ledger
  around it. Records are never edited; a reversal appends a
  `ReversalEntry` beside the record; a later effect measurement attaches
  by record id and cites its own Run ids. The minted version number is
  never reused — a rollback-and-repromote mints the next number — so
  `(scope, subject, version)` always names exactly one content hash, which
  is the immutability promise in its checkable form.

**The contract is not a sixth promotion mechanism.** It is the ledger and
gate the existing six map onto. A family adopts it by producing a
`PromotionRecord` from its sanctioned transition; the template family
additionally shares its approval type (done in this change, since the class
was definitionally the same object). Families that have not adopted the
ledger yet are not in violation of this ADR — adoption per family is
tracked in the spec's ACs, not asserted here.

### Why the protected-constituent classification is a constructor argument

The contract refuses to be constructed without a classification for *every*
scope. An explicit empty set is a written decision that a family has no
protected constituents; a missing entry is refused, because an unclassified
family is an unguarded fence — ADR-083126-5e62's doctrine (a failure to
establish provenance cannot grant less scrutiny) applied to construction
time, where it costs one line, rather than evaluation time, where it costs
a compromise. The authoritative code-scope classification remains
`maistro_rsi.sensitive_paths` and the derived containment surface
(`check-promotion-surface.py`); a host passes those patterns in rather than
this module growing a second copy that would drift from the real one.

### What this deliberately does not decide

- It does not move genome promotion onto `PromotionApproval`. The genome
  gate (`approved_for_promotion=False` refusal) is the same posture with a
  different mechanism, and rewiring `maistro-evolve`'s audited transition
  is migration work, not contract definition. Recorded as follow-up.
- It does not give prompts, skills or learnings a ledger. Their semantics
  are compatible (label moves, trust tiers, hit thresholds) but their
  stores have no record object yet. Recorded as follow-up.
- It does not replace `maistro_rsi.promotion_review`. RLPHD is a *predictor
  of human approval* feeding this contract's `PromotionApproval`, not a
  competing gate.

## Consequences

### Positive

- The five promises are checkable in one place, with tests that fail once
  and mean six things.
- A future improvement path (evolve→template bridge, learning→prompt
  promotion) has a gate to call instead of a pattern to re-derive — the
  precondition ADR-082926-65bf named when it decided the template side
  first.
- Traceability has a shape: record id → evidence Run ids → effect
  measurement Run ids. Nothing else in the repo can answer "what measured
  this promotion before and after" without grepping.

### Negative / Trade-offs

- Six families now share one refusal vocabulary, so a fence firing in an
  unexpected family is visible org-wide. That is the point, but it means
  fence changes are governance changes, not library changes.
- The contract takes `current_version`/`current_content_hash` from the
  caller rather than reading a store. A caller that lies (stale snapshot)
  gets a record minted past the wrong base; the mitigation is that the
  record carries both hashes, so the lie is on the record — the ledger
  shows the collision at the next promotion of the same subject.
- The graph template family now constructs the canonical approval with a
  default `policy_id` (`direct-approval`) until its stores record a real
  policy. Honest but coarse: those records cannot distinguish reviewer
  policies yet.

### Neutral

- No migration, no schema change: the ledger is a value object until a
  store adopts it.
- `PromotionApproval` gains two defaulted fields; every existing
  construction site keeps working (the template tests are the proof).
