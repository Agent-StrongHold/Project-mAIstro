# #1893 verification round — job 9445c760

Snapshot: issue #1893 only; assigned branch `auto-1893`, clean starting HEAD
`717be4d741ebac8d7197a49920b292ff531bc234` (one docs commit ahead of the
dispatch-context PR #1945 head `4e43df759aad`; unpushed — no push permitted),
develop base `ed5613457d6fa54e99d0b968b72870cb96938573` per lane assignment.
Evidence: driver logs check-0..4 of this job, the prior artifact
`9de5cfe5e8ac43839bdf5610774f0045/result.json` (treated as claims to re-check,
not as proof), and this round's own reruns. One read-only `git fetch origin`.

No production code, ledger, grant, gate or test file was edited this round.

## Refuting the lane's `test: failure` signal (read-only GitHub queries)

- `gh pr view 1945 --json statusCheckRollup` at head `4e43df759`: the `test`
  check is **SUCCESS**; the only FAILURE is `exact-debt-ledger`. Every other
  required job (postgres pg17/pg18, coverage legs, lint-and-type-check, Gate C,
  quality, security, integration-scope, docker-build, e2e) is SUCCESS/SKIPPED.
- `gh run list --event merge_group` (300 runs): **no merge-group run has ever
  been created for pr-1945/auto-1893**; the failing merge-queue `test` runs the
  lane cites do not exist for this branch. Every `CI` workflow run on
  `auto-1893` (feb983e48, 1584201b3, 4e43df759) concluded success.
- The `test: failure` in the lane brief is therefore stale, not actionable.

## exact-debt-ledger — reproduced first-hand, still structurally blocked

`RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
→ **exit 1** at `717be4d741eb`, with the trusted base resolving to merge-base
`cc6e4899ddef` (verified in the adapter banner), both sub-gates failing for
exactly `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`
(NEW unreachable module / NEW disposition, no already-landed authorization).
All other delegated ratchets in the same run pass (adr-status-language,
citation-status, promotion-surface, shell-execution, contract-markers,
enumerations, lifecycle).

Origin/develop re-fetched: now `ed5613457d6f` — four commits beyond the prior
round's `5df964aba` (#2105 backup permissions, #2104 MCP authorities, #2106
CORS loopback, #2074 research WIP). `git log cc6e4899d..origin/develop --stat`
shows **no commit touches `quality/reachability-baseline.json`,
`quality/reachability-dispositions.json` or
`quality/ratchet-authorizations.json`**: the grant has still not landed, so the
two-merge rule still forbids branch-side self-authorization
(`ratchet_provenance.load_authorizations` reads the base).

No-ledger-escape proof from code, not experiment: `scripts/check-reachability.py`
`main()` computes `added = set(unreachable) - baseline` and exits 1 on any
added module ("add them to quality/reachability-baseline.json"), so deleting
the two baseline rows fails the candidate-blocking ratchet; keeping them fails
the base-resolved provenance adapter until an authorization lands on the base.
Candidate-side ratchets are green: `check-reachability.py` exit 0 (171
unreachable of 1379), `check-reachability-dispositions.py` exit 0.

The lane's vulture amendment exception is inapplicable: `check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 0
(1323 reviewed → 1323, unclassified 0). `check-shipped-surface-truth.py` → exit 0.

## Other legs re-run at this head

- Driver check-0..4: all pass (uv sync, ruff check, ruff format --check 3238
  files, focused pytest **201 passed 3 skipped**, suite-inventory maistro-core
  16298 node IDs).
- Focused pytest rerun: 201 passed, 3 skipped — the 3 skips are exactly the
  PostgreSQL legs.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py` → clean.

## Live PostgreSQL durability — re-produced independently (new this round)

Prior rounds' PG evidence was re-executed from scratch, not trusted:

1. Fresh disposable container `auto1893-repair-pg` (pgvector/pgvector:pg18,
   port 18599, distinct from the unrelated soak container on 18433), removed
   after capture.
2. `DATABASE_URL=… uv run alembic upgrade head` → real chain **001→061,
   exit 0**.
3. `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL=…
   uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py
   packages/maistro-core/tests/tasks/test_admission_codec.py -q` →
   **204 passed, 0 skipped** (was 201+3s without PG; the same three legs ran for
   real, including the parametrized
   `test_raw_and_production_pool_codecs_read_identical_text_snapshots`
   unbound/bound/acknowledged against a production-codec pool).
4. Catalog evidence read back with psql: `pg_constraint.pg_get_constraintdef`
   for `ck_task_idempotency_v2_identity` carries, for `format_version = 2`:
   non-zero `[0-9a-f]{32}` generation_id and claim_token, all immutable-envelope
   fields non-blank, `expires_at > created_at`, binding rule
   `((task_id IS NULL AND run_id IS NULL) OR (task_id IS NOT NULL AND run_id IS
   NOT NULL AND task_id = receipt_id))`, and `acknowledged_at` only with a full
   pair. `SELECT count(*) FROM task_idempotency` after the run → **0 residue
   rows**.
5. Repaired code points read at this head: `admission_codec.py:291-292` emits
   `task_id`/`run_id` together from the binding (`task_id = binding.receipt_id`,
   matching the CHECK); `admission_identity.py:289-292` enforces
   `binding.receipt_id == envelope.receipt_id`;
   `test_admission_codec.py:133-137` asserts the migration-055 binding shape
   independently of encode/decode agreement.

## Verdict-relevant residue

`exact-debt-ledger` cannot go green from this branch: it needs the reachability
grant landed on origin/develop and then develop merged into auto-1893 (the
sanctioned two-merge path), which is outside writer authority — no GitHub
mutations. Frontend npm legs remain unexecuted locally (no Node-project change
on the branch; the backend↔frontend coupling point, `types.gen.ts`, is covered
by the PR-run `test` SUCCESS at `4e43df759`).
