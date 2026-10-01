# MAIstro SPEC Agent Index

Progressive-disclosure entry point for the complete SPEC corpus.

**Coverage:** 213/213 SPEC files indexed by exact filename, 0 missing.

## How to use

1. Start with the canonical August specs for architecture/execution work.
2. Open correctness-hardening specs for a specific invariant.
3. Use older sequential/legacy specs only for requirements that have not been replaced.
4. Open the full SPEC only when implementation detail, ACs, tests, or rationale are needed.
5. Never implement an older spec literally when it conflicts with a newer accepted ADR/SPEC.

## Canonical implementation spine

For M1 architecture convergence, start with:

- [SPEC-081226-9944](../../specs/SPEC-081226-9944-canonical-product-hierarchy-and-ownership.md) — product hierarchy/ownership
- [SPEC-081426-b1d3](../../specs/SPEC-081426-b1d3-project-scope-tree.md) — Project scope tree
- [SPEC-081226-6e34](../../specs/SPEC-081226-6e34-hierarchical-permissions.md) — scoped grants/deny-wins
- [SPEC-081226-69ee](../../specs/SPEC-081226-69ee-graph-node-execution-model.md) — Graph/Node model
- [SPEC-081226-a66b](../../specs/SPEC-081226-a66b-run-noderun-attempt-lifecycle.md) — canonical lifecycle
- [SPEC-081426-1f7c](../../specs/SPEC-081426-1f7c-execution-runtime-contract.md) — physical execution mechanics
- [SPEC-081226-6b46](../../specs/SPEC-081226-6b46-capability-provider-binding-invocation.md) — capability fulfillment/effects
- [SPEC-081226-7248](../../specs/SPEC-081226-7248-event-checkpoint-model.md) — durable events/recovery
- [SPEC-081226-bb3a](../../specs/SPEC-081226-bb3a-template-object-provenance-semantics.md) — reusable definitions/provenance
- [SPEC-081226-e626](../../specs/SPEC-081226-e626-persona-surface-model.md) — Persona
- [SPEC-081226-034b](../../specs/SPEC-081226-034b-package-ownership-dependency-direction.md) — package ownership

These are mostly **AC Defined**, not Implemented. That is important: they are the current acceptance checklist for convergence, not evidence that convergence is finished.

## M1-critical hardening specs

Particularly important follow-ups include:

- parked Run resume without repeating effects: SPEC-082926-a44e
- schedule consumer node fidelity: SPEC-082926-d90e
- typed Attempt output: SPEC-082926-2844
- HITL timeout/cancellation: SPEC-083026-73c1
- execution correlation: SPEC-083026-20b2
- record producer provenance: SPEC-083026-b2b5
- canonical Run consumer and Graph continuation decisions reflected in the late-August ADR/SPEC family
- maistro-server Task backend retirement: SPEC-226

## M2 security/identity focus

- SPEC-081226-6e34 scoped authorization
- SPEC-245/246/247/248 authorization/elevation/RLPHD, reconciled to the scoped model
- SPEC-183 OAuth rewritten to canonical principals
- SPEC-082126-3c9d PII normalization
- SPEC-082126-5f6a Warden L3 failure semantics
- SPEC-082126-7a31 tool-argument resource limits
- SPEC-082226-2a10 resource security floors
- SPEC-090326-b7e2 browser outbound policy
- SPEC-092526-c41d Warden admission of RSI-harvested content
- SPEC-190 sandbox substrate after ADR-093 floor reconciliation
- crypto-bound approvals from ADR-090726-9a4e need a current implementation SPEC/evidence pass

## M3/M4 likely focus

- observability completion: SPEC-228, SPEC-070226-2b70
- durable memory dynamics and retrieval: SPEC-240-250 plus August/September durable-memory specs
- ConfigStore: SPEC-062226-fb23
- deployment/backup rewrite: SPEC-070226-fbe3
- Canvas/Design Studio cutover: SPEC-070226-8239, SPEC-219-229
- Evolve/RSI fidelity and candidate promotion: SPEC-202/207/062926-8ec5/070126-9d37 and related Evolve proposals
- foreign harness portability only after canonical Binding/Invocation rewrite

## Major stale-spec traps

Do not implement these literally:

- SPEC-010 SQLite singleton
- SPEC-013 1kHz reactor
- SPEC-015 Hyperagent runtime
- SPEC-175/177/181/226 Task-era execution semantics
- SPEC-182 direct A2A broker
- SPEC-201 Builders-owned runtime
- SPEC-211 Task lanes
- SPEC-251 outbound delivery gateway
- SPEC-254 shadow git
- SPEC-255 parallel git-wave fan-in
- SPEC-256 TaskCheckpoint replay
- SPEC-230 expand/contract schema compatibility
- old DID/VC/seed specs as mandatory baseline identity

Useful requirements from those specs should move into current canonical owners, then the obsolete path should be deleted.

## Pre-1.0 rule

Parity/evidence protects useful behavior, not obsolete architecture.

```text
build canonical model
→ move useful behavior
→ change real callers
→ delete obsolete system
```

Do not add compatibility branches merely to preserve an unshipped pre-1.0 API, schema, executor, identity model, or product surface.

## Index groups

- [Legacy / early specs](legacy-early/README.md)
- [Mid-2026 memory/design/evolve/quality](mid-2026/README.md)
- [July architecture](july-architecture/README.md)
- [Canonical August architecture](canonical-august/README.md)
- [Late-August / September correctness hardening](correctness-hardening/README.md)
- [Sequential 160-197](sequential-160-197/README.md)
- [Sequential 200-234](sequential-200-234/README.md)
- [Sequential 240-281](sequential-240-281/README.md)

## Lifecycle interpretation

- **Implemented** should mean the narrow SPEC contract is directly evidenced.
- **AC Defined** means acceptance criteria exist and are mapped, not that the behavior is complete.
- **Accepted** may mean implemented primitives exist but strict completion/reachability evidence is incomplete.
- **Proposed** is not implementation authority unless an accepted governing decision independently requires the same behavior.
- **Superseded/Deprecated** specs are historical only.

Production reachability remains stronger evidence than module/test existence.
