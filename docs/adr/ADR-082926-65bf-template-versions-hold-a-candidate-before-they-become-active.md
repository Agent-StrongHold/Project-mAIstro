---
id: ADR-082926-65bf
title: "Template versions hold a candidate state before they become active"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-29
history:
  - status: Proposed
    date: 2026-08-29
substrate:
  - maistro-engine#ADR-081226-bb3a
implements: []
related:
  - maistro-engine#SPEC-081226-bb3a
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/graph/test_node_template_store.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082926-65bf: Template versions hold a candidate state before they become active

## Context

SPEC-081226-bb3a **R14** says an improvement produced by RSI, Evolve or
learning must be represented as a *candidate* object or template version
before it becomes an active reusable version, that promotion must be explicit
and auditable, and that historical versions and existing instantiated objects
stay unchanged. **AC-11** is its acceptance criterion.

AC-11 is the only criterion in that file with no `ac-modules` anchor. Every
other one names the module that answers for it; AC-11 does not, because
nothing did.

The discipline R14 describes **already exists, for `PipelineGenome`**:

| R14 clause | `maistro-evolve` |
|---|---|
| a candidate is produced | `reflect.spawn_challenger` — deep copy, new id, `generation + 1`, `parent_a_id` set, fitness cleared |
| the published version is unchanged | the same: the parent genome is never mutated |
| promotion only after a policy gate | `approved_for_promotion`, defaulting `False`; `PopulationStore.promote` refuses without it |
| explicit and auditable | `promote_audited` — attempt recorded before the mutation, fail-closed; a failed commit entry compensates |

The template families have none of it. `NodeTemplate` and `GraphTemplate`
carry `template_id`, `version` and `content_hash`: a version exists or it does
not, and if it exists it is what every unversioned resolution returns.
`InMemoryNodeTemplateStore.put` refuses redefinition, which is R14's
*immutability* half (and AC-7); it says nothing about the *candidacy* half.
There is no promotion operation on either store.

So an improvement to a template has two options today — publish it as an
active version immediately, or not exist. R14 forbids the first; AC-11
describes the second as a failure.

## Decision

**Templates gain a lifecycle. A version can exist as a candidate, and becomes
active only through an explicit, audited promotion.**

`NodeTemplate` and `GraphTemplate` gain
`lifecycle: Literal["candidate", "promoting", "active"]`, defaulting to
`"active"`.

Three rules follow, and they are the whole decision:

1. **No execution path resolves a non-active version.** Unversioned
   resolution returns the latest `active` version; and `require_template` —
   the door every execution goes through — refuses a named version that is
   not active. Reading a candidate is still available through the store's
   own `get`, which is the inspection door. Splitting the two is what stops a
   `Schedule` pinning `template_version` to a candidate from running it.
2. **Promotion is gated.** It takes a `PromotionApproval` naming an approver
   and a reason, as a required argument rather than a mutable field: there is
   no state for an idempotent `put` to overwrite and no default that could be
   permissive. Recording that a thing happened is not deciding that it may.
3. **Promotion is audited, in an order that makes the claim true.** Attempt
   recorded → `promoting` → commit recorded → `active`. The transitional
   state is load-bearing: the durable stores commit the row before the audit
   sink is asked, so activating first would let a concurrent reader
   instantiate a version the audit failure then rolls back. With
   `promoting`, "active implies a committed entry" holds for every observer.
   Compensation catches `BaseException` and is shielded, because
   `CancelledError` is not an `Exception` and a cancelled rollback is not a
   rollback.

**An idempotent re-registration never moves the lifecycle.** Because the hash
excludes `lifecycle`, a caller resubmitting identical content with the field's
default hashes equal to a stored candidate; letting `put` write that through
would activate it with no approval and no audit entry, and demote a promoted
version just as quietly. `promote_audited` is the only thing that changes it.

### `lifecycle` is excluded from the content hash

The rule is that a fact *about* a definition must not change what the
definition *is*:

> Two templates that differ only in whether they have been promoted are the
> same definition. If `lifecycle` entered the hash, promoting a candidate
> would change its `content_hash` — and every object instantiated from it
> while it was a candidate cites that hash in `source_template`. Promotion
> would retroactively falsify their provenance.

Candidacy is lifecycle, not content. `content_hash` answers "what is this
definition"; `lifecycle` answers "may it be handed out by default". They are
different questions and the hash must only answer the first.

The same rule is being recorded in parallel for `saved_from` in
ADR-082926-d0dc (#40, in flight). That is a citation rather than a
dependency: this decision stands on its own reasoning and neither ADR needs
the other to land first, so there is no `substrate` edge between them.

### The default is `"active"`, and that is deliberate

The opposite default would be safer in isolation and wrong here. Every
template written before this decision is an active reusable definition;
defaulting to `"candidate"` would make the stored JSONB payloads read back as
candidates and make every existing template invisible to unversioned
resolution on the first deploy. Safety by default is worth a great deal, but
not a silent outage of every template in the system.

The gate that matters is not the field's default — it is that promotion is
the only way `lifecycle` changes after `put`, and that a caller has to ask for
candidacy explicitly to get it.

### What the rejected answer would have cost

The alternative was to bind R14 to the genome layer only, anchor AC-11 at
`maistro_evolve`, and amend the spec to put the template families out of
scope until an improvement path targets them.

That is honest about what is built, and it is cheaper. It was rejected
because R14 says "object/**template** version" in as many words, and because
the ordering matters: an evolve→template bridge built *before* templates can
hold a candidate would have nowhere to put its proposals except straight into
the active version, which is precisely the silent mutation R14 exists to
prevent. Deciding the template side first is what makes that bridge
buildable without a migration later.

The cost of this answer is that the improvement path in AC-11's scenario is
any caller rather than `maistro-evolve` specifically. That is recorded in the
consequences below rather than hidden.

## Consequences

### Positive

- AC-11 gets an anchor and the spec's `ac-modules` map is complete.
- R14's candidate discipline holds for templates with the same shape it
  already has for genomes, so there is one idea in the codebase rather than
  two that agree by luck.
- An improvement path can propose a template version without touching what
  anyone is using — which is the precondition for building the
  evolve→template bridge at all.

### Negative / Trade-offs

- **The improvement path AC-11 exercises is not yet `maistro-evolve`.** No
  file there imports `NodeTemplate` or `GraphTemplate`; that bridge is a
  follow-up. What is proven here is that the template layer *can hold* a
  candidate and *does* refuse to serve one by default. A reader should not
  take AC-11's marker as evidence that Evolve proposes template versions
  today, and the test says so in its own docstring.
- Three states in the resolution path are three things to get wrong. The
  mitigations are that exactly one operation may change the lifecycle, that
  `put` cannot move it at all, and that both non-active states are excluded by
  the same predicate rather than by two that must agree.
- A promotion whose final activation fails leaves the version `promoting`:
  audited as committed but not serving. That is the safe direction of the two
  — a promotion that did not finish, rather than an unaudited active version —
  and `lifecycle_of` reports it rather than hiding it. It does mean an
  operator can find a stuck `promoting` version and must re-run the
  promotion.
- `lifecycle` is a nullable-shaped field in practice: rows written before it
  read back as `"active"` by default. That is the intended reading and not a
  migration, but it does mean the field cannot later be used to distinguish
  "authored active" from "promoted active" without a real migration.

### Neutral

- No migration. Both families are stored as JSONB payloads, so an added field
  with a default reads back on old rows.
- No change to `content_hash` semantics, and no change to AC-7's redefinition
  refusal: registering a candidate as version N when version N already exists
  with different content is still a conflict.
