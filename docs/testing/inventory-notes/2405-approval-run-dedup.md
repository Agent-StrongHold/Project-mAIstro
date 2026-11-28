---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +32
---

# Self-repair approval wait: restart/replica convergence and reconstructible resume (#2405)

## Repair round 3: real-PostgreSQL closure (+7 maistro-core node IDs)

The prior round documented the audit's slice-4 real-kill/replay proofs as
unexecuted. This round executed them — separate OS processes sharing only a
migrated PostgreSQL (alembic to head), every store the shipped composition
wires (`PgRunStore`, `PgGraphContinuationStore` under
`CanonicalDurableRunStore`, `PgApprovalStore`, `PgBindingStore`,
`PgInvocationStore`) — and the execution exposed three real defects, each
fixed with a red/green oracle:

- **Alembic-first deployments could not create a DurableApproval at all.**
  Revision 043 keyed `uq_capability_approval_effect` on the physical visit;
  `ensure_capability_schema` added the `effect_scope` *column* but left the
  legacy *constraint*, while `PgApprovalStore.create` upserts on the scope
  key — every admission died on `InvalidColumnReferenceError`. The bootstrap
  now reconciles the constraint to the scope-keyed identity, guarded on the
  exact legacy definition (`test_ensure_capability_schema_reconciles_the_alembic_legacy_constraint`,
  plus the idempotency half; both in `test_pg_approval_store.py`).
- **The episode chain never moved the effect key.** Migration 034 makes
  `provenance.effect_key` one-Run-forever, so a post-settlement episode reusing
  the settled key could never admit (`ix_canonical_runs_effect` violation), and
  the same index racing a winner leaked a raw `UniqueViolationError` instead of
  `DuplicateOccurrence`. The key now moves with the chained token
  (`episode_effect_key`), the admitted identity is scope-digested
  (`incident_run_effect_key` — 034's index is global across Workspaces and the
  provider key deliberately is not), and `_occurrence_conflict` translates the
  effect-index refusal for Runs carrying both identities
  (`test_pg_store_internals.py` +2, both discrimination halves).
- **A replica re-entering the claimed Run before the winner published its
  first checkpoint crashed admission.** The continuation store's uniqueness is
  the fence; the loser now converges to the winner's parked wait (and still
  refuses when no wait appeared — the winner died pre-publication)
  (`test_continuation_collision_converges_to_the_winner_s_wait`).

Executed receipts (scratch driver outside the tree, fresh Workspaces per run,
`PROOF_JSON` per phase): admit→PAUSED with approval request; answer through
the shipped HITL door in P3 → QUEUED; fresh P4 resumes with exactly **one**
physical HTTP effect; fresh P5's second tick dispatches nothing; counts read
back 1 canonical Run / 1 DurableApproval / 1 Invocation. Restart: P1 dies
pre-approval, P2 hydrates from `list_hitl_paused` and reconciles to the SAME
Run. Two replicas race: one run_id, one Run, one Approval, survivor PAUSED.
Post-settlement: episode 1 admits with a new claim token and a different
effect key. Full battery green with `MAISTRO_TEST_PG_DSN` set: graph+runs
4659, hive 4739, capabilities 877.

## Round 1–2 coverage (+25 maistro-core, +2 hive node IDs)

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

All round 1–2 hand-written tests run on the in-memory spine (canonical
`InMemoryRunStore` + `CanonicalDurableRunStore` wrapper); none is skipped. The
interleaving coverage there is asyncio-concurrency, a scripted probe/insert
race stub, and simulated crash windows. Round 3 closes that gap: the audit's
real-kill/replay proofs (slice 4) are now executed against migrated
PostgreSQL in separate OS processes, with the receipts above. The corrected
front matter (the fence was missing, so this file's delta silently read as
none, and the +17 understated the registry-derived remainder) is why the
inventory gate drifted by the full +23 on the first validation round; rounds
2 (+2/+2 race-fence and recovery-ownership mutation oracles) and 3 (+7
real-PostgreSQL closure oracles) are recorded in the same ledger.
