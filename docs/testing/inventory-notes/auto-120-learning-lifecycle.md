---
inventory-delta:
  packages/maistro-core/tests: +543
  packages/maistro-core/src: +850
---

Issue #120 (M4-B4, SPEC-282) adds the learning lifecycle: contradiction,
reinforcement, decay, supersession and consolidation for institutional knowledge,
preserving every prior version and evidence event.

`packages/maistro-core/src/maistro/memory/learnings/lifecycle.py` (+846) ships
`InMemoryLearningLifecycle` beside `InMemoryLearningStore` (the `SkillMutation`/
`LearningApproval` side-record pattern): an evidence ledger whose reinforcement,
contradiction, weakening, supersession and consolidation events must name the exact
Run or evaluation (AC-1, refused otherwise), a revision ledger that snapshots prior
state before every mutation so confidence/status updates never erase history (AC-2),
`decay` with floor and optional retirement plus `supersede` (AC-3), `consolidate`
producing a new derived record whose `ConsolidationRecord` names the exact source ids
with sources preserved (AC-4), and conflict detection/surfacing — `find_conflicts`
over active pairs and `LearningRetrieval.conflicts` carrying both sides alongside
retrieval (AC-5). `InMemoryLearningStore.get` (+17) is the id lookup the lifecycle
uses to track the store's canonical instance after a dedup hit; the store's dedup
probe, statuses and contracts are otherwise untouched.

`packages/maistro-core/tests/memory/learnings/test_lifecycle.py` (+543) pins each
acceptance axis behaviorally with a deterministic clock: exact Run/eval ids on
evidence and refusal of unattributed updates, revision chains and append-only
evidence ordering, silence-proportional decay with floor/retire-below and no
double-charging, supersession keeping the old row reachable in `list_all` but out of
retrieval, consolidation provenance and source preservation (including the
ordering trap where storing first would let the store's dedup overwrite a source in
place), and conflict registration/resolution/re-surfacing through retrieval.
