# Issue #13 — `exact-debt-ledger` repair round: the failure is inherited from `develop`

Job `1be05898bfe34fce8f507465e09b7795` (lane L13, phase `repair`), branch
`auto-13`, starting HEAD `c83376b9f8f77f485e3463ee6993d2264b2e7659`, develop
base `e20e9f52ea94b393184f210cc9379f9f693f13d0`.

Every claim below was re-derived in this round from the tree and from the
assigned base. No earlier verification claim was assumed; the previous note in
[`inventory-notes/13-one-execution-universe.md`](inventory-notes/13-one-execution-universe.md)
reached the same conclusion, and this round confirms it with a measurement that
note did not have: **the same gate fails on the base tree, byte for byte.**

## 1. What the assigned gate actually executes

`.github/workflows/vulture-ratchet.yml` job `exact-debt-ledger` runs three
steps, in order, and stops at the first failure:

1. `scripts/check-ratchet-provenance.py` — the trusted-base wrapper inventory,
   which among others executes `check-reachability-provenance.py`;
2. `scripts/check-shipped-surface-truth.py`;
3. `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
   --exclude '*/third_party/*'`.

Step 1 fails, so step 3 — the vulture per-identity ledger the lane brief names
— **never executed in CI**. Running all three here separates the two:
the vulture ledger is green and the failure is the reachability ratchet.

## 2. Re-derived measurement at this head

| command | result |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **rc=0** — 1326 reviewed identities → 1326 findings, `unclassified: 0`, `never_allowlist: 0` |
| `uv run python scripts/check-shipped-surface-truth.py` | **rc=0** — "Shipped-surface truth matrix is complete." |
| `uv run python scripts/check-ratchet-provenance.py` | **rc=1** — see below |

```
FAIL: reachability ratchet moved away from trusted state
  - maistro.runs.admission_identity: NEW unreachable module absent from trusted base and not previously authorized
  - maistro.runs.admission_identity: current unreachable module missing from candidate baseline
FAIL: ratchet provenance inventory is incomplete
  - check-reachability-provenance.py: trusted-base gate returned 1
```

There is no vulture work in this round: no unbanked identity, no identity the
scan no longer produces. `git diff --numstat origin/develop -- quality/` is
empty, so this branch has not touched `quality/vulture-baseline.json`,
`quality/reachability-baseline.json` or `quality/ratchet-authorizations.json` at
all. The lane's ledger-amendment exception has nothing to amend.

## 3. The failure predates this branch — measured, not inferred

`maistro.runs.admission_identity` (`packages/maistro-core/src/maistro/runs/admission_identity.py`,
520 lines, "inactive contract leaf") reached `develop` through PR #1936
(`auto-1851`) with no importer. This branch only merged that state.

Reproduction on the base itself, using a `git archive` of the base commit
(no worktree state touched):

```
$ git archive e20e9f52ea94 | tar -x -C /tmp/base13
$ uv run python /tmp/base13/scripts/check-reachability.py
1417 production modules, 169 unreachable from any entry point
1 module(s) are NEWLY UNREACHABLE:
  maistro.runs.admission_identity  (maistro.runs.admission_identity)
```

and the set difference between the base scan and the base ledger:

```
scan 169  ledger 168
scan-ledger ['maistro.runs.admission_identity']
ledger-scan []
```

The base ledger is *exactly* the base scan minus that one module, at the same
1417-module universe this branch reports. The reachability floor is therefore
already violated on `develop` before this branch contributes anything.

The branch diff is not capable of moving the import graph either:

```
$ git diff --stat origin/develop HEAD
 .../inventory-notes/13-audit-log-schema-bootstrap.md |  71 ++
 .../inventory-notes/13-one-execution-universe.md     | 162 ++
 packages/maistro-core/src/maistro/persistence/pg_audit.py | 62 +-
 packages/maistro-core/tests/events/test_container_pg_durable_events.py | 60 ++
 packages/maistro-core/tests/persistence/test_pg_audit.py | 44 +-
 packages/maistro-core/tests/test_container_wiring.py | 19 +-
 uv.lock                                             | 390 ++++++---
```

No `maistro/runs/**` file, no `maistro/container.py` wiring edge, no entry
point. The same three root tests fail here for the same reason:

