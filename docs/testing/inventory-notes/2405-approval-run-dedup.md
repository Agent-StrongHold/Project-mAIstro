---
inventory-delta:
  packages/maistro-core/tests: +25
  packages/hive-conductor/backend/tests: +2
---

# Self-repair approval wait: restart/replica convergence and reconstructible resume (#2405)

Twenty-five maistro-core node IDs and two hive-conductor node IDs, pinning the
coordination contracts the #2405 audits proved broken:

- **One incident, one Run.** Nineteen node IDs in
  `packages/maistro-core/tests/capabilities/test_self_repair_incident_dedup.py`,
  covering stable incident identity (workspace/resource/action/request digest,
  no `id(proposal)` — asserted across *distinct* proposal objects, so the
  object-id derivation cannot coincide by allocation), an atomic same-incident
  claim through the existing occurrence-claim unique index, the
  `DuplicateOccurrence` loser reconciling to the winner (one insert, no
  replacement Run, no chained claim for a live winner — deterministic stub,
  plus a forced two-probe interleaving whose fence counter proves the pass did
  not come from check-then-insert), crash-window re-entry of the claimed Run,
  refusal of a claim held for a different effect, distinct incidents never
  aliasing, terminal settlement chaining the next episode, and hydration
  gating a fresh provider/replica (with hydration failure failing the whole
  cycle closed).
- **Approved work resumes.** The registered `infra.approval_gated_action`
  kind composes from durable facts plus Container-owned authorities: an
  answered pause resumes through `resume_durable_graph` with exactly one
  physical effect, a second tick is inert, missing authorities fail
  composition closed, and a revoked Binding fails the resume closed with zero
  dispatch.
- **The recovery cadence owns the source — and only that source.** Two node
  IDs in `packages/hive-conductor/backend/tests/test_self_repair_recovery.py`:
  the shipped tick hands the canonical recovery seams the self_repair
  prefilter, predicate, stores and canonical Event sink (the wake seam owns
  through the predicate alone), and a stranded crash-window Run is recovered
  end-to-end while a foreign-sourced QUEUED Run stays untouched and the tick
  stays idempotent. Deleting `_owned` fails both.

The remaining six maistro-core node IDs are not hand-written tests: they are
parametrize expansions over production registries this change extends, so
they move with the source, not with a test edit.

- `tests/graph/nodes/test_node_composition.py` +3: the resolver-composition
  contract now enumerates the newly registered `infra.approval_gated_action`
  kind (bare resolver refuses it, a wired resolver hands it its exact
  authorities, every declared authority is supplyable).
- `tests/graph/nodes/test_container_node_composition.py` +2: the new
  `capability_registry -> capabilities` authority-mapping row is enumerated by
  two parametrized composition tests (deleting the Container resolver's
  registry authority fails both).
- `tests/graph/nodes/test_production_registration_universe.py` +1: the
  registry-binds-identity test now covers the new node registration.
- `tests/tasks/test_admission_codec.py` ±0: three generation-id parametrize
  values were reseeded (different UUID fixtures), so three IDs left and three
  arrived — net zero, listed only because the gate counts identities, not
  intent.

All hand-written tests run on the in-memory spine (canonical
`InMemoryRunStore` + `CanonicalDurableRunStore` wrapper); none is skipped. The
interleaving coverage is asyncio-concurrency, a scripted probe/insert race
stub, and simulated crash windows — not real multi-process PostgreSQL kills —
the audit's real-kill/replay proofs (slice 4) remain unexecuted here and are
not claimed. The corrected front matter (the fence was missing, so this
file's delta silently read as none, and the +17 understated the
registry-derived remainder) is why the inventory gate drifted by the full +23
on the first validation round; this round's +2/+2 are the race-fence and
recovery-ownership mutation-oracle tests the audit requires.
