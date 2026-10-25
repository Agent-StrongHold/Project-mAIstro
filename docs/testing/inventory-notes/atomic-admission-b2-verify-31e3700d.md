---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round — job 31e3700d8faa (test-gate repair round)

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`8cbe9dee60b0fe61c0e622ee024661ef8af51fdb` (prior round's evidence note on top
of merge commit `0efacadf3`, PR #1945 head). Delta vs the fully-verified head
`0efacadf306b` is exactly one docs file
(`atomic-admission-b2-verify-0efacadf.md`, `git diff --stat` = 1 file, 112
insertions) — **no production code, test, ledger, grant or gate file changed**
since that head, so prior-round evidence carries over by content identity
where not re-executed. This round adds one evidence note and no tests
(inventory delta 0).

## Named CI gate "test" — every leg re-executed fresh at this head

CI env `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1` where CI sets it:

- `uv sync --locked --extra dev --extra bootstrap` → resolved 256 packages
- `packages/maistro-server/tests` → **545 passed, 8 skipped**
- `packages/maistro-turing/tests` → **210 passed**
- `packages/maistro-turing/backend/tests` → **90 passed**
- `packages/maistro-design/tests` → **572 passed, 1 skipped**
- `packages/maistro-ext-harness/tests` → **273 passed**
- `packages/maistro-ext-sdk/tests` → **147 passed**
- `tests/ --ignore=tests/tools/registry` → **4971 passed, 129 skipped** (4m46s)
- `packages/hive-conductor/backend/tests` → **3626 passed, 19 skipped**
- one-process leakage (`tests/` + hive backend + design, `--timeout=60`) →
  **9262 passed, 149 skipped** (7m36s)
- `scripts/check-suite-inventory.py` → **17 suites match**, 0 duplicates
- `scripts/check-test-duplicates.py` → 1586 files, 0 byte-identical groups
- OpenAPI types: `dump-hive-openapi.py` + `npm run gen:api` +
  `git diff --exit-code types.gen.ts` → **no diff**, tree clean after
- hive frontend: `npm run lint` 0 errors (94 pre-existing warnings),
  `npm run build` exit 0
- canvas frontend: `npm run test:ci` **79 passed (5 files)**, `npm run lint`
  0 errors (13 warnings), `npm run build` exit 0 (re-run with exit captured)

Every leg of the `test` job is green at this head; the merge-queue
"test: failure" row is not reproducible here. (Prior round additionally
showed CI's own `test` job at this content concluding success at
2026-10-10T15:30:00Z.)

## exact-debt-ledger with CI's exact arguments (fresh at this head)

- vulture leg: `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → **1323 reviewed identities = 1323 findings,
  exit 0. No vulture-baseline.json amendment needed or made.**
- shipped-surface leg: complete, exit 0.
- provenance leg (`RATCHET_BASE_REV=origin/develop
  check-ratchet-provenance.py`): FAIL, identical to the prior round and the
  CI log for this head — `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` NEW disposition/baseline rows "absent from
  trusted base and not previously authorized". `origin/develop` re-fetched
  this round is **still `bb4257f0960f`** — the reachability authorization has
  not landed. Two-merge rule applies: the grant must land on develop first;
  the lane brief's ledger exception covers the vulture ledger only, and issue
  #1893 forbids "baseline/grant/gate modifications to make an unwired slice
  green". No permitted in-lane action changes this; unblock = owner lands the
  reachability grant on develop, then this branch merges develop.

## Other gates re-run fresh at this head

- `uv run ruff check .` → all checks passed (driver check-1)
- `uv run ruff format --check .` → 3272 files formatted (driver check-2)
- mypy over the seven published `src` trees → "Success: no issues found in
  892 source files"
- focused admission pytest (driver check-3) → 201 passed, 3 skipped
  (PG legs skip without DSN); prior round's live-PG durability evidence
  (chain 001→062 destructive-first, 204/0 with `MAISTRO_REQUIRE_PG_LEGS=1`,
  `ck_task_idempotency_v2_identity` positive + negative probes, 0 residue)
  carries over: the delta to that head is docs-only.

## Premature-closure scan

No `fixes/closes/resolves #1893` in any commit subject/body on the branch;
PR #1945 body says "Refs #1893" only (unchanged from prior round's scan).
