---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair round e1e7: codec verified against live PostgreSQL; one structural gate remains

## Frozen scope and reconciliation

This round processes only issue #1893 in `/home/dev/Git/wt/auto-1893`
(branch `auto-1893`), starting at the exact assigned head
`a5f9e32e28c3d96afe198124318779b085494c7d`, develop base
`d592654aca614fb74467487542693c46b3aa30fb`. The worktree arrived clean; no
earlier uncommitted work was present. `origin/develop` was fetched (read-only)
and has not moved from the assigned base. No production activation, wiring,
SQL mutation, HTTP mapping, queue change, grant, or gate edit is made. The
canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model is untouched.

No tests are added in this round (`inventory-delta` is 0); this note records
executed evidence only. Nothing here closes the issue or authorizes merge.

## Prior findings checked against the current head

1. **"admission_codec.py:290-291 emits task_id=None while preserving a bound
   run_id" — already repaired before this round** by commit `c1351bffe`
   ("preserve v2 admission binding storage identity"). Current lines 291-292
   emit `task_id = binding.receipt_id` when bound, and
   `AdmissionRecordV2.__post_init__` enforces
   `binding.receipt_id == envelope.receipt_id`, so the encoder can never emit
   a shape migration 055's `ck_task_idempotency_v2_identity` rejects.
2. **"test_admission_codec.py:126-131 accepts the invalid mapping" — already
   repaired**: the round-trip test now independently asserts the storage
   contract (`row["task_id"] == "rcpt-1"` iff bound) instead of trusting
   encode/decode agreement.
3. **"check-ratchet-provenance.py exits 1 on NEW unauthorized
   maistro.runs.admission_identity / maistro.tasks.admission_codec
   reachability/disposition debt" — reproduced, and structural**: see below.

## Executed validation (this round, by this worker)

Environment: native PostgreSQL 18.6 on 127.0.0.1:5432 (Docker daemon down;
native server used instead), disposable database `maistro_b2_26898`, created
for this round and dropped after. Migrated with the real chain:
`DATABASE_URL=... uv run alembic upgrade head` — reached head through
`055_task_admission_generations` (#1892). The live CHECK constraint was read
back from `pg_constraint` and requires exactly: v2 rows carry both binding
columns with `task_id = receipt_id`, or neither.

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py -q`
  with `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` on that DB:
  **131 passed, 0 skipped** — including the three parametrizations of
  `test_raw_and_production_pool_codecs_read_identical_text_snapshots`
  (raw asyncpg pool vs production `_register_json_codecs` pool, same server
  identity asserted, distinct backend PIDs recorded). Prior rounds reported
  this test skipped; this round supplies the real-database evidence the issue
  demands. Without the DB env, the same file passes with the PG leg skipped.
- Driver battery reproduced: ruff check/format clean; focused
  `test_root_admission_identity.py + test_admission_codec.py` 201 passed,
  3 skipped (PG leg); `check-suite-inventory.py --suite
  packages/maistro-core/tests` ok.
- Injected boundary on the live DB (codec-driven INSERTs of fully valid v2
  rows): the encoder's bound output persists (1 row); tampered
  `task_id != receipt_id`, one-sided `run_id`, and one-sided `task_id` are
  each rejected by `ck_task_idempotency_v2_identity`. The pre-fix defect
  class cannot be persisted by the current encoder.
- Canonical mypy over all seven package src trees: "Success: no issues found
  in 878 source files".
- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact arguments): 1323 reviewed
  identities -> 1323 findings, exit 0. **The vulture ledger needs no
  amendment this round**; none was made.
- `check-shipped-surface-truth.py`: ok. `check-convergence-matrix.py`: ok
  (52 subsystems, 171 unreachable attributed). `check-promotion-surface.py`:
  ok. `check-reachability.py`: ok (171 unreachable, candidate ledger matches
  the scan). `check-reachability-dispositions.py`: ok (50 groups disposition
  all 171). Root self-checks `tests/test_check_reachability*.py`,
  `tests/test_check_ratchet_provenance.py`,
  `tests/test_reachability_{scanner,source_universe}.py` with
  `RATCHET_BASE_REV=origin/develop`: 66 passed. Full-repo
  `check-suite-inventory.py`: ok (17 suites, 30848 node IDs).

## The one remaining CI failure is structural, not a code defect

`exact-debt-ledger` (vulture-ratchet.yml) fails at its first step,
`check-ratchet-provenance.py`, whose sub-gates
`check-reachability-provenance.py` and
`check-reachability-dispositions-provenance.py` both report:

- `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`:
  NEW unreachable module/disposition absent from the trusted base and not
  previously authorized (169 -> 171 unreachable).

Both modules are deliberately production-unreachable: B2's scope forbids
activation, and the C consumer leaf is their future caller. The provenance
gates read `quality/ratchet-authorizations.json` from the merge base
(`ratchet_provenance.load_authorizations`, base `d592654aca61`), which grants
neither module — verified against `origin/develop` after fetch. This is the
repository's documented two-merge rule: a grant never authorizes the change
that introduces it, so no ledger state on this branch can pass (removing the
candidate baseline rows or the disposition only fails the sibling required
gates instead — `check-reachability.py` and
`check-reachability-dispositions.py` each demand the banking this branch
already carries). Adding the grants on this branch is both ineffective
(base-read) and outside this lane's grant-edit authority.

Unblocking paths (owner actions, both outside this lane): land a grant PR
for these two reachability identities on `develop` first, then re-evaluate
this branch; or land the #1845 C consumer leaf, which makes both modules
production-reachable and lets the baseline rows be pruned. The
`test: failure` line in the lane brief could not be attributed to branch
content: every locally runnable slice of the ci.yml `test` job that this
branch can affect passes (root reachability/ratchet self-checks above,
full-repo suite inventory); the ci.yml suites for server/turing/design and
the frontends are untouched by this branch's diff (maistro-core sources and
tests, docs, quality ledgers only).

## Verdict recorded for this round

Issue-level B2 acceptance evidence is established (typed codec, ten
prospective contracts plus regressions, live-DB durability, no activation).
PR-level mergeability remains blocked by `exact-debt-ledger` for the
structural reason above; this is COORDINATION_REQUIRED per the issue, not an
in-lane repair item.
