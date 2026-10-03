---
inventory-delta:
  packages/maistro-design/tests: +42
---
# CreativeBrief versioned projection contract (#773)

Forty-two new collected cases in
`packages/maistro-design/tests/test_creative_brief.py` implement the parent
epic's central invariant before the #774 child lane lands persistence: one
versioned CreativeBrief bound to one exact canonical Goal revision, supplying
the identical shared context to every artifact branch.

The cases cover: creation binding the exact `goal_revision` (v1 lineage,
`list_by_goal` resolution in scope); canonical identity validation through
`maistro.interop` (#458) — blank/non-positive Goal revisions, blank scope,
owner-Agent, and Persona references are refused as typed
`CreativeBriefError`s, so Design Studio cannot mint a second Goal/Agent
identity universe; the shared-context invariant — landing-page, coupon, deck,
and video-script branches all receive the same Goal identity/revision, brief
version, accountable Agent, Persona, Design System, audience, and source
references, with only the declared channel requirement varying per branch;
versioned evolution — `revise` appends versions while `BriefRevision` carries
no Goal/scope/owner fields at all (compile-level negative control), historical
versions stay frozen and byte-identical for Runs that consumed them, and
`None` carries references forward so a Persona/Design System binding cannot be
silently dropped; single-lineage-per-Goal-revision (a second lineage for the
same revision conflicts; a new revision gets its own lineage); scope-keyed
reads with keyword-only, default-free scope arguments (#326) — a sibling
Workspace/Project gets `None`/not-found and cannot revise a lineage it cannot
see; version boundary refusals (non-tuple string collections, non-positive or
non-integer version numbers, malformed artifact requirements, empty/foreign
lineage members, discontiguous versions); `ArtifactProvenance.bind` refusing
blank Run/NodeRun/Attempt identities and `assert_matches_goal` refusing
provenance claimed against a foreign Goal revision; and JSON-safe
serializations of the shared context, published version, and provenance record.

The contract adds no scheduler, Run lifecycle, Goal store, or authorization
path: execution terminality stays owned by Run/NodeRun/Attempt, and the module
records provenance only. `InMemoryCreativeBriefStore` is an explicit reference
implementation; PostgreSQL remains authoritative for durable state.

No product, gate, threshold, or runtime authority changed. Full-suite CI
collection, formatting, and fresh exact-head review remain required before
merge.
