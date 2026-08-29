---
id: ADR-082926-d0dc
title: "Save-as-template records the object it was saved from, outside the content hash"
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
  - packages/maistro-core/tests/test_graph_definitions.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082926-d0dc: Save-as-template records the object it was saved from, outside the content hash

## Context

SPEC-081226-bb3a **AC-6** says that when a customized Node is saved as a new
NodeTemplate, *"a new template identity and version exist, **and their
provenance identifies the source Node**, and the Node itself is unchanged"*.

Two of those three clauses hold. The third has nothing to bind to:

- `TemplateProvenance` carries `template_id`, `template_version`,
  `template_hash` — it records the template an **object** came from.
- `NodeTemplate.from_node` explicitly *excludes* `source_template` from the
  values it copies, and records nothing in its place.
- `GraphTemplate.from_graph` likewise keeps no reference to the Graph.
- No field anywhere in `maistro.graph.definitions` names the object a template
  was saved from.

So provenance runs one way only: object → template. The reverse direction,
template → source object, is the direction AC-6 asks for and the direction
save-as-template creates. Without it, a template promoted out of a live object
is indistinguishable from one authored from nothing, and the question "where
did this reusable definition come from" has no answer once the session that
saved it ends.

This is the same class of gap as AC-10's `graph/workflow` half, which recorded
no `source_import_provenance` (fixed in #577). The difference is that AC-10's
source was a *legacy format* and this one is a *live workspace object*.

## Decision

Add `saved_from: SourceObjectProvenance | None` to `NodeTemplate` and
`GraphTemplate`, populated by `from_node` and `from_graph`.

`SourceObjectProvenance` records:

| field | why |
|---|---|
| `object_kind` | `"node"` or `"graph"` — the two things that can be saved |
| `object_id` | the `node_id`/`graph_id` the template was promoted from |
| `object_hash` | the object's content at the moment of saving |
| `object_source_template` | the object's own `source_template`, when it had one |

The last field is what makes lineage a chain rather than a single hop: a Node
instantiated from T@1, customized, then saved as U@1 has `U.saved_from`
naming the Node *and* recording that the Node itself came from T@1. Without
it the chain breaks at every save and "what is this ultimately derived from"
becomes unanswerable after two steps.

**`saved_from` is excluded from the content hash.** This is the load-bearing
half of the decision. `_reusable_content` already excludes `template_id`,
`workspace_id` and `version` because they are identity rather than content;
`saved_from` joins them for a stronger reason:

> Two templates saved from two different Nodes that happen to carry identical
> content **are** identical content. If `saved_from` entered the hash they
> would hash differently, and the store's idempotent re-registration — AC-7,
> "re-registering identical content is a no-op" — would start refusing
> re-registration as a redefinition conflict. Provenance about where content
> came from must not change what the content *is*.

The same reasoning is why `Node.source_template` is *inside* the node's
content today and this is outside the template's: a Node's provenance is part
of what that instantiated object is, while a template's origin is a fact
about its creation, not about the definition it offers for reuse.

## Consequences

### Positive

- AC-6's third clause becomes assertable, and lineage survives the session
  that created it.
- Saving is auditable in both directions: an object says which template it
  came from, and a template says which object it was promoted from.
- Idempotent re-registration is untouched, because the hash is untouched.

### Negative / Trade-offs

- `saved_from` is a nullable field that most templates will not carry —
  authored templates have no source object. Readers must treat `None` as
  "authored, not promoted", not as "unknown".
- Recording `object_id` retains a reference to an object that may later be
  deleted. This is deliberate: the record is what the save *was*, not a live
  pointer, and a dangling id is more informative than no id. It is not a
  foreign key and must never be dereferenced as one.
- The chain field means a long promote → customize → save cycle carries a
  little history in every template. Bounded in practice by one hop per save,
  and it is provenance rather than content, so it never reaches the hash.

### Neutral

- No migration. Both template families are stored as JSONB payloads, so an
  added optional field reads back as `None` on rows written before it.
- `GraphTemplate.from_graph` keeps copying each Node's own `source_template`
  as it does today; this decision adds the graph-level record beside it and
  changes nothing about the node-level one.
