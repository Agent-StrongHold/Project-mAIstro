# Research Lab: post-convergence memory extension and #2310 integration audit

**Status:** Draft for review; planning and source audit, not an accepted ADR or implementation claim.  
**Base:** `develop` (inspected 2026-11-02).  
**Related:** #2310, #105, #804, #1046, #901, #904, #910; ADR-013, ADR-080, ADR-091, ADR-082226-5104, SPEC-241.

## Executive decision

Research Lab is a new Workspace product surface and a richer expression of **canonical memory**, not a second knowledge engine or architecture spine. It uses canonical Workspace/principal authorization, PostgreSQL durable memory, Graph → Run → NodeRun → Attempt, governed effects/approval/audit, retrieval, and the persistent Workspace Agent. No separate agent, scheduler, goal store, memory authority, or execution lifecycle is permitted.

## Product behavior and decisions

- **Topics:** first-class graph entities and mind-map roots, not exclusive storage scopes. One canonical proposition can connect to multiple topics without duplication.
- **Inputs:** autosaved, revision-preserving freeform notes (including lectures), source documents and media. Original authored text is immutable as historical evidence; later edits are revisions. Extract propositions, concepts, questions, and relationships with passage-level provenance. Hybrid processing: lightweight incremental extraction while typing; deeper reconciliation at checkpoints.
- **Epistemic distinctions:** a proposition is not a belief. Belief records who accepts a proposition in which context and when; explicit user endorsement must not be changed without review and acceptance. An approval of a graph edit does not itself endorse a proposition. Axioms/premises/conclusions are contextual roles, not mutually exclusive permanent entity types. Derivations capture joint premises, method and origin.
- **Truth assessment:** enum `SUPPORTED | REFUTED | DISPUTED | UNVERIFIED | CONTEXT_DEPENDENT` (context-dependent may eventually become a qualifier), plus separately calibrated probability of classification correctness. Keep retrieval weight, source reliability, contextual authority, logical validity, and user belief independent. Neither approval nor lecture authority makes a claim true.
- **Evidence:** signed support/opposition; explicit `CONFLICTS_WITH` relations. Preserve competing claims and evidence, automatically reassess best-supported interpretations; do not double-count shared origins or amplify cycles. Context matters: apparent conflicts may disappear after qualification.
- **Logic and provenance:** use established predicate/description logic, RDF/OWL semantic conventions, PROV-O, defeasible/argumentation frameworks where appropriate; these standards do not require a separate graph database. Track provenance for assertions, beliefs, derivations and edges. Conclusions can be derived without independent external evidence; unverified claims are not automatically axioms.
- **Time:** distinguish learned, recorded, valid, accepted and assessed times; version changes and support historical reconstruction, including shifting course-specific authority.
- **Sharing:** automatically link related knowledge within a Workspace. Simplify authorized sharing across same-user Workspaces without assuming common ACLs. Cross-owner sharing requires explicit permission. Live references default; independently versioned snapshots optional. Do not traverse another Workspace's private hot projection.
- **Retrieval:** traverse topic-connected, agent-authorized knowledge across permissible boundaries. Rank by semantic relevance with **exponential decay over weighted graph distance** (`R(d)=R0 exp(-lambda*d)`), using relationship-dependent nonnegative costs; handle multiple paths and cycles without unbounded amplification. This is retrieval relevance, never truth confidence.
- **Agent autonomy:** automatically extract, link, evaluate, and flag conflicts. Never silently revise a user's explicitly endorsed belief; present evidence for accept/reject/defer. Reassessment of evidence proceeds independently. Reuse canonical Goals/Runs, policy, and audit.
- **UI:** note editor, sources, interactive topic mind map, provenance/evidence inspection, belief review, temporal history, and research Goal controls. All substantive operations must have backend/API and agent access without UI-only authority.

## Current `develop` observations for #2310

The issue marks these modules `CONNECT / unreachable`: `maistro.memory.episodic.consolidation`, `maistro.memory.episodic.sharing`, `maistro.memory.learnings.approval`, `maistro.memory.learnings.promoter`, `maistro.memory.mutations`. They remain in `quality/reachability-baseline.json` and the `memory-advanced-retrieval` group in `quality/reachability-dispositions.json`.

