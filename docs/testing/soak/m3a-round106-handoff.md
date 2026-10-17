# Issue #860 — round 106 (job a1929c49) independent re-validation at b2b367b429

**Not promotion evidence or integration approval.** The previous block was
"worker requested attention: BLOCKED" from job `26966253…`, whose own repair
doc (`docs/testing/soak/issue-860-26966253-repair.md`) found no evidence-based
source or ledger repair. This round resolves the block the only way it can be
resolved in-lane: by re-executing the deterministic battery fresh at the
current head without taking any earlier round's claims on trust, and by
re-verifying the two terminal blockers by construction. No source, test, or
ledger change was identified or made; this document is the only change.

## Snapshot

- Head `b2b367b429bad22f80501182fcf4e297fdd0a5c4` (round-105 handoff lineage),
  tree clean before this round's edits; supplied develop base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- This job directory contains **no `check-*.log` files**: the driver executed
  zero deterministic checks this round. Every result below was run fresh in
  this round at this head.
- **New since round 105 (head `7164c97f0b8a`): 158 commits, 39
  production-path files changed** (`git diff --name-only ed0fe24a07a0..HEAD --
  packages scripts tests deploy`, 31 of them under `packages/`). The round-100
  evidence pack is hash-bound to `ed0fe24a07a0…` (`git_clean: true`), so it no
  longer byte-binds this head. Per the issue's own rule ("any code/runtime-
  config change requires a new soak"), even the partially evidenced rows now
  require a fresh soak at whatever commit is ultimately promoted. Nothing was
  regenerated here: doing so would manufacture unhashable evidence.

## Re-executed deterministic battery at `b2b367b429` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,301 files already formatted |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml:1077-1082 exact arguments) | rc=0: **1,322 reviewed identities → 1,322 findings**, `unclassified: 0`, `never_allowlist: 0` (base `321cbdb8fe9b`, candidate `b2b367b429ba`) — no ledger amendment |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** — the historical `98a11313/check-3.log` failure (`assert 24 == 21`) still does not reproduce; skips require `MAISTRO_TEST_PG_DSN` |
| `uv run mypy <ci.yml's ten package srcs>` (exact CI arguments) | **Success: no issues found in 1057 source files** |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory |

## Blockers re-verified from harness code, not prose

`failed_promotion_checks()` imported from `scripts/soak/run_soak.py` at this
head and applied to the committed pack:

- `docs/testing/soak/evidence/m3a-round100-shakedown.json`
  (`hashes.git_head = ed0fe24a07a0…`, `git_clean = true`) → failing pair
  **`['sustain_duration', 'exact_rc_artifact']`**, now additionally stale by
  the production drift above.
- `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (`scripts/soak/run_soak.py:67`).
  A four-hour minimum cannot complete inside any single in-lane round and
  background execution is prohibited by lane rules; the soak harness itself
  is the execution authority, so no shorter run may be relabeled as the
  promotion soak.
- `preflight_artifact_check()` (`scripts/soak/run_soak.py:730-748`) returns
  `ok: false` for the host-uvicorn-preflight topology with deliberately no
  CLI override. No RC exists to soak: parent **#89 is open** and RC PR
  **#1672 is an open draft** (#1567/#1602/#2100 are merged history, none of
  them a designation).

## Contrary bounded evidence re-confirmed (unchanged product facts)

- `tests/test_soak_promotion_gates.py:439`
  (`test_replica_selection_has_an_independent_production_allowance`) passes by
  reproducing independent per-instance rate allowances for one identity:
  process-local `InMemoryRateLimiter`
  (`packages/maistro-server/src/maistro_server/api/rate_limit.py`). Cluster
  budget enforcement remains a product decision, not a soak artifact.
- `tests/test_soak_promotion_gates.py:564`
  (`test_receipt_load_reads_admitted_tasks_through_production_router`)
  reproduces a real process-local queue receipt 404 on the peer replica
  (`packages/maistro-server/src/maistro_server/api/tasks.py`). Both are
  documented in-lane findings (F/H series) and must not be reported as
  replica-resistant enforcement.

## Disposition

Acceptance rows 3 (sustained duration) and 8 (exact-RC soak) remain
**externally blocked**: they require a release-owner RC designation under the
open parent #89, a production Compose runner, and a ≥ 4 h soak window. Row 5
carries contrary product evidence (per-replica allowances). Because 39
production files changed since the round-100 soak head, rows 1-2, 4-7 and 10
must be re-evidenced at the eventual promotion commit regardless. Filing
findings on GitHub is prohibited in this lane; the F1-F12 mapping to earliest
broken invariants stays in-repo. Escalation to the release owner is unchanged.

Progress: checked 1 issue; done 0 acceptance-complete issues (rows 3, 5, 8
blocked or contrary; remaining rows require a fresh soak at the promotion
head after the drift); skipped 0; validation errors 0; escalated 1 (RC
designation under parent #89); inventory delta 0 (docs-only round, no tests
added or removed); repairs 0 (none evidenced).
