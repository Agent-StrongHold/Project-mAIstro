---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round at 14d7e8ac4 (job 955976d8)

Snapshot: issue #1893 only; branch `auto-1893`, starting HEAD verified exactly
`14d7e8ac4717fd8f0ae3282bcd761a21576b7164`, worktree clean at entry, no
incoming uncommitted work to salvage. No source or test edits this round; no
ledger/grant/gate edits (the issue forbids baseline/grant modifications to
green an unwired slice, and the lane-brief vulture amendment has no target —
see below). No GitHub mutations.

## Which CI gate is actually red

Live API evidence at the remote branch head `80171ce1cff9` (= `origin/auto-1893`,
a strict ancestor of this HEAD; local is 39 ahead, 0 behind): workflow `CI`
→ **success**, `quality` → success, `Vulture Ratchet` → **failure**, all others
success. Job `exact-debt-ledger` (117010602424) failed at the single step
"Require enforced ratchet provenance policy"
(`.github/workflows/vulture-ratchet.yml:78`); the vulture and shipped-surface
steps of the same job did not fail. The lane brief's named `test: failure`
does not correspond to any run on this branch's heads — the `test` job is
green on the remote head and all seven of its pytest legs were re-executed
green locally at this HEAD (counts below).

## Fresh evidence executed at this HEAD (14d7e8ac4)

- CI `test` job legs, CI env (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`):
  `tests/ --ignore=tests/tools/registry` **4978 passed, 135 skipped**;
  `packages/maistro-server/tests` **557 passed, 8 skipped**;
  `packages/maistro-turing/tests` **210 passed**;
  `packages/maistro-turing/backend/tests` **90 passed**;
  `packages/maistro-design/tests` **572 passed, 1 skipped**;
  `packages/maistro-ext-harness/tests` **273 passed**;
  `packages/maistro-ext-sdk/tests` **147 passed**.
- exact-debt-ledger gates with CI-exact arguments:
  `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` → **exit 1** on exactly the two
  reachability entries (`maistro.runs.admission_identity`,
  `maistro.tasks.admission_codec`: "NEW disposition absent from trusted ledger
  and not covered by an already-landed reachability authorization" / "NEW
  unreachable module absent from trusted base and not previously authorized");
  `scripts/check-shipped-surface-truth.py` → exit 0;
  `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → exit 0, **1322 reviewed = 1322 findings** —
  no unbanked identity, so the lane-brief vulture amendment has no target.
- Candidate-side reachability legs: `check-reachability.py packages` → exit 0
  (171 banked); `check-reachability-dispositions.py` → exit 0 (50 groups).
  Only the *provenance* wrappers fail: `ratchet_provenance.load_authorizations`
  reads `quality/ratchet-authorizations.json` from the merge-base revision
  (ac737014), so a grant cannot authorize the change that introduces it
  (two-merge rule; scripts/ratchet_provenance.py:478-518).
- Focused B2 suites, pure: 201 passed, 3 skipped. mypy on
  `packages/maistro-core/src`: clean (791 files).
- Real-PostgreSQL durability re-executed on a **fresh** disposable PG 18.6
  container (`maistro-verify-1893`, port 18499, DB `repair1893_verify`):
  `uv run alembic upgrade head` applied the full real chain 001→063;
  `ck_task_idempotency_v2_identity` present. Focused B2 suites with
  `MAISTRO_REQUIRE_PG_LEGS=1`, `MAISTRO_TEST_PG_DSN` and
  `MAISTRO_TEST_DATABASE_URL` set: **204 passed, 0 skipped**. Residue rows in
  `task_idempotency` after the run: **0**. The CHECK constraint live-fires: a
  hand INSERT with `task_id='rcpt-OTHER'` ≠ `receipt_id='rcpt-1'` is rejected
  with `ck_task_idempotency_v2_identity` — the exact identity match the
  repaired `admission_identity.py:291-292` enforces and
  `admission_codec.py:291-292` emits (`task_id = binding.receipt_id`,
  `run_id = binding.run_id`, both from one binding).
- All 10 prospective test names from the issue body are present in
  `test_admission_codec.py` and executed in the runs above.
- Full `packages/maistro-core/tests` tree with PG legs (corrected plain-DSN
  env): **16437 passed, 137 skipped, 7 failed, 3 xfailed**. All 7 failures are
  pre-existing PostgreSQL-leg failures in
  `conformance/test_approval_store_conformance.py` (6) and
  `backlog/test_backlog_store_conformance.py` (1) — modules this branch never
  touched (branch diff touches only new admission modules, their tests, a
  vulture whitelist and quality/ ledgers); both files import only untouched
  code (`maistro.capabilities.approval_store`, `maistro.backlog.*`); CI's PG
  job never runs either file with `MAISTRO_REQUIRE_PG_LEGS`. Zero failures in
  anything branch-touched. (First full-tree attempt with a
  `postgresql+asyncpg://` MAISTRO_TEST_DATABASE_URL produced 93 setup errors —
  `conformance/_legs.py` hands that variable to asyncpg raw, which rejects the
  driver suffix; environmental, resolved by the plain scheme the codec test's
  own strip-regex tolerates.)

## Structural blocker (unchanged, now re-proven at this head)

`origin/develop` advanced one unrelated commit to `ab8b3737` (#1627 graph
test); the prepared reachability grant `3235229f5fed` is still **not** an
ancestor of `origin/develop`, so merging develop now would move the trusted
base without authorizing the two rows — the merge is step two of the
two-merge sequence and belongs after the grant lands on develop. Landing the
grant requires a develop-side push, which is worker-prohibited. Unblock:
land `3235229f5fed`'s authorization content on develop, then merge
`origin/develop` into `auto-1893`; `check-ratchet-provenance.py` then passes
with the same candidate ledgers.

No closure keywords against #1893 in any commit subject on this branch
(checked `ac7370141e8e..HEAD`).
