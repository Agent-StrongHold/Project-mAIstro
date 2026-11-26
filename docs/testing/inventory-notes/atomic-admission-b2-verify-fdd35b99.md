---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round at fdd35b99 (job 82e7ec99)

Snapshot: issue #1893 only; branch `auto-1893`, starting head verified exactly
`fdd35b9959f8905a7f950bdd91eb8f9d8d7419f3`, worktree clean, develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7` re-fetched: `origin/develop` has not
moved and the merge-base equals the develop tip, so no develop sync was needed.
No source or test edits this round (docs only); no GitHub mutations.

This round re-verified, by fresh execution at this head, every claim the two
preceding rounds recorded — the driver checks (`check-0..4.log`) had already
passed, and the prior job (41b694c9) died on a provider timeout after its
checks passed, so nothing below is carried over on trust.

## Fresh evidence executed this round (all commands run at this head)

- Driver battery (job dir `check-*.log`): `ruff check .` PASS;
  `ruff format --check .` PASS (3277 files); focused pytest 311 passed
  3 skipped; `check-suite-inventory.py --suite packages/maistro-core/tests`
  PASS (16467 nodes).
- Focused, no PG: `test_admission_codec.py` (131 collected) +
  `test_root_admission_identity.py` (73 collected) -> **201 passed, 3 skipped**
  (the 3 PG-leg params).
- **Durable PG leg, independently reproduced on a NEW disposable database**
  `maistro_1893_v82e7ec` (name confirmed absent before CREATE) on the
  pgvector/pg18 PostgreSQL 18.6 instance at 127.0.0.1:5433:
  `DATABASE_URL=... uv run alembic upgrade head` migrated the real chain
  001->062 (68 upgrades, exit 0); reran the two focused files with
  `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` targeting that same
  database and `MAISTRO_REQUIRE_PG_LEGS=1` -> **204 passed, 0 skipped, exit 0**.
  The leg INSERTs every encoded row through both the production
  `_register_json_codecs` pool and an independent raw asyncpg pool, asserting
  identical reads from distinct sessions on the same server/database — so
  migration 055's `ck_task_idempotency_v2_identity` CHECK genuinely accepted
  the codec's encoding. Post-run SQL residue: `task_idempotency` 0 rows,
  `canonical_runs` 0 rows, `alembic_version` = 062. (Operator error, not code:
  the first attempt failed 3 tests because a single `export A=... B="$A"`
  expands `$A` before `A` is assigned, so `MAISTRO_TEST_PG_DSN` captured empty
  — the same shell-usage bug the 8b032636 round documented; rerun with
  separate exports, clean.)
- CI `test` job halves, CI env (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`,
  after `uv sync --locked --extra dev --extra bootstrap`):
  `uv run pytest tests/ --ignore=tests/tools/registry -q` -> **4971 passed,
  129 skipped, exit 0** (4m38s); `uv run pytest packages/maistro-server/tests
  packages/maistro-turing/tests packages/maistro-turing/backend/tests
  packages/maistro-design/tests packages/maistro-ext-harness/tests
  packages/maistro-ext-sdk/tests -q` -> **1849 passed, 9 skipped, exit 0**
  (1m03s). The snapshot's `test: failure` is again not reproducible at this
  head.
- `uv run mypy --strict packages/maistro-core/src` -> PASS (784 files, exit 0).
- Full `uv run python scripts/check-suite-inventory.py` -> PASS
  (17 suites match the recorded inventory; 0 duplicate/byte-identical
  evidence).
- Candidate gates: `check-reachability.py` PASS (1396 modules, 171
  unreachable); `check-reachability-dispositions.py` PASS (50 groups: 149
  CONNECT, 20 LIBRARY, 2 RETIRE); `check-promotion-surface.py` PASS;
  `check-shipped-surface-truth.py` PASS.
- Vulture, CI-exact argv (vulture-ratchet.yml:77): `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` -> PASS (1323 reviewed identities -> 1323
  findings, exit 0). The CI-repair-round permission to amend
  `quality/vulture-baseline.json` has nothing to act on.

## The one red gate, reproduced and confirmed structurally upstream

`RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
-> FAIL (exit 1), reproduced exactly: `check-reachability-provenance.py`
flags `maistro.runs.admission_identity` + `maistro.tasks.admission_codec`
(169 -> 171 unreachable) as NEW unreachable modules absent from the trusted
base, and `check-reachability-dispositions-provenance.py` flags their two NEW
dispositions as absent from the trusted ledger. No other ratchet fails.

In-branch alternatives remain prohibited: wiring the modules would violate
B2's "typed representation only" scope; editing the gate or self-authorizing
violates the issue's "no baseline/grant/gate modifications to make an unwired
slice green", and by the two-merge rule a grant added on this branch is read
from the merge base, so it can never authorize its own introduction.
Resolution stays upstream: land the reachability authorization for
`maistro.runs.admission_identity` + `maistro.tasks.admission_codec` on
develop (two-merge rule), then merge develop into `auto-1893`.

## Scope hygiene re-verified

`git diff origin/develop...HEAD` production surface is exactly:
`packages/maistro-core/src/maistro/tasks/admission_codec.py` (new, 662
lines), `packages/maistro-core/src/maistro/runs/admission_identity.py` (new,
517 lines, #1851 prerequisite), `packages/maistro-core/src/_vulture_whitelist.py`
(+32 scanner-reference lines), `packages/maistro-core/src/maistro/extensions/packs.py`
(+14 salvage guard for pack/extension identity collision, documented in
`auto-1893-d2c9.md`), the three test files, `quality/reachability-baseline.json`
(+2 rows), `quality/reachability-dispositions.json` (+1 group), and docs.
`alembic/` and `packages/maistro-server/src` are untouched on this branch. No
SQL mutation, HTTP mapping, or queue change exists in the diff. Commit
subjects against this lane: 0 matches for fixes/closes/resolves #1893; the
repair lines named by the prior rounds (`encode_admission_record` emitting
`task_id`+`run_id` together from the binding; the
`binding.receipt_id == envelope.receipt_id` guard; the round-trip test's
independent storage-shape assertions) are all present at this head and
exercised by the passing suite.

Verdict of this round: all B2 functional acceptance criteria hold at this
head under fresh independent execution, including the real-PostgreSQL
durability leg; the remaining red is the upstream two-merge sequencing only.
