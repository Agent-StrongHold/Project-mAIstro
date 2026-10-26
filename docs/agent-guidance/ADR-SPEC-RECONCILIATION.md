# ADR ↔ SPEC Cross-Corpus Reconciliation

**Audit coverage** (exact-filename accounting against this branch's tree)

- ADR decision files (`docs/adr/*.md`, excluding `ADR-INDEX.md`, `ADR-000-template.md`, `DECISION-BACKLOG.md`, `OUT-OF-SCOPE.md`): **215 tracked; 200 domain-indexed**
- SPEC files (`docs/specs/*.md`, excluding `README.md`): **228 tracked; 213 domain-indexed**
- The audit snapshot itself covered 200/200 ADR decision files and 213/213 SPEC files with 0 missing. Fifteen ADRs and fifteen SPECs landed on `develop` after that snapshot (all present at this branch's base), so the corpus outgrew the audit as written. They are accounted for — enumerated with their verbatim front-matter status under **Post-snapshot arrivals** below — but are not yet folded into their domain indexes. Folding them in is the immediate next action before any "fully indexed" claim is restored.

## Highest-priority finding: canonical architecture is under-evidenced

The eleven canonical August architecture SPECs are the current implementation spine:

- SPEC-081226-034b
- SPEC-081226-69ee
- SPEC-081226-6b46
- SPEC-081226-6e34
- SPEC-081226-7248
- SPEC-081226-9944
- SPEC-081226-a66b
- SPEC-081226-bb3a
- SPEC-081226-e626
- SPEC-081426-1f7c
- SPEC-081426-b1d3

Ten currently declare `tests: []`. SPEC-081226-bb3a binds only one test.

This does **not** mean the implementation has no tests. The repository contains substantial later tests for Run/NodeRun/Attempt, durable Graph execution, scheduling, HITL, fencing, provenance, authorization, and capability behavior. It means the canonical SPEC lifecycle/evidence records do not yet bind those tests.

### Next action

Perform an **AC-by-AC evidence binding pass** on these eleven SPECs:

1. For each AC, inspect the named `ac-modules` anchor.
2. Find the direct behavioral/conformance tests proving the criterion.
3. Add those tests to the SPEC's `tests:` evidence.
4. Mark criteria that are implemented-but-unreachable separately from genuinely missing behavior.
5. Create focused implementation issues only for the remaining real gaps.
6. Promote lifecycle status only after strict evidence and production reachability justify it.

This should happen before broad new M1 implementation work because it will distinguish:
- already-built but undocumented/evidence-unbound architecture;
- reachable but incompletely tested architecture;
- genuinely missing architecture;
- obsolete duplicate paths that should simply be deleted.

## M1 priority

### P0: canonical execution authority

- SPEC-081226-a66b Run/NodeRun/Attempt
- SPEC-081226-69ee Graph/Node execution
- SPEC-081426-1f7c ExecutionRuntime
- SPEC-081226-7248 durable Event/recovery
- SPEC-082926-a44e parked-Run resume
- SPEC-082926-d90e schedule consumer fidelity
- SPEC-083026-73c1 HITL timeout/cancel
- SPEC-226 maistro-server Task-backend retirement

Success condition: one post-admission lifecycle and one physical-execution authority; old Task/GraphRun/Builders/Hive executors are projections or deleted.

### P1: canonical ownership

- SPEC-081226-9944 hierarchy/ownership
- SPEC-081426-b1d3 Project tree
- SPEC-081226-bb3a Templates/provenance
- SPEC-081226-e626 Persona
- SPEC-081226-034b package ownership

Success condition: every durable object has one owner/scope and no compatibility facade acts as a second authority.

### P1: capability fulfillment

- SPEC-081226-6b46 Provider/Binding/Invocation
- SPEC-222/270 credential selection
- renderer/harness/model/tool specs migrated to the same seam
- SPEC-082226-4478/ADR equivalent one governed tool surface

Success condition: specialized/external effects have one authorized fulfillment path with durable Invocation evidence.

## M2 priority

- SPEC-081226-6e34 scoped authorization
- SPEC-245/246/247/248 reconciled to scoped grants
- SPEC-183 canonical-principal OAuth
- current web/session security
- SPEC-190 sandbox floor
- Warden/Sentinel boundary specs
- ADR-090726-9a4e crypto-bound approval implementation/evidence
- canonical Workspace identity and stable Workspace Agent

## M3/M4 priority

- observability closure and replay/sensitivity
- memory dynamics/retrieval/context safety
- ConfigStore
- Canvas/Design Studio cutover
- deployment/backup current-schema policy
- Evolve/RSI candidate fidelity/promotion
- foreign harness portability after capability convergence

## Specs that should not drive new implementation as written

Legacy requirements may be harvested, but these mechanisms are stale or deprecated:

- SPEC-008 direct A2A networking
- SPEC-010 SQLite singleton
- SPEC-013 reactor
- SPEC-015 Hyperagent runtime
- SPEC-175/177/181 Task/legacy graph bridges
- SPEC-182 old A2A broker
- SPEC-201 Builders runtime
- SPEC-211 lane-based Task scheduling
- SPEC-230 expand/contract DB compatibility
- SPEC-251 delivery gateway
- SPEC-254 shadow git
- SPEC-255 parallel git-wave fan-in
- SPEC-256 Task checkpoint replay

## Pre-1.0 interpretation

When a current canonical spec and an older compatibility-oriented spec conflict, prefer the canonical architecture and delete the obsolete path after useful behavior is migrated.

No pre-1.0 requirement gets architectural weight merely because it preserves an old unshipped interface.

## Post-snapshot arrivals (accounted, pending domain-index folding)

These files exist in `docs/adr/` / `docs/specs/` but have no domain-index entry yet. Each entry cites
only the file's own front matter; statuses are recorded verbatim and no lifecycle claim is made here.

ADR decision files (15):

- [ADR-092926-7a01](../adr/ADR-092926-7a01-closed-loop-design-process.md) — status: Proposed
- [ADR-093026-7a90](../adr/ADR-093026-7a90-design-process-is-a-first-class-object-graph.md) — status: Proposed
- [ADR-100126-5445](../adr/ADR-100126-5445-a-learning-promotes-on-evidence-not-on-hits.md) — status: Accepted
- [ADR-100126-8c2d](../adr/ADR-100126-8c2d-validated-collective-learning.md) — status: Proposed
- [ADR-100126-a9c4](../adr/ADR-100126-a9c4-one-governed-promotion-contract.md) — status: Accepted
- [ADR-100126-b118](../adr/ADR-100126-b118-dag-execution-budget-policy.md) — status: Proposed
- [ADR-100126-f9d6](../adr/ADR-100126-f9d6-engine-lifecycle-gates-health-ready.md) — status: Accepted
- [ADR-100526-9c55](../adr/ADR-100526-9c55-extension-contract-versioning-and-deprecation-policy.md) — status: Implemented
- [ADR-100526-be49](../adr/ADR-100526-be49-connector-source-sdk.md) — status: Proposed
- [ADR-100826-c0e1](../adr/ADR-100826-c0e1-coin-ledger-billing-identity.md) — status: Accepted
- [ADR-101726-e4bb](../adr/ADR-101726-e4bb-verification-aware-execution-contracts.md) — status: Proposed
- [ADR-101826-2a63](../adr/ADR-101826-2a63-biscuit-verification-adapter.md) — status: Proposed
- [ADR-103](../adr/ADR-103-knowledge-stage-ladder.md) — status: Accepted
- [ADR-104](../adr/ADR-104-extension-context-least-authority.md) — status: Accepted
- [ADR-105](../adr/ADR-105-provider-adapter-sdk.md) — status: Accepted

SPEC files (15):

- [SPEC-092826-a774](../specs/SPEC-092826-a774-creative-brief-contract.md) — status: AC
- [SPEC-092826-a780](../specs/SPEC-092826-a780-versioned-creative-artifact-state.md) — status: AC
- [SPEC-092926-7a01](../specs/SPEC-092926-7a01-closed-loop-design-process.md) — status: Proposed
- [SPEC-092926-7a02](../specs/SPEC-092926-7a02-closed-loop-design-process-contract.md) — status: Proposed
- [SPEC-093026-7a90](../specs/SPEC-093026-7a90-closed-loop-design-process-contract.md) — status: Proposed
- [SPEC-100126-5445](../specs/SPEC-100126-5445-learning-epistemics.md) — status: Tests
- [SPEC-100126-a9c4](../specs/SPEC-100126-a9c4-canonical-promotion-contract.md) — status: AC
- [SPEC-100126-b779](../specs/SPEC-100126-b779-cross-artifact-consistency-evaluation.md) — status: AC
- [SPEC-100126-c041](../specs/SPEC-100126-c041-workspace-cutover-phase-0-contract.md) — status: Proposed
- [SPEC-100426-b103](../specs/SPEC-100426-b103-knowledge-stage-ladder.md) — status: Accepted
- [SPEC-100826-c0e1](../specs/SPEC-100826-c0e1-coin-ledger-billing-identity.md) — status: AC
- [SPEC-102426-976a](../specs/SPEC-102426-976a-extension-telemetry-attribution.md) — status: Accepted
- [SPEC-282](../specs/SPEC-282-self-generated-curriculum.md) — status: Proposed
- [SPEC-283](../specs/SPEC-283-learning-lifecycle.md) — status: Accepted
- [SPEC-284](../specs/SPEC-284-provider-adapter-sdk.md) — status: Implemented
