---
id: ADR-083126-5e62
title: "Generated quality evidence is not the judge after trusted-base migration"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-31
accepted: 2026-08-31
substrate: []
implements: []
related:
  - maistro-engine#ADR-082526-1899
  - maistro-engine#ADR-082926-25a2
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/test_autonomous_merge_quality_classes.py
history:
  - status: Proposed
    date: 2026-08-31
  - status: Accepted
    date: 2026-08-31
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083126-5e62: Generated quality evidence is not the judge after trusted-base migration

## Context

The autonomous-merge policy historically classified every `quality/**` edit as
RED. That was safe when quality ratchets read their baseline from the candidate
tree: an author who could weaken the same ledger used for the verdict could
approve their own regression.

That blanket rule becomes inaccurate once a ratchet has moved its comparison
authority to trusted-base provenance. In that state the candidate copy is an
observation or bookkeeping artifact, while the protected base supplies the
oracle and any authorization. Treating both as the same trusted surface hides
which change actually edits the judge and serializes unrelated work around
mechanical ledger updates.

The inverse mistake would be worse: exempting every file named `*-baseline.json`
because it looks generated would reopen the candidate-as-oracle defect for any
ratchet whose migration is incomplete.

## Decision

`quality/**` remains deny-by-default. The protected-base
`quality/branch-independence.json` registry is the single classification source
for autonomous-merge risk.

Only surfaces whose reviewed registry kind is `base_derived` or `generated` may
be downgraded from RED to YELLOW. That registry change must happen only after the
owning checker has proved its comparison authority is independent of the
candidate copy.

All other quality kinds remain RED:

- `specification` because changing it changes reviewed policy;
- `per_identity_policy` because it carries durable authorization or disposition;
- `folded_notes` because it contributes trusted bound state even though the fold
  is branch-independent;
- `legacy_shared_aggregate` and `retired_compat` because their migration or
  compatibility semantics are incomplete;
- unknown, malformed, missing, or multiply matched classifications because a
  failure to establish provenance cannot grant less scrutiny.

The registry itself is a RED specification. The autonomous-merge judge and the
registry are both loaded from the protected base, so a candidate cannot edit its
own registry copy to weaken the classification used for that same PR.

YELLOW remains human-only for autonomous PRs under the current risk model. This
decision therefore distinguishes evidence from judge without granting a new
class of changes autonomous merge authority. A later decision may promote a
specific YELLOW class only after dedicated safety evidence exists.

## First migration

`quality/wiring-reads-baseline.json` is the first surface moved to
`base_derived`. `scripts/check-wiring-reads.py` measures the candidate, but
`_trusted_baseline()` resolves its comparison ledger through
`ratchet_provenance.resolve_baseline()` and reads authorizations from that exact
trusted baseline revision. Candidate banking therefore cannot authorize newly
unread wiring.

No other legacy surface is reclassified by this decision. Each future migration
must prove the same authority property independently before its protected-base
registry entry changes.

## AC-state and stale branches

The historical AC-state contradiction no longer requires a generated shared
measurement commit during ordinary PR review. #723 moved improvement durability
to merge-time actual-base comparison. AC-state folded notes therefore remain RED
without recreating the old mandatory-rebank loop.

Stale-branch attribution is a separate problem. Repository-owned queue admission
uses a current-base-to-prospective-merge diff so changes that landed on
`develop` after the branch was cut are not charged to the candidate. This ADR
does not add another stale-diff implementation to the risk classifier.

## Consequences

### Positive

- A risk report can distinguish "candidate edited the judge" from "candidate
  updated evidence whose judge lives on the protected base."
- Provenance migrations unlock incrementally by changing one reviewed registry
  entry instead of editing another hard-coded allowlist in the merge checker.
- Candidate-controlled self-exemption remains impossible.
- Unknown and partially migrated quality state remains fail-closed.

### Negative / trade-offs

- A migrated generated ledger is still YELLOW, so this decision alone does not
  make such a PR autonomously mergeable.
- The protected-base branch-independence registry becomes an input to the
  autonomous-merge policy and must remain schema-compatible with the judge.

## Acceptance

- A migrated `base_derived` quality surface reports YELLOW with a distinct
  evidence reason.
- Policy, legacy, unknown, malformed, and ambiguous quality state reports RED.
- Merge groups may carry YELLOW generated evidence after PR-time policy, while
  RED quality state remains blocked.
- Wiring-reads is removed from the frozen legacy set only because its current
  checker already proves trusted-base comparison and authorization provenance.
