---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 develop-sync + exact-debt-ledger re-validation round at 049de5b47 (develop 6c739f054)

Snapshot: issue #1893 only; branch `auto-1893`, starting head verified exactly
`cbe81496c1a47a0debd268ddc39a8ae114ad1970`, briefed base `ab8b3737fa64f8`.
Worktree clean at entry, no incoming uncommitted work to salvage. Round type:
**develop sync** plus fresh re-execution of the `exact-debt-ledger` gates at
CI argv and the acceptance battery on the merged tree. No source, test,
ledger, grant, gate or migration edits authored this round; no GitHub
mutations. The delta is 0: the +7 above is develop's own
`1873-cancellation-receipt-readiness.md` (PR #2143) arriving with the merge
(16621 + 7 = 16628 collected, gate green); this round adds no tests and does
not double-count their note.

## develop sync

- `git fetch origin develop`: `refs/remotes/origin/develop` moved
  `498ff93a3cbf` → `6c739f054f99` — two commits: #2143 (cancellation-receipt
  readiness: `tasks/queue.py` +25 src, `api/runs.py` +23 src,
  `test_queue_persistence.py` +146, `test_runs_api.py` +176, its own
  inventory note) and #2145 (quality: `ac-state` grant
  `design_coverage@39.641`, owner-authorized two-merge landing).
- Merged conflict-free as `049de5b47`. Local refname hazard re-confirmed:
  a stale `refs/heads/origin/develop` (frozen at `ab8b3737f`) shadows the
  remote-tracking ref, so every command here names
  `refs/remotes/origin/develop` explicitly; merge-base vs develop is now
  `6c739f054`.
- quality/ integrity post-merge: `git diff --numstat cbe81496c..HEAD --
  quality/` shows exactly develop's +7/−1 (`ac-state` row landing); vs
  develop the branch is still purely additive (10 grant rows in
  ratchet-authorizations.json, 2 reachability-baseline entries, 11
  disposition rows; zero deletions, vulture-baseline.json untouched).
  Admission grant rows (`maistro.runs.admission_identity`,
  `maistro.tasks.admission_codec`), baseline entries and the
  `runs-root-admission-contracts` disposition group all verified present;
  develop's `design_coverage@39.641` row present.

## exact-debt-ledger at CI argv on merged head 049de5b47

- `check-shipped-surface-truth.py`: exit 0.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`: exit 0, exact 1322 reviewed == 1322 findings — the
  driver-named vulture-ledger amendment still has **no target**; zero
  unbanked identities.
- `check-reachability-provenance.py`: exit 1 on exactly
  `maistro.runs.admission_identity` + `maistro.tasks.admission_codec`
  ("NEW unreachable module absent from trusted base and not previously
  authorized"; 169 trusted → 171 current of 1403 modules, baseline origin
  `ab8b3737fa64` via the stale local trunk ref).
- `check-reachability-dispositions-provenance.py`: exit 1 on the same two
  identities ("NEW disposition ... not covered by an already-landed
  reachability authorization") — same single root cause, not a second wall.
- Umbrella `check-ratchet-provenance.py`: fails only on those two delegated
  adapters; every other delegated gate green (e.g. enumeration gaps 1→1,
  lifecycle 0→0).
- **Grant-first proof re-proven on the merged tree**: with
  `RATCHET_BASE_REV=6af21c54e` both provenance gates exit 0 (171==171
  exact; dispositions "new debt uses prior reachability authorization").
  The wall is authorization placement, not branch content.
- Fresh owner-state check: `git merge-base --is-ancestor 6af21c54e
  refs/remotes/origin/develop` is false and grep for the grant in
  develop's ratchet-authorizations.json counts 0 — develop tip `6c739f054`
  still lacks grant `6af21c54e`. Sole remaining ingredient is the
  owner-side grant-first landing on develop (two-merge rule,
  `load_authorizations` reads `quality/ratchet-authorizations.json` from
  the merge base only), which requires a GitHub push this lane is
  prohibited from performing.

## Acceptance battery on merged head 049de5b47

- `uv run ruff check .` / `uv run ruff format --check .`: both exit 0
  (3302 files formatted).
- Focused B2 suite `packages/maistro-core/tests/tasks/test_admission_codec.py`:
  128 passed / 3 skipped (skips = the DSN-gated PG legs at line 470).
- Driver's five regression files + develop's new
  `test_queue_persistence.py`: 399 passed / 3 skipped.
- Suite inventory: `check-suite-inventory.py --suite
  packages/maistro-core/tests` exit 0 at 16628 collected / 16628 unique,
  0 duplicate evidence.
- mypy at ci.yml argv (10 package src trees): "Success: no issues found in
  1059 source files".
- Scope re-check: branch vs develop package delta is exactly the admission
  contract slice (`runs/admission_identity.py` +517,
  `tasks/admission_codec.py` +662, `_vulture_whitelist.py` +32 scan input)
  plus tests — no SQL migration, HTTP mapping or queue change authored by
  this slice; admission src and tests are bit-identical to the PG-proven
  head `94de9c2ec` (`git diff 94de9c2ec HEAD` on those paths is empty).
- B2 interfaces re-read in source on the merged tree:
  `AdmissionRowHeader` frozen+slotted with the six contract fields and
  `format_version: Literal[1, 2]`; `decode_admission_header`;
  `decode_admission_record`; `encode_admission_record`;
  `AdmissionDecodeCode` with exactly the six contract values;
  `AdmissionRowDecodeError(ValueError)` carrying `code` + validated-hash
  `scope_key` with `raise ... from None` chain suppression throughout;
  partial pair / bound-pair-without-receipt / receipt-only all yield
  `partial_legacy_binding` without guessing the cause; no fingerprint
  recalculation. All 10 prospective test names present (1 each).
- **PG durability LIVE re-proven** on fresh disposable DB `adm1893_r6`
  (pgvector:pg18 container `maistro-postgres`, host port 5433): real
  alembic chain `DATABASE_URL=...adm1893_r6 uv run alembic upgrade head`
  ran 001→063 exit 0; then `MAISTRO_REQUIRE_PG_LEGS=1` with
  `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` targeting the same
  DB: codec + identity suites **204 passed / 0 skipped** (all three PG
  legs executed, raw-vs-production pool server identity asserted inside
  the test). DB dropped afterwards.

## Wall status (unchanged)

exact-debt-ledger remains red solely because the #1893 reachability
authorization must land on develop before any candidate that introduces the
two modules can be judged against it. Every branch-side ingredient is in
place and proven: content green under grant-first base, vulture exact with
zero amendable rows, dispositions/baseline banked. No permitted edit can
substitute for the owner-side landing.