```
$ uv run pytest tests/test_reachability_baseline_identity.py tests/test_check_reachability.py -q
3 failed, 36 passed
::error title=New unreachable modules::maistro.runs.admission_identity
```

## 4. Why this cannot be repaired from a topic branch

- `scripts/ratchet_provenance.py:load_authorizations` reads
  `quality/ratchet-authorizations.json` **from the merge base**. A grant added
  by this change cannot authorize this change ("Authorizing a floor-raise is
  now two merges -- the grant, then the regression it permits"). At this head
  the base file has **zero** entries mentioning `admission_identity`, and this
  branch's copy is identical to `develop`'s.
- Adding the row to `quality/reachability-baseline.json` alone does not change
  the outcome (bullet 1 still fails, and the ledger's own header states the list
  "can only shrink"), and banking without a landed grant is precisely the
  "banking is not authorizing" case the repo documents.
- The other escape valves are all self-suppression: a fake caller or keep-alive
  import (prohibited by the leaf's own issue), a source-universe exclusion in
  `check-reachability.py`, or a `--min-confidence`/allowlist edit. Each would
  hide an unreachable module rather than make it reachable, and each is a gate
  weakening this lane may not perform.
- Genuinely wiring the leaf — a root-admission backend that consumes
  `AdmissionTicket`/`AdmissionRecordV2` and fences leases inside its own
  transaction — is the #1845/#1851 integration, not issue #13's work, and it
  cannot be improvised inside a CI-repair round: it would put unreviewed
  admission/fencing semantics on the canonical `Goal -> Graph -> Run -> NodeRun
  -> Attempt` path.

So this round deliberately makes **no** change to source, ledgers or grants,
and records the blocker instead: deleting, renaming or wiring another lane's
reviewed contract leaf from here would be less honest than leaving the gate red
with the reason on record.

## 5. What this round did re-verify about the branch itself

The branch's own production change (the `audit_log` bootstrap in
`maistro/persistence/pg_audit.py`, commit `c83376b9f`) was re-checked against a
real server rather than a fake pool — a fresh database that has never run the
migration chain (`postgres:17`, container `auto-13-pg17`, database
`maestro_verify13`):

```
MAISTRO_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/maestro_verify13 \
MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest packages/maistro-core/tests/events -q
385 passed
```

and the new tests do fail against the pre-fix code (the base tree's
`pg_audit.py` extracted to `/tmp/base13`, the branch's test file copied beside
it, base's own `pyproject.toml` `pythonpath` in force):

```
FAILED ...TestTheAuditStoreComesUpToo::test_wiring_creates_the_audit_table_it_needs
FAILED ...TestTheAuditStoreComesUpToo::test_the_audit_table_is_readable_after_the_wiring
asyncpg.exceptions.UndefinedTableError: relation "audit_log" does not exist
```

Focused local battery at this head:

- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 3362 files already formatted.
- `uv run pytest packages/maistro-core/tests/graph/durable_runs/test_node_retry_attempts.py packages/maistro-core/tests/graph/nodes/test_agent_synth_dag.py packages/maistro-core/tests/persistence/test_pg_audit.py packages/maistro-core/tests/test_container_wiring.py -q` → 108 passed, 1 skipped.
- `uv run pytest packages/hive-conductor/backend/tests/test_scheduler_canonical_admission.py -q` → 16 passed.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` → 16787 nodes, 0 duplicates, matches recorded inventory.

## 6. The sequence that unblocks it (develop-side, two merges)

1. On `develop`, land a `reachability` authorization for
   `maistro.runs.admission_identity` in `quality/ratchet-authorizations.json`,
   with the reviewed rationale that the leaf is a deliberately unwired contract
   (the disposition #1851 recorded).
2. In the change that needs it, add exactly one row to
   `quality/reachability-baseline.json`:
   `"maistro.runs.admission_identity"`, keeping the list sorted, with the
   `docs/architecture/CONVERGENCE-MATRIX.md` row the ledger's own conventions
   require.

After step 1 lands, this branch's step-2 row is a one-line diff and every
currently red job (`exact-debt-ledger`, `Quality / Reachability`, the root
`test` job, and the aggregating `Quality gate` / `Coverage gate` that inherit
them) goes green without touching production code.

## 7. Re-derived again at `e5767cd3b` (job `5939f970`, same day)

A second `exact-debt-ledger` repair round re-ran the gate rather than trusting
this note. Nothing in sections 2–4 changed, and it is now measured a second,
independent way — from a real git worktree of the base rather than a
`git archive` extract
(`git worktree add --detach ~/Git/worktrees/base13-e20e9f52 e20e9f52`):

```
$ cd ~/Git/worktrees/base13-e20e9f52 && uv run --project <branch> python scripts/check-reachability.py
1417 production modules, 169 unreachable from any entry point
1 module(s) are NEWLY UNREACHABLE:
  maistro.runs.admission_identity  (maistro.runs.admission_identity)
rc=1
```

`scripts/check-reachability-provenance.py` refuses to run *inside* that worktree
(`FAIL: the base revision resolves to HEAD itself … the comparison could not
fail`), which is the gate correctly rejecting a self-approving comparison — so
the base-side scan above plus the base ledger (168 rows, no `admission_identity`)
is the measurement, exactly as in section 3.

At the branch head, unchanged: `check-vulture-baseline.py` **rc=0** (1326 →
1326, `unclassified: 0`, `never_allowlist: 0`), `check-shipped-surface-truth.py`
**rc=0**, `check-ratchet-provenance.py` **rc=1** on the single reachability
bullet pair. There is still no vulture identity to bank or prune, and
`git diff --numstat origin/develop -- quality/` is still empty.

This round's substantive repair is to the branch's own production change, not
to the gate: the audit bootstrap created the table without the indexes the
migration chain and the SQLite sibling give it. See
[`inventory-notes/13-audit-log-schema-bootstrap.md`](inventory-notes/13-audit-log-schema-bootstrap.md#second-repair-round--the-bootstraps-index-shape-2026-10-20-job-5939f970).

## 8. Re-derived at `6808fca72` (2026-10-20, this round)

The two attempts before this one died to provider rate limits after their
checks passed; nothing they observed is inherited here. Re-executed at
`6808fca72`: all three `exact-debt-ledger` steps at CI's exact argv (step 1
rc=1 on the same single reachability bullet pair, steps 2–3 rc=0, vulture
1326→1326 with `unclassified: 0`), the base-worktree reproduction at
`e20e9f52` (169 unreachable, `maistro.runs.admission_identity` NEWLY
UNREACHABLE, rc=1), and the root-test failures (3 failed / 36 passed, all
naming that module). `origin/develop` is still at the base, so the two-merge
unblock has not started. The branch's audit-bootstrap repair was additionally
proved on a migrated `pgvector:pg18` database (`alembic upgrade head` → `063`:
test_pg_audit + test_container_wiring, 66 passed) and by a direct
before/after: the base `ensure_schema` raises `UndefinedTableError` on a fresh
database where the branch's `ensure_schema` creates the table with all 13
indexes. Full detail:
[`inventory-notes/13-one-execution-universe.md`](inventory-notes/13-one-execution-universe.md#third-ci-repair-round-at-6808fca72-2026-10-20).

## 9. Residual risks

- Until step 1 lands, this epic PR cannot merge no matter what any lane does
  here; the failure will keep reproducing on every sync.
- `quality/reachability-baseline.json`'s `_generated_from` still reads "1302
  production modules" against a 1417-module universe. Pre-existing on
  `develop`, not validated by the gate, and not touched here.
- The audit bootstrap mirrors migrations 005/036 (columns) and 005/062 (indexes)
  by hand. A future migration that changes `audit_log` must keep the two in
  step; the real-PostgreSQL `pg_indexes`/`information_schema` assertions in
  `test_container_pg_durable_events.py` are what will catch it.

## Resolution (2026-10-20 sync)

`auto-13` was merged with `origin/develop` at `c2d7209f1dbc` (merge commit
`9ec0c7eaa`). The inherited reachability ratchet no longer fires on the
merged tree: `maistro.runs.admission_identity` is reachable through
`maistro.runs`, and `check-ratchet-provenance.py`, `check-reachability.py`,
`check-vulture-baseline.py`, and `check-shipped-surface-truth.py` all exit 0.
The audit-schema bootstrap contract (bootstrap-create + page indexes) was
retained over develop's ALTER-only variant; see
`docs/testing/inventory-notes/auto-13-7b24.md` for the test-count delta.
