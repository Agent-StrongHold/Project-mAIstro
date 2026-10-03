---
inventory-delta:
  packages/maistro-core/tests: +50
---

Issue #120 (M4-B4, SPEC-283) adds the learning lifecycle: contradiction,
reinforcement, decay, supersession and consolidation for institutional knowledge,
preserving every prior version and evidence event.

`packages/maistro-core/src/maistro/memory/learnings/lifecycle.py` ships
`InMemoryLearningLifecycle` beside `InMemoryLearningStore` (the `SkillMutation`/
`LearningApproval` side-record pattern): an evidence ledger whose reinforcement,
contradiction, weakening, supersession and consolidation events must name the exact
Run or evaluation (AC-1, refused otherwise), a revision ledger that snapshots prior
state before every mutation so confidence/status updates never erase history (AC-2),
`decay` with floor and optional retirement plus `supersede` (AC-3), `consolidate`
producing a new derived record whose `ConsolidationRecord` names the exact source ids
with sources preserved (AC-4), and conflict detection/surfacing — `find_conflicts`
over active pairs and `LearningRetrieval.conflicts` carrying both sides alongside
retrieval (AC-5). `InMemoryLearningStore.get` is the id lookup the lifecycle
uses to track the store's canonical instance after a dedup hit; the store's dedup
probe, statuses and contracts are otherwise untouched.

`packages/maistro-core/tests/memory/learnings/test_lifecycle.py` (49 tests) pins each
acceptance axis behaviorally with a deterministic clock: exact Run/eval ids on
evidence and refusal of unattributed updates, revision chains and append-only
evidence ordering, silence-proportional decay with floor/retire-below and no
double-charging, supersession keeping the old row reachable in `list_all` but out of
retrieval, consolidation provenance and source preservation (including the
ordering trap where storing first would let the store's dedup overwrite a source in
place), and conflict registration/resolution/re-surfacing through retrieval.

The CI-repair round (#120) adds 16 lifecycle tests and 1 store test pinning the
degenerate paths the diff-coverage gate counted as partial arcs: the frozen
records' own constructor refusals (naive timestamps on revisions/conflicts/
consolidations/standing, out-of-range confidence, single-source and derived-as-source
consolidation records, evidence-driven evidence without a Run/evaluation link),
duplicated-id dedup in reinforce/retire, decay's naive-timestamp refusal, the
per-side org filter on conflict reads, a second distinct pair getting its own
conflict record, retrieval not surfacing conflicts outside the retrieved set, and
`InMemoryLearningStore.get` returning None for an unknown id.

Second CI-repair round: the spec was renumbered SPEC-282 → SPEC-283 (SPEC-282 was
already taken by the self-generated-curriculum spec, which the registry duplicate-ID
lint caught), its five acceptance bullets gained **AC-N** ids plus `ac-modules:`
anchors, and the five AC test classes gained matching `@pytest.mark.ac` markers so
the ac-state mandate proves each criterion. No tests were added or removed in this
round — the suite delta above is unchanged.
