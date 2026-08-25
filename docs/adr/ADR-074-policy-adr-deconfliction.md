---
id: ADR-074
title: "Policy ⇄ ADR Deconfliction — the governance dialectic (declared intent vs revealed preference)"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-30
substrate:
  - maistro-engine#ADR-070
  - maistro-engine#ADR-073
implements: []
related:
  - maistro-engine#ADR-024
  - maistro-engine#ADR-031
  - maistro-engine#ADR-032
  - maistro-engine#ADR-068
  - maistro-engine#ADR-072
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
  - status: Implemented
  - status: Accepted
    date: 2026-08-25
    reason: "M0 strict evidence reconciliation: current acceptance evidence does not support an Implemented completion claim; implementation history remains recorded."

---

# ADR-074: Policy ⇄ ADR Deconfliction

**Status:** Proposed
**Date:** 2026-05-30
**Closes a hole opened by:** ADR-073 (online-mutable policy) + ADR-068 (adaptive RLPHD) + ADR-070
(Compose auto-adds learned entries) — together these let learned policy **silently drift** from the
documented ADRs with no reconciliation path.

---

## Context

The system now has two sources of truth that can disagree:

- **ADRs = declared intent** — what the team decided it wants, top-down, a priori.
- **The learning policy engine = revealed preference** — what the team actually approves, distilled
  from real human decisions (ADR-073 Sentinel's DB policy + ADR-068 RLPHD adaptive weights). Note the
  RLPHD weights are **interpretable, hand-editable parameters, not an opaque model** (ADR-068) —
  which is precisely what makes this deconfliction tractable: you can read, diff, and reconcile a
  drifted parameter against an ADR invariant; you could not do that to a black box.

When a learned-policy change drifts into conflict with an ADR, *that divergence is the most valuable
signal in the system*: either the ADR is stale, or the learning is noise/poisoning. Neither is
automatically right. Forcing a reconciliation is how the system converges on **what the team genuinely
wants over time, not what it declared on day one** — the ADRs and the learned policy **audit each
other**.

## Decision

### Conflicts never auto-resolve

A learned-policy change (RLPHD θ shift, a new learned allow/deny, an auto-promotion) that conflicts
with an authority **does not activate**. It is **held** (fail-safe — the ADR remains source of truth)
and routed to **admin review** with an **impact analysis**: which authority clause it violates, which
**N deployed artifacts** (recipes/configs/active policies/contracts) also conflict, and the **evidence
behind the learning** (e.g., "θ fell because you approved 8 borderline `deploy` calls in 3 days").

This conflict-check **is the Repertoire *Rehearse* step (ADR-070)**: a learned change is a *Compose*;
it must *Rehearse* against the authorities (next section) before it can commit. Pass → commit;
conflict → admin review.

### Precedence of authorities (checked top-down, stop at first conflict)

A candidate policy decision is compared against authorities in **strict order** — a legal hierarchy:

1. **ADRs** — the *constitution*. Highest authority; **safety-critical ADRs do not bend** (see below).
2. **Specs** — the *statutes*, derived from ADRs. A policy passing the ADR check but contradicting a
   Spec is held; the Spec usually wins (it is amendable only if its parent ADR permits).
3. **Prior policy decisions** — *case law / precedent*. A policy consistent with ADRs + Specs but
   contradicting precedent triggers precedent reconciliation; the newest may supersede old precedent
   **with recorded rationale** — this is how the learned policy legitimately evolves.

The comparison engine that performs this walk is specified in **SPEC-206** (it requires ADRs + Specs
to carry machine-checkable invariants per ADR-031/032, and the prior-policy store to be queryable).

### Three outcomes (admin adjudicates direction-of-correction)

| Outcome | When | Effect |
|---------|------|--------|
| **Revert the learning** | ADR/Spec wins; the drift was wrong / inconsistent / suspect | Learning rolled back; **trains the predictor down**. The authority *caught* a bad drift. |
| **Scoped exception** | Coexist; narrow/contextual divergence | Recorded **waiver with scope + expiry** (revisited, not permanent); authority unchanged. |
| **Amend authority + reconcile** | Learning wins; strong, consistent, broad revealed preference vs a stale/peripheral ADR/Spec | **PR to the ADR/Spec** *and* update the N conflicting artifacts to match. The learning engine effectively *proposed* the change, validated by behavior. |

### Safety-critical ADRs are near-inviolable

ADRs designated **safety-critical** (the ADR-072 threat-model invariants, ADR-028 privilege
separation, the ADR-068 budget veto and authority-subset rule) **do not bend to revealed preference**.
A learned drift against one is treated as a **policy-poisoning signal** (gradual prompt-injection
erosion) → it routes to a **security review**, default = **revert**, never a casual amend. This is the
ADR-072 "ADRs as immune system" made operational.

### Everything is audited

Every conflict, the impact analysis, and the chosen outcome are recorded as **signed VCs** (ADR-024)
and ADR-037 events, feeding back: a reverted learning teaches the predictor; an amended ADR updates
declared intent; an exception is a tracked, expiring waiver.

## Acceptance criteria

- [ ] A learned-policy change conflicting with an ADR/Spec/prior-policy is **held, not applied**, and
      routed to admin review (property test: no conflicting change auto-activates).
- [ ] The review surfaces the violated authority clause + the N conflicting deployed artifacts + the
      learning's evidence.
- [ ] Outcomes are exactly {revert, scoped-exception (with expiry), amend+reconcile}; each recorded as
      a signed VC.
- [ ] A drift against a **safety-critical** ADR routes to security review with default-revert; it
      cannot be amended away by a single admin without the security path.
- [ ] The conformance walk follows SPEC-206 precedence (ADRs → Specs → prior policy), stopping at the
      first conflict.
- [ ] An "amend + reconcile" outcome opens a PR to the authority **and** lists the N artifacts to
      update (no half-reconciled state).

## Consequences

- Closes the silent-drift hole in ADR-073/068/070.
- Makes the ADRs and the learning engine a self-correcting pair — the system builds toward the team's
  *actual* intent.
- Requires SPEC-206 (the comparison engine) and machine-checkable invariants on ADRs/Specs
  (ADR-031/032 evolve to carry them).

## Out of scope

- The model that *generates* learned changes (RLPHD predictor — ADR-068 follow-up SPEC).
- The exact "safety-critical" designation mechanism (a front-matter flag on ADRs — small follow-up).
- The comparison-engine internals — **SPEC-206**.
