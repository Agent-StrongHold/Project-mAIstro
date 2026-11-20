# REPAIR-NOTES — #337 round: develop sync concluded, suite-inventory drift fixed

Job `aa208ef5926a42b18b3d3601168d991e`, branch `auto-337`. Incoming head
`46b0986d1` ("Add record_outcome function to feedback_service.py", the
#337 feedback-durability writer). Two blocks carried in: the previous
worker's concluded-but-uncommitted develop sync ("worker made no commit"),
and the red `test` check from the last merge-queue evaluation at
`4f053797`.

## 1. The preserved merge resolution is concluded, then the sync is completed

The worktree arrived mid-merge (`403a3ba3e`, one resolved conflict in
`tests/test_check_image_lock_reconciliation.py`, no conflict markers) —
the prior attempt's rate-limit death (429) landed after its checks passed
but before `git commit`. Nothing was reset: the staged resolution was
validated as-is (ruff check/format clean; the resolved gate file plus the
four #337 durability suites → 152 passed) and concluded as `f147e3353`.

`origin/develop` had advanced past the merge head, so a second
`git merge origin/develop` (now `db1885b44`, the M1 closeout) auto-merged
clean and committed as `5390137da`. Quality ledgers: `git diff --numstat
origin/develop -- quality/` is empty — no row silently lost or duplicated
by either merge (vulture is a multiset; nothing was passed through
`set()`). The vulture gate (CI-exact args) reads 1263 reviewed identities
= 1263 findings, exit 0, no ledger amendment needed or made.

## 2. The red `test` check — root cause and local proof

The round-2 notes on this lane already established (and this round
re-confirmed) that the `RuntimeError: Event loop is closed` lines in that
CI log are teardown annotations from a pytest step that PASSED — the job
proceeded past them to the npm-audit step, and the full root suite passes
locally. Every `test`-job step was re-run against the merged head:

- `uv run pytest tests/ --ignore=tests/tools/registry -q` → **5800 passed,
  139 skipped** (342s), no event-loop errors;
- `uv run pytest packages/hive-conductor/backend/tests -q` → **4084
  passed, 28 skipped**;
- cross-suite leakage step, all three trees in one process with
  `--timeout=60` → **10638 passed, 169 skipped** (672s);
- `npm audit --audit-level=high` (canvas) → **found 0 vulnerabilities**,
  exit 0 (the HIGHs that red this step in earlier rounds were lockfile
  fixed in the round-2 repair, which develop now carries);
- canvas `npm run test:ci` **84 passed**, `npm run lint` exit 0, `npm run
  build` ok; hive frontend `npm run lint` / `npm run build` exit 0;
- hive OpenAPI generated types: `dump-hive-openapi.py` + `gen:api` →
  `git diff --exit-code` on `types.gen.ts` clean;
- `check-test-duplicates.py` → ok (0 byte-identical files).

## 3. Suite-inventory drift (net −1 on `tests/`) — fixed in its own note

The sync superseded the last test this lane's inventory note counted:
`test_parse_expected_keeps_every_entry_of_a_forked_conditional_name`
(existed only on this branch, recorded as `tests/: +1` in
`auto-337-a36c.md`) is replaced byte-for-byte in coverage by develop's
renamed `test_parse_expected_keeps_every_marker_forked_variant_of_a_name`
— same required-pin-beside-a-forked-name fixture (now with
hash-continuation lines) and the same two assertions — which develop's own
`93-image-lock-gate-marker-forks` delta already counts. Keeping the `+1`
would double-count a node that no longer exists (the collected count was
6032 vs expected 6033). The note's front matter now records only the hive
backend `+8` (untouched), with a prose section documenting the
supersession, per the note's own across-sync convention.
`check-suite-inventory.py` → **ok: 21 suite(s) match the recorded
inventory**.

## 4. Issue #337 acceptance re-verified against reachable behavior (no edits needed)

All four state families' governing specs are Accepted and name their
proving tests; all were executed on the merged head (294 passed, 14
skipped — every skip is `MAISTRO_TEST_PG_DSN is not set`, the PostgreSQL
conformance leg whose producer is ci.yml/quality.yml's
`MAISTRO_TEST_PG_DSN`-gated job):

- **DAG history** (SPEC-083026-2601): restart survival, after-the-write
  reader, already-running reader staleness, another-replica reload,
  canonical run-id carried or honestly absent, retention bound stated by
  the endpoint and enforced on load — `test_dag_run_history_durability.py`.
- **Node metrics** (SPEC-083026-2642): survive-restart + replica refresh,
  canonical attempt as idempotency key, projection carries all canonical
  ids, retention eviction, workspace-scoped reads fail closed,
  non-positive bound refused — `test_durable_node_metrics.py`.
- **Feedback** (SPEC-083026-58de): `set_outcome_store` has its production
  caller (`engine._wire_outcome_store`, engine.py:290, with the #1181
  unwind rebind); `record_outcome` paths in `chat_completion.py` write
  under the #1036 terminality contract; thumbs conformance runs its
  SQLite leg here and the PG leg in the hosted gate.
- **Profiles** (SPEC-083026-ef62): read-back-before-acknowledgement over
  `PersistedStore`, real SQLite round-trip, deletion, tools read what the
  route wrote and vice versa — `test_profile_durability.py`.
- Scope authorization and pagination are explicit and tested
  (`test_dag_run_scope.py`: scope-filtered list, limit applied after
  filtering, out-of-scope reads/SSE refused like missing).

The `record_outcome` service function added at the incoming head writes
through the same bound durable store; the vulture gate is green at
CI-exact args, so it carries no unbanked unused-wiring identity.

## Commands and outcomes (summary)

- `uv run ruff check .` / `uv run ruff format --check .` → clean (run
  after each merge and on the final tree).
- Merges: `git commit` (concluding preserved resolution), `git merge
  origin/develop` → auto-resolved, committed.
- Test/inventory evidence as listed in §2–§4.
- `git diff --numstat origin/develop -- quality/` → empty.

## Not touched / residuals

- No production code changed this round: the repair was the sync
  conclusion plus the inventory-note correction; #337's durability work
  was verified, not rewritten.
- The 14 skipped thumbs-conformance nodes need a live Postgres; their
  producer runs in the hosted PG-gated job, so local evidence is the
  SQLite leg plus the gate's own environment contract.
