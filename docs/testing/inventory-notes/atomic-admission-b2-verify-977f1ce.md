---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 B2 verification round at 977f1ce (job 70d64ce0)

Snapshot: issue #1893 only; branch `auto-1893`, starting HEAD verified exactly
`977f1cedc9b92eb9c28baa66fcae05f588420d94`, worktree clean at entry, no
incoming uncommitted work to salvage. Supplied develop base
`ac7370141e8e61bd6f352bca35ed0b505104aadb` re-fetched and re-confirmed as
`origin/develop` in both this worktree and the canonical clone (develop
advanced past the round-22 states `9bd1a93ee`/`83c7788d6` — both proven
ancestors of this HEAD — to `ac737014` bump commits; merge-base equals the
develop tip, so the branch is exactly synced). The prepared reachability grant
`3235229f5fed` is still not on `origin/develop`; the two-merge dependency is
unchanged. No GitHub mutations, no ledger/grant/gate edits, no source or test
edits this round.

Driver verifier logs (check-0..check-4) all green: uv sync, ruff check,
ruff format, focused admission files 346 passed / 3 skipped (pure mode),
suite inventory `packages/maistro-core/tests` 16,567 nodes, 0 duplicates.

## Fresh evidence executed at this head

- Focused admission suites, pure: `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q`
  -> **201 passed, 3 skipped** (the skips are the real-pool leg awaiting DSNs).
- Real-PostgreSQL durability re-executed: fresh disposable DB
  `repair1893_977f1ce` on the lane pgvector/pg18 server (127.0.0.1:5433,
  PostgreSQL 18.6) migrated through the real chain with
  `DATABASE_URL=... uv run alembic upgrade head` to head **063** (chain
  001 -> 063 includes 055 forward admission representation). Focused suites
  plus the two extension files under `MAISTRO_REQUIRE_PG_LEGS=1` with both
  `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` targeting that DB:
  **349 passed, 0 skipped** — the raw-asyncpg vs `_register_json_codecs`
  two-pool TEXT snapshot identity proof ran for real. Post-run DB state:
  `ck_task_idempotency_v2_identity` present, **0** residue rows in
  `task_idempotency`.
- CI `test` job (`.github/workflows/ci.yml:504`) pytest legs at this head,
  CI env (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`, 60s timeouts):
  `tests/ --ignore=tests/tools/registry` **4978 passed, 135 skipped**;
  `packages/maistro-server/tests` **557 passed, 8 skipped**;
  `packages/maistro-turing/tests` **210 passed**;
  `packages/maistro-turing/backend/tests` **90 passed**;
  `packages/maistro-design/tests` **572 passed, 1 skipped**;
  `packages/maistro-ext-harness/tests` **273 passed**;
  `packages/maistro-ext-sdk/tests` **147 passed**. The hosted
  merge-queue `test: failure` remains unreproducible: every pytest leg of
  that job is green at this head, and the branch's diff touches no frontend,
  server, turing, or migration file (232 docs, 7 maistro-core, 2 quality,
  2 root REPAIR-NOTES, 1 `.cursor` context file).
- `packages/maistro-core/tests/runs` + `packages/maistro-core/tests/tasks`
  -> **1919 passed, 310 skipped** (adjacent-subtree regression, no failures).
- Full-gate equivalents: `scripts/check-suite-inventory.py` (all suites)
  -> **ok: 17 suite(s) match the recorded inventory**;
  `scripts/check-test-duplicates.py` -> ok; `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py` -> Success.
- CI-exact debt-ledger legs: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> **1322 reviewed
  identities = 1322 findings, exit 0** (no vulture amendment warranted — the
  lane brief's vulture-ledger repair instruction has nothing unbanked to
  act on at this head); `check-reachability.py` -> 1403 production modules,
  171 unreachable, exit 0 (candidate baseline matches the scan exactly);
  `check-reachability-dispositions.py` -> 50 groups cover all 171
  (149 CONNECT / 20 LIBRARY / 2 RETIRE), exit 0;
  `check-shipped-surface-truth.py` -> complete, exit 0.
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` -> **exit 1, unchanged in shape**:
  exactly the two reachability provenance sub-gates fail on
  `maistro.runs.admission_identity` + `maistro.tasks.admission_codec`
  (NEW vs trusted base `ac737014`, "not covered by an already-landed
  reachability authorization"); every other sub-ratchet OK (vulture,
  promotion-surface 270, contract-markers 358, enumerations, lifecycle,
  shell, adr-status-language, citation-status).

## Conclusion

Round 22's state is reproduced and extended at `977f1cedc9b9` against the
ninth successive develop state: all B2 leaf evidence is green, including the
live PG 18.6 durability leg at migration head 063, and the CI `test` job's
failure is not reproducible at this head. The only red anywhere remains the
exact-debt-ledger reachability provenance pair, which structurally cannot
clear in-branch: the gate reads `quality/ratchet-authorizations.json` from
the merge base, the two modules are deliberately unwired contract leaves per
#1893's own scope ("no baseline/grant/gate modifications to make an unwired
slice green"), and the prepared two-entry grant (`3235229f5fed`, probe- and
constructively-proven green post-landing in rounds 17-22) must land on
develop before `origin/develop` is merged here. That landing is
campaign-level and outside worker authority (no push permitted). This round
adds no tests; `inventory-delta` is 0.
