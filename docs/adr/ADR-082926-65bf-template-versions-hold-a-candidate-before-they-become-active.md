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
  - packages/maistro-core/tests/graph/test_template_lifecycle.py
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
`lifecycle: Literal["candidate", "active"]`, defaulting to `"active"`.

Two rules follow, and they are the whole decision:

1. **Unversioned resolution returns the latest *active* version, never a
   candidate.** This is the failure mode being guarded: a candidate silently
   becoming what everyone gets. A caller naming an exact version still gets
   exactly that version, candidate or not — inspecting a candidate is the
   point of having one.
2. **Promotion is a separate, audited operation**, not a `put`. It records an
   attempt before the state change and a commit after, and compensates rather
   than leaving an unaudited active version — the guarantees
   `promote_audited` already makes, rather than a second weaker discipline
   beside it.

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
- A third state in the resolution path is a third thing to get wrong. The
  mitigation is that exactly one operation may change it.
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