`memory/episodic/consolidation.py` implements pure `consolidate()` producing `MergeProposal` and `ContradictionFlag`, `apply_merge()` / `apply_contradiction()` record transformations, and `run_batch()` accepting caller-provided persistence callbacks. The module does **not** itself construct or execute a canonical Graph/NodeRun or establish durable, governed writes. Its contradiction behavior subtracts a fixed memory **weight** delta from both sides; this is **not** Research Lab's evidence-based truth assessment.

`memory/working/dreaming.py` implements read-only `collect_candidates()` returning scoped memories, hypotheses, entities, co-occurrence relationships and clusters. It intentionally cannot write durable memory. Its documentation expects a Dreaming Run to promote candidates via authoritative stores. The actual production call path connecting these pieces has not been proven.

`docs/architecture/working-memory.md` establishes PostgreSQL as durable authority and the per-Workspace graph as a disposable projection, with no cross-Workspace traversal. ADR-091 separates persisted memory types from context assembly layers. The proposed Research Lab graph must therefore be durable canonical semantic records **projected into** hot graph/retrieval interfaces, not stored only in the disposable graph.

## #2310 proposed integration plan (not implemented in this PR)

1. Trace canonical Graph node registration, Run/NodeRun dispatch, Dreaming candidate collection, `EpisodicStore` write protocols, authorization, approvals, and event/audit identity. Record exact entrypoint-to-write call path and absent seams before changing code.
2. Implement a governed consolidation Graph with explicit candidate, proposal and apply stages. Use existing canonical scheduler/Goal/Run and store/effect contracts; no direct private worker, callback-only production persistence, or alternate authority.
3. Preserve scoped access, provenance, idempotent retries, review policy and atomic durable writes. Ensure duplicates and contradictions are not silently deleted or treated as truth; respect existing episodic semantics pending Research Lab's separate domain extension.
4. Connect or explicitly retire each of the five modules; ensure every intended module has a real reachable production caller rather than only test imports.
5. Verify with end-to-end Graph/NodeRun tests, real PostgreSQL persistence and restart recovery, workspace isolation, denial cases, idempotent retry, audit/correlation and gate results on the tested commit. Only then remove resolved entries from reachability baseline/dispositions.

### Acceptance criteria

- [ ] Each of the five #2310 modules has a documented canonical caller or explicit `RETIRE/replaced_by` disposition.
- [ ] Real production Graph Run exercises candidate collection → proposal → authorized durable apply.
- [ ] Workspace/user/global scope boundaries enforced; no unauthorized cross-Workspace graph traversal.
- [ ] Review, event/effect and audit paths use canonical authorities; retry does not duplicate mutations.
- [ ] PostgreSQL restart reconstructs committed memory and hot projections; no process-local fallback masquerades as durable success.
- [ ] Reachability and disposition gates pass on exact head; #2310 can be closed with linked evidence.

## Dependencies and sequencing

- **#2310 (M3/P1):** current memory lifecycle wiring. Most direct prerequisite for automated Research Lab maintenance.
- **#105 (M4):** retained observation/full-result log PostgreSQL durability; do not treat process-local or SQLite-only evidence as the production contract.
- **#804 (M3):** persistent Workspace Agent Goal reconciliation and restart-safe unattended work.
- **#1046:** Workspace product integration and authorization; **#901/#904/#910** research overlaps in retrieval, calibration, and autonomous acquisition.

Research Lab's semantic proposition/belief/evidence schema is **new product work** and is not an implicit acceptance criterion for #2310. Develop its contracts and UI in parallel, but defer production unattended maintenance and cross-Workspace promotion until the canonical dependencies are proven.

## Open engineering choices (not user-level blockers)

Select and benchmark evidence aggregation (dependency-aware bipolar argumentation / probabilistic methods), graph identity and deduplication, time/version schema, traversal attenuation, and calibrated evaluation. No ungrounded confidence percentages or fixed thresholds should be presented as validated.

## Verification limitations

This PR is documentation-only. Source and issue metadata were inspected on `develop`; no tests, PostgreSQL restart exercises, or full production call-path audit were run. Do not mark #2310 resolved based on this document.
