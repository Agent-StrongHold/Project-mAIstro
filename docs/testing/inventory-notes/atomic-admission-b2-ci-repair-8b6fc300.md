---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 CI-repair round at aad0bdb3855b (job 8b6fc300)

Snapshot: issue #1893 only; branch `auto-1893`, starting HEAD verified exactly
`aad0bdb3855b250bd84ec6d71c7198b8fe2b4632`, worktree clean at entry, live
`git ls-remote origin develop` = `ab8b3737fa64f8d840f421ef87ca506c509444ff` =
merge-base = the supplied develop base, so the branch is 0 behind and no sync
merge was needed. No source, test, ledger, grant or gate edits this round
(docs only). The prior lane (job a2c32ef9) died on a provider timeout AFTER
its five deterministic checks had all passed (rc=0 each); its evidence was
re-executed, not assumed.

## Verdict-relevant fresh evidence executed at this head

CI `exact-debt-ledger` job steps reproduced at CI's exact argv
(`.github/workflows/vulture-ratchet.yml:82-86`, after
`uv sync --locked --all-extras` per vulture-ratchet.yml:75):

1. `uv run python scripts/check-ratchet-provenance.py` -> **FAIL (exit 1)**,
   sole failures are the `reachability` and `reachability-dispositions`
   ratchets on exactly two identities: `maistro.runs.admission_identity` and
   `maistro.tasks.admission_codec` — "NEW ... absent from trusted ledger and
   not covered by an already-landed reachability authorization". All eight
   other ratchets in the same run passed with no candidate-approved expansion.
2. `uv run python scripts/check-shipped-surface-truth.py` -> exit 0.
3. `uv run python scripts/check-vulture-baseline.py packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'` -> **exit 0**, exact
   1322 reviewed identities == 1322 findings, unclassified 0. The lane
   brief's vulture-amendment remedy therefore has no target: there are zero
   unbanked or amendable vulture rows at this head.

## Why the remaining failure is structural (not repairable in-lane)

- `scripts/ratchet_provenance.py:478` (`load_authorizations`) reads grants
  **from the base revision** by design: "a new grant does not take effect in
  the change that introduces it. Authorizing a floor-raise is now two
  merges". `git diff origin/develop...HEAD -- quality/` shows the branch
  already carries candidate-side rows for the two identities
  (`ratchet-authorizations.json` +10, `reachability-baseline.json` +2,
  `reachability-dispositions.json` +11), which the gate necessarily ignores.
- The develop tip (the gate's trusted base) carries no grant for either
  identity (live ls-remote above; base `ratchet-authorizations.json`
  inspected: no `reachability-dispositions` key at all, and no such
  `reachability` entries).
- Issue #1893 forbids both remaining escape valves in its own text: "No
  production activation ... C is the consumer" / "no live _assess change"
  (wiring the codec to manufacture reachability), and "Test imports, fake
  callers and package exports are not runtime reachability; no
  baseline/grant/gate modifications to make an unwired slice green". A prior
  wiring attempt was already reverted on this branch
  (`0eacd9a44 revert 29e3be4's broken reachability hack in idempotency.py`).
- Deleting the two modules would destroy the leaf's mandated deliverable
  (the issue names both file paths as exact scope; `admission_identity.py`
  is the #1851 prerequisite "types must be present on the agreed
  integration branch").
- Lane prohibitions bar editing `quality/*.json` beyond the vulture ledger,
  and the vulture ledger is exact. Removing the candidate-side rows would
  only convert the authorization failure into a banking failure
  (`check-reachability-provenance.py` fails on `candidate_added` too);
  the outcome is walled either way.

Unblock paths (owner coordination, outside this lane): land the
reachability/reachability-dispositions grants on develop first (the
documented two-merge flow), or land the C consumer leaf that makes the
modules genuinely reachable, or an explicit owner re-scope. This matches the
issue's own `COORDINATION_REQUIRED` marker.

## Deliverable conformance re-verified at this head

- Exact-scope files present: `packages/maistro-core/src/maistro/tasks/
  admission_codec.py` (662 lines), `packages/maistro-core/tests/tasks/
  test_admission_codec.py` (816 lines), plus `maistro/runs/admission_identity.py`
  (#1851 DTO stack) and its test file. All 10 prospective tests named in the
  issue exist and pass.
- Interfaces read against the issue text and conform exactly:
  `@dataclass(frozen=True, slots=True)` `AdmissionRowHeader` with the six
  specified fields; `decode_admission_header(row)`; `decode_admission_record(
  row, *, header)` re-deriving and rejecting a header/row mismatch
  (`invalid_header`); `encode_admission_record` returning a fresh flat
  mapping; `AdmissionDecodeCode(StrEnum)` with exactly the six specified
  values; `AdmissionRowDecodeError(ValueError)` carrying `code` and a
  `scope_key` that is a validated `[0-9a-f]{64}` or `None`, with `raise ...
  from None` chains (no raw snapshot/owner-token leakage).
- Diff surface confirms "No SQL mutation, HTTP mapping or queue changes":
  branch-vs-base changes are the two new modules, the `_vulture_whitelist`
  scanner-input additions, four test files (two new; `test_cli_lock.py`
  hardened with three extra assertions at three terminal widths;
  `test_pack_contracts.py` gains a new pack/extension identity-conflict
  boundary test), and the quality ledgers discussed above. No routes, queue
  or `_assess` files touched.
- Focused (issue command) `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py -q` -> 128
  passed, 3 skipped; the 3 skips are the DSN-gated PG legs at
  `test_admission_codec.py:470` ("set MAISTRO_TEST_PG_DSN and
  MAISTRO_TEST_DATABASE_URL").
- PG durability re-proven live THIS round on a NEW disposable DB
  `adm1893_r1792254349` (existing healthy pgvector/pg18 container
  `maistro-postgres`, 127.0.0.1:5433): `DATABASE_URL=... uv run alembic
  upgrade head` ran the real migration chain 001->063, exit 0; then
  `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=... MAISTRO_TEST_DATABASE_URL=...
  uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py -q`
  -> **131 passed, 0 skipped**; same env against
  `packages/maistro-core/tests/runs/test_root_admission_identity.py -q` ->
  **73 passed**. Raw-asyncpg vs production-pool codec parity leg included in
  the 131 (no skip counted as durability).
- `uv run mypy packages/maistro-core/src` under the CI `--all-extras` sync ->
  Success: no issues found in 791 source files.
- Driver deterministic checks at this head (job 8b6fc300, all rc=0):
  `uv sync --locked --extra dev`; `ruff check .` ("All checks passed!");
  `ruff format --check .` (3301 files already formatted); focused pytest set
  (346 passed, 3 skipped — the same three DSN-gated legs, re-proven live
  above); `scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` ("ok ... 16567", unique-evidence clean).

No tests were added or removed this round (inventory delta: 0). Canonical
execution model (Goal -> Graph -> Run -> NodeRun -> Attempt) untouched: the
leaf defines typed vocabulary and a pure codec only, authorizing nothing.
