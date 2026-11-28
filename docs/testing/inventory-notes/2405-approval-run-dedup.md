---
inventory-delta:
  packages/maistro-core/tests: +23
---

# Self-repair approval wait: restart/replica convergence and reconstructible resume (#2405)

Twenty-three maistro-core node IDs across a new file and four source-derived
parametrize expansions, pinning the two coordination contracts the #2405 audits
proved broken:

- **One incident, one Run.** Seventeen node IDs in a new
  `packages/maistro-core/tests/capabilities/test_self_repair_incident_dedup.py`,
  covering stable incident identity (workspace/resource/action/request digest,
  no `id(proposal)`), an atomic same-incident claim through the existing
  occurrence-claim unique index (`DuplicateOccurrence` losers reconcile to the
  winner), crash-window re-entry of the claimed Run, refusal of a claim held
  for a different effect, distinct incidents never aliasing, terminal
  settlement chaining the next episode, and hydration gating a fresh
  provider/replica (with hydration failure failing the whole cycle closed).
- **Approved work resumes.** The registered `infra.approval_gated_action`
  kind composes from durable facts plus Container-owned authorities: an
  answered pause resumes through `resume_durable_graph` with exactly one
  physical effect, a second tick is inert, missing authorities fail
  composition closed, and a revoked Binding fails the resume closed with zero
  dispatch.

The remaining six node IDs are not hand-written tests: they are parametrize
expansions over production registries this change extends, so they move with
the source, not with a test edit.

- `tests/graph/nodes/test_node_composition.py` +3: the resolver-composition
  contract now enumerates the newly registered `infra.approval_gated_action`
  kind (bare resolver refuses it, a wired resolver hands it its exact
  authorities, every declared authority is supplyable).
- `tests/graph/nodes/test_container_node_composition.py` +2: the new
  `capability_registry -> capabilities` authority-mapping row is enumerated by
  two parametrized composition tests, not zero as this note previously
  claimed.
- `tests/graph/nodes/test_production_registration_universe.py` +1: the
  registry-binds-identity test now covers the new node registration.
- `tests/tasks/test_admission_codec.py` ±0: three generation-id parametrize
  values were reseeded (different UUID fixtures), so three IDs left and three
  arrived — net zero, listed only because the gate counts identities, not
  intent.

All seventeen hand-written tests run on the in-memory spine (canonical
`InMemoryRunStore` + `CanonicalDurableRunStore` wrapper); none is skipped. The
interleaving coverage is asyncio-concurrency and simulated crash windows, not
real multi-process PostgreSQL kills — the audit's real-kill/replay proofs
(slice 4) remain unexecuted here and are not claimed. The corrected front
matter (the fence was missing, so this file's delta silently read as none, and
the +17 understated the registry-derived remainder) is why the inventory gate
drifted by the full +23 on the previous validation round.
