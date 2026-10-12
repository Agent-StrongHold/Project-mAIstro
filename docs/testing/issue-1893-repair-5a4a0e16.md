# Issue #1893 repair checkpoint — job 5a4a0e16

## Frozen scope

- Assigned worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `7ec0c6caedb9e00bea015da850b553887b11e5ee` (verified); supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item: #1893 B2 codec repair, focused on supplied `test: failure`, exact-debt-ledger and previously reported reachability authorization blocker.
- Review files: admission codec/identity modules, their two focused test files, existing B2 inventory notes, applicable ADRs, quality documentation and CI workflow/gate code. No unrelated issue/PR work.
- Candidate write scope: this evidence record; codec/tests only if an actual regression is reproduced; vulture ledger only if the explicitly requested scan establishes retained unbanked identities. No reachability ledger/grant changes permitted.
- Starting worktree clean; no incoming edits to salvage. No conflict/develop-sync condition established.

## Evidence and assumptions

Read the frozen dispatch issue body and supplied check logs. Driver logs show dependency sync, ruff check and format passing; focused pytest: 201 passed, 3 skipped; inventory: 16,466 nodes. These are driver observations, not fresh execution or durability proof.

Ambiguity: `test: failure` identifies no failing test or traceback. Assumption: reproduce focused tests and inspect supplied evidence before considering changes. Historical claims are not current-head validation. Production activation remains prohibited; no fake runtime caller will be added to satisfy reachability.

## Fresh validation checkpoint

