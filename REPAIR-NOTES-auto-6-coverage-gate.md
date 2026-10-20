# REPAIR — PR #2198 / issue #6 coverage-gate round (branch `auto-6`)

Job `cad862e25bfc40fba3060859c621d54e`, 2026-10-19. Scope: the red
**Coverage gate (publish-set floor + diff coverage)** at head
`6b93ac61f721ad29eae7fb4ff0ef64211670a1bb` (job 117793059866, ran 19m37s), plus
the carried "develop sync conflict preserved in worktree" block.

## State found and preserved

- The worktree carried uncommitted prior-run test additions (audit-proof suite:
  canonical-byte behavior, `ensure_schema` idempotency, `_wire_audit_log`
  wiring contract, verify-surface cases) and a matching inventory-note bump
  (+16 → +26). Saved to the job directory as `incoming-uncommitted.patch`,
  then committed intact as `701434fc4` — nothing discarded.
- Branch was 3 commits behind `origin/develop` (`d8675ac89`, `e0cca7024`,
  `e708451b3`). Merged; **no conflicts** (develop's `container.py` rewrite and
  this branch's `_wire_audit_log` hunk auto-merged; grep-confirmed the wiring
  survives at container.py:2476/2870). Merge commit `3ca6676e3`.
- While the round ran, develop advanced again (`82da18240`, `5f714e1be`);
  merged as `d395c74d3`, also clean. Final head `d395c74d3`, 0 commits behind.

## Root cause of the CI red (reproduced, not guessed)

At `6b93ac61f` the salvage tests did not exist. Re-running the maistro-core
producer with exactly the tests that head had (10 salvage tests deselected)
reproduces the diff-gate failure on the new/changed files:

| file | pre-salvage | post-salvage (full suite) |
|---|---|---|
| `security/sentinel/signing.py` (new file, all lines changed) | 86% lines, 9 missed stmts (70,72,74,80,90,97,171,180,183), 9 partial branches → branch arcs ≈ 73.5% **< 80% floor** | 100% lines, 0 partial branches |
| `persistence/pg_audit.py` | changed lines 42-49 (`ensure_schema` body) uncovered → 88% | changed lines covered; only pre-existing develop-owned lines 88-99 (org-scoped pagination, merged from develop) uncovered |
| `security/sentinel/audit.py`, `sqlite_audit.py`, `types/security.py` | audit.py 96% (line 68) | 100% |

The gate-job timeline matches: ~19.6 min total = checkout/sync + serial
producers + the final per-file diff step; the publish-set floor aborts in the
first ~1-2 min of `combine`, so a late death points at the diff step (or a
serial producer), and the diff step failure is now reproduced locally. The
publish-set floor itself only moved **up**: every added publish-set statement
is at 94-100% coverage (signing.py 99 stmts at 100%), and CI's three producer
jobs (`coverage (no services)`, `(PostgreSQL)`, `(MinIO)`) were green at that
head.

## Validation battery at final head `d395c74d3`

- `uv run ruff check .` → All checks passed. `uv run ruff format --check .` → clean.
- `uv run pytest packages/maistro-core/tests --timeout=30 -q` (producer-equivalent, full suite): **15472 passed, 1078 skipped, 3 xfailed**.
- `uv run coverage run --append --branch --source=packages/maistro-server/src/maistro_server -m pytest packages/maistro-server/tests --timeout=30 -q`: 571 passed, 8 skipped (container-merge coupling check).
- `uv run python scripts/check-diff-coverage.py coverage.xml --base 5f714e1be` (CI's exact command, current develop tip as base) → **ok: every measured file ≥ 90% lines / 80% branch arcs**, exit 0.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` → ok, 16544 collected match recorded inventory (halved counts + per-note deltas incl. `m2-sentinel-audit-signatures.md` +26).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments) → 1321 reviewed identities = 1321 findings, exit 0. **No ledger amendment needed** (and none made).
- `uv run mypy` over the seven canonical package src trees → Success, 903 files.
- Targeted: persistence/audit/wiring/conformance suites → 142 passed, 1 skipped.

## Verdict of this round

The coverage-gate red is attributable to the missing salvage tests for the new
`signing.py` canonicalizer/signer surface and `ensure_schema`; committing the
preserved salvage closes it. Nothing was weakened: no gate edit, no ledger
edit, no threshold change; the only tree changes are tests, their inventory
note, and the develop merges.

## Residual risks

1. Serial producer legs other than maistro-core/maistro-server were not rerun
   locally (root `tests/`, hive-conductor, turing/design/registry/harness/sdk);
   CI had them green at `6b93ac61f`, and the new develop content shipped with
   its own green develop CI. A transient there re-runs in the merge queue.
2. The publish-set floor number itself cannot be computed without all three
   producer datasets locally; the argument it holds is directional (added
   statements are covered), not a measured 87% aggregate.
3. `pg_audit.py` lines 88-99 remain uncovered — develop-owned pagination code,
   outside this change's diff scope and outside the diff gate's scored lines.
