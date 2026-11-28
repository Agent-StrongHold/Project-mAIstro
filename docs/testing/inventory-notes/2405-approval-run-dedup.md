---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
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

## Review rounds P1/P2 (+1 hive node ID; maistro-core count unchanged)

- **Review P1 (+1 hive):** `test_self_repair_invoker_advances_effect_identity_after_settlement`
  (`test_capabilities_wiring.py`) pins the wired auto-repair invoker's
  settled-generation advance — a post-settlement dispatch derives its heir
  effect key from the settled row's durable `invocation_id` instead of
  replaying the settled COMPLETED ledger row. Added in commit e9a043286c but
  never recorded in this ledger, which is the +1 drift the suite-inventory
  gate reported (expected 4778, collected 4779).
- **Review P2 (±0):**
  `test_ensure_capability_schema_reconciles_the_alembic_legacy_constraint`
  was strengthened in place — it now seeds two physical visits of one
  `(run_id, binding_id, effect_key)` before the reconciliation and asserts
  each row lands on its own physical NodeRun scope after it. No new node ID;
  the red-check is the collision itself (neutering the backfill makes the
  constraint swap die on `UniqueViolationError`).

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

## Local CI-gate reproduction at head 262a0653c4 (2026-11-28 validation round)

Executed with CI's exact arguments against the lane's pgvector/pg17
(auto2405-pg17, migrated to head): `ruff check .` and `ruff format --check .`
clean; `mypy --strict packages/maistro-core/src` clean (after
`uv sync --locked --all-extras` — the `--extra dev` venv cannot resolve
`maistro_bootstrap.cli`, an environment artifact CI never sees);
`check-suite-inventory.py`, `check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'`, `check-radon-baseline.py`,
`check-execution-lifecycles.py` and the interrogate floors for
maistro/graph/nodes + durable_runs + maistro all pass. Full batteries:
`packages/maistro-core/tests` 19135 passed / 302 skipped / 7 xfailed and
`packages/hive-conductor/backend/tests` 4740 passed / 39 skipped, both under
`coverage run --branch` with `MAISTRO_TEST_PG_DSN`; `tests/migrations` 174
passed on real PostgreSQL. `test_pg_approval_store.py` +
`test_pg_invocation_store.py` 27 passed and `test_pg_store_internals.py` 22
passed on the migrated server.

**The Coverage gate (diff half) is RED at this head — real, not a measurement
gap.** `scripts/check-diff-coverage.py coverage.xml --base 547eb70a` fails
three files whose changed lines the combined suite data never executes (the
core producer data here is a superset of CI's coverage-unit +
coverage-postgres producers; the hive producer data is a superset of CI's
server-less backend run + its PG legs):

- `packages/hive-conductor/backend/services/capabilities_wiring.py` — 64.9%
  of 57 changed lines. Uncovered: line 154 (the `_execute_auto_repair_effect`
  `TypeError` fail-closed guard for a non-action provider), lines 206–209
  (the `_MAX_EFFECT_GENERATIONS` cap refusing a further incident identity),
  lines 336–353 (the entire `load_pending` body — the durable pending-waits
  hydration that pages `list_hitl_paused`, filters `admission_source ==
  "self_repair"`, and maps resource → run_id). No hive test drives the wired
  hydration loader at all.
- `packages/maistro-core/src/maistro/capabilities/providers/self_repair.py`
  — 86.8% of 38 changed lines. Uncovered: 189 (`continue` skip in the
  hydration loop), 217 (`return None`), 220–221 (the `except Exception →
  logger.warning` fail-closed arm), 227 (`return None`). The dedup suite
  pins hydration gating in-memory but not these arms, and CI's
  coverage-postgres producer does not run `tests/capabilities/` beyond
  `test_backend_effect_context.py`, so these lines cannot join CI's
  coverage.xml through the current producer list.
- `packages/maistro-core/src/maistro/graph/nodes/infra_approval_action.py` —
  75.0% of 20 changed branch arcs (need 80%). Partial arcs at 174
  (`_effect_context is None`), 191 (empty `binding_id`), 203 (`authorized
  .binding_id != binding_id` mismatch), 209 (`registry is None`), 215
  (non-`InfraAction` provider) — each guard has one untaken outcome; the
  composition tests exercise the happy path plus revoked-Binding, not every
  fail-closed arm.

A repair round should add tests whose *execution* covers exactly these lines
(a hydration-loader test over seeded paused Runs; non-action-provider and
cap-exceeded invoker arms; the node's five guard arms) — no production change
is implied; the production seams themselves are verified live above.

**Environment traps that cost this round time, recorded to save the next one:**
running the whole `packages/maistro-core/tests` battery with BOTH
`MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set against a long-lived
shared database fails three tests that are green in CI's fresh service DB:
`persistence/test_pg_audit.py::test_real_postgres_two_org_scope_and_schema`
(asserts the alembic-036 nullable `audit_log.org_id`; the shipped
`pg_audit.py:49,122` store bootstrap creates the column `NOT NULL` when it
races the chain) and
`test_container_postgres.py::test_an_unmigrated_database_names_the_command_that_fixes_it`.
`persistence/test_schedule_winner_crash.py` subprocess workers also exit
silently on the drifted DB while passing on a fresh one. None is a branch
defect: this branch's only alembic change deletes
`074_canonical_event_projection.py`, and the same three files pass 50/50 on a
fresh chain-shaped database created for this round (`maistro_test2` on the
same server, alembic-upgraded, all previously-failing tests green). Repair
the shared DB with `ALTER TABLE audit_log ALTER COLUMN org_id DROP NOT NULL;`
and run audit/container_postgres suites before any suite that bootstraps the
store schema, or use the fresh `maistro_test2`.