- Exact requested Vulture command passed: 1,323 findings, zero unclassified, exact trusted-base match. No ledger amendment is warranted.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` failed (exit 1): admission identity and codec are both unauthorized new unreachable modules and unauthorized new dispositions (169 trusted versus 171 candidate). This reproduces the prior blocker, not a guessed scanner finding.
- Read accepted ADRs 081226-a66b, 082526-7f02 and 083126-5e62. Reconciliation: maintain the canonical execution hierarchy and immutable admission provenance; candidate ledger edits cannot grant authority. The explicit Vulture repair exception does not authorize reachability policy changes or premature production activation.

- Fresh focused pytest over both admission files: 201 passed, 3 skipped in 1.30s; skips require both database URLs.
- Fresh `uv run ruff check .`, `uv run ruff format --check .` (3,277 files) and scoped mypy (both source modules) passed.
- Fresh shipped-surface truth and core suite inventory checks passed (16,466 nodes, no duplicate evidence).
- Production-source import search finds only codec -> identity plus Vulture whitelist, not a runtime consumer. This corroborates the gate and module docstrings rather than treating test imports as reachability.
- Existing lane container `auto-1893-pg` is running pgvector/pg18 on port 15498. First read-only psql probe failed because POSTGRES_USER is unset and psql defaulted to root. Resolve using the image's default postgres account; no pre-existing database will be migrated or truncated.

## Real PostgreSQL validation

Verified that `issue1893_5a4a0e16` did not exist, then created it in the existing lane container (default image account `postgres`). No existing database was modified. The new disposable database is retained for inspection, with no test admission or Run rows remaining.

Executed on the unchanged starting source SHA:

1. `DATABASE_URL=<disposable-db-url> uv run alembic upgrade head`: PASS, full real chain from empty through 001 to 062, including forward admission migration 055. Log: job directory `repair-migrations.log`. No downgrade tests run.
2. Set nonempty `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` to that same DB, plus `MAISTRO_REQUIRE_PG_LEGS=1`. Ran `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs --junitxml=<job>/repair-pg.xml -o junit_family=legacy`: **204 passed, zero skipped**, 1.68s. Log: `repair-pg-pytest.log`. JUnit records all 204 executed nodes.
3. Independent SQL after tests: PostgreSQL 18.6, current database `issue1893_5a4a0e16`, Alembic revision `062`, `task_idempotency` count **0**, `canonical_runs` count **0**.

The production/raw pool identity pairs in JUnit are the same DB/server (`172.17.0.9/32:5432`) with distinct backend PIDs:

| State | Production PID | Raw PID | Persisted admission rows before cleanup |
| --- | --- | --- | --- |
| unbound | 44049 | 44050 | 1 |
| bound | 44051 | 44052 | 1 |
| acknowledged | 44053 | 44054 | 1 |

Each test inserted encoded bound parameters into the real migrated table, read identical named-column TEXT values through production `_register_json_codecs` and raw pools, and injected escaped lone surrogates into all three snapshot columns. Those injections failed typed/safely without changing header fingerprint evidence. This proves codec storage round trips, not authorization, admission atomicity, crash recovery or dispatch. No new test or mutation experiment was added; historical pre-fix results are not claimed as this round's execution.

## Acceptance audit

- **Interfaces / immutable DTOs:** source inspection and both focused files pass. Frozen/slotted header; six decode codes; strict UUID `.hex`, signed timestamps, validated scope-only errors; fresh flat encode mappings. Header immutability is source-verified; DTO immutability is test-proven.
- **No guessed identity:** bound/unbound/partial/receipt-only legacy tests pass. Bound pairs lacking receipt evidence fail typed rather than fabricating the receipt required by #1851. `completed_at` is ignored. V2 independent assertions verify `task_id == receipt_id` with paired `run_id`, and the real SQL constraint accepts all three valid states.
- **Header/full-decode separation:** named expiry/fingerprint preservation tests pass despite malformed snapshots and partial binding; scalar/header mismatches and unknown formats fail closed. No clock, request fingerprint, assessment or claim mutation added.
- **Strict snapshot evidence / error hygiene:** duplicate keys, nonobject roots, bare nonfinite values, precision loss, excess nesting and invalid Unicode fail typed; safe messages and suppressed parsing chains are asserted. Snapshot canonical bytes, evidence tags and stored fingerprints survive the passing round-trip tests. Arbitrary raw formatting is canonicalized, not preserved byte-for-byte.
- **Real raw/production pools:** PASS as detailed above, against real migrations and distinct same-database sessions, with zero residual rows.
- **Production evidence-json serialization and model_of/model_of_json materialization:** UNVERIFIED by this suite's manually constructed tag fixtures; no materialization path is introduced by B2.
- **Run JSONB object payload and authorized principals/Workspace/Project/registered Graph:** UNVERIFIED. These are DTO/storage tests, not positive canonical Run admission tests; no Run is created. No transaction/crash/dispatch claim follows from their passing.
- **B2 stage boundary:** no source changes this round; reviewed codec has no SQL mutation, HTTP mapping, queue/scope utility or live `_assess` change. Consumer expiry/replacement/409 ordering is C/F2, not B2 proof. Activation and external base/ownership release remain UNVERIFIED and are not authorized here.
- **Gates:** ruff check/format, scoped mypy, exact Vulture, shipped-surface and suite inventory pass. Candidate reachability and disposition scans also pass (1,396 modules / 171 unreachable / 50 groups), but the independently executed trusted-base provenance gate FAILS. A matching candidate ledger is not authorization.
- **Full required integration CI:** UNVERIFIED, not substituted by focused success. No changes to tests, inventory counts, source, gates, ledgers or grants this round, so no inventory-delta update is needed.

## Unresolved evidence and handoff

**BLOCKED.** `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613` carry two unauthorized modules relative to frozen base `3c761d14db944a727fa0744444bc67cfe36d49f7`. `.github/workflows/vulture-ratchet.yml:77` requires the failing provenance check. Resolution requires the owner-controlled trusted-base authorization process before coordinated integration; this worker cannot manufacture approval, modify those ledgers, or activate C.

The supplied generic `test: failure` is **UNRESOLVED**: captured check-run summaries show a failing `test` at linked #1855 head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, while linked #1945 head `fcc8b437f209a35aa68a61d6f0a5387414938355` reports success. Neither is the assigned SHA. No attributable assigned-head failing node/traceback is supplied by those summaries. CI's `test` job excludes the publish-set core suite (`.github/workflows/ci.yml:574-612`), so this round's 204 passes do not prove that entire job. Obtain exact failing-head diagnostics before an unrelated repair.

No develop-sync conflict existed; the conditional fetch/merge instruction did not apply. No GitHub mutation, push, policy relaxation, fake caller or speculative code repair was performed. Only this report changes. `git diff --check` passed before final report update and is repeated before committing.

Progress: checked 1 issue, done 0 repairs, skipped 0 issues, errors 1 required gate. Next: trusted-base reachability resolution and exact assigned-head CI failure diagnostics. This local commit is a blocked handoff, not integration approval.
