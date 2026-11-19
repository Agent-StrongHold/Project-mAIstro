# REPAIR-NOTES #2361 round 2 — stale gate evidence; develop-sync verified resolved

Branch `cursor/workspace-capabilities-delete-8aa9`, head `2e7a26e31a58e44cd367b0971bef0d3919d54dae`,
PR base `469f361339e5f08a026ab744cdcddf0091a160f2` (= `origin/develop`, which has not moved).

## Dispatch blocks and what this round found

1. **"develop sync conflict preserved in worktree" — RESOLVED, no action needed.**
   `HEAD` is merge commit `2e7a26e31a` ("Merge remote-tracking branch 'origin/develop'"), with
   `git rev-list --count origin/develop ^HEAD` = 0 (develop fully contained), no unmerged index
   entries, clean worktree. `python scripts/check-merge-markers.py` → exit 0
   ("ok: no conflict markers in any tracked file"). The `<<<<<<<` grep hits are prior rounds'
   committed notes and test fixtures, not conflict residue.

2. **CI gate failure `integration-scope: failure` — STALE; green at this head.**
   GitHub run 44422658136 (pull_request, head `2e7a26e31a`) → **completed success** at
   2026-11-18T23:55Z (check-run conclusion recorded 23:55:05Z). The earlier failures
   (runs at `bc20785f52`/`a0c032ef3d`/`8aafa37e75`) predate the develop-sync merge.
   Local CI-exact classifier reproduction: `git diff --no-renames --name-only
   469f361339...HEAD` (29 paths) → `ci_merge_group_scope.py --json` →
   `check-integration-scope.py --event-name pull_request --required-json` → exit 0,
   required set `{docker-build, hive-conductor-e2e, hive-conductor-e2e-ui, wheel-imports}` —
   all four SUCCESS on GitHub at this head.

3. **`Quality / Acceptance state` — the prior round's "deterministic red" was an environment
   artifact; CI-exact local run exits 0.** Prior verifier measured design_coverage 39.8641
   locally without CI's service stack. Reproduced CI's exact invocation
   (quality.yml `quality-acceptance`): pgvector/pgvector:pg18 service, `uv sync --locked
   --all-extras`, `uv pip install -e packages/maistro-evolve pytest-timeout`,
   `alembic upgrade head` (→ 068), `RATCHET_BASE_REV=origin/develop`,
   `MANDATE_BASE_SHA=469f361339…`, `MAISTRO_TEST_PG_DSN`/`DATABASE_URL` set, then
   `python scripts/check-ac-state.py --run-tests --ratchet --mandate 469f361339…`
   → **exit 0**: design coverage **44.4608%** — exactly on the banked floor from the 50
   base notes; mandate (0 criteria newly claimed/unproven) and chain (0 absent links) clean.
   Missing DB services had been skipping AC tests locally, deflating the measurement.
   GitHub agrees: check-run 135219358588 **completed success** at this head.

4. **`exact-debt-ledger` / vulture — green; no ledger amendment performed.**
   CI-exact scan `python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
   --exclude '*/third_party/*'` → exit 0: 1235 findings / 1235 reviewed identities,
   `unclassified: 0`, `never_allowlist: 0`. GitHub check-run 135219355567 success at this head.

5. **`Coverage gate (publish-set floor + diff coverage)` — concluded success 2026-11-19T00:27:36Z**
   (check-run 135228098937) after its three producers
   (`coverage (no services)`, `coverage (MinIO)`, `coverage (PostgreSQL)`) succeeded at this
   head. Branch changes no coverage config (`git diff 469f361339...HEAD` has no
   pyproject/`.coveragerc`/conftest changes; only e2e spec, backend rum_store + tests).

## Final GitHub state at head `2e7a26e31a` (observed 2026-11-19T00:28Z)

`statusCheckRollup`: **77 SUCCESS, 3 SKIPPED** (object storage/MinIO, durable-events,
strike-ladder — service-conditional), **0 failing, 0 pending**;
`mergeStateStatus: CLEAN`, `mergeable: MERGEABLE`.

Local battery re-run this round: `uv run ruff check .` (clean), `uv run ruff format --check .`
(3580 files already formatted), `uv run pytest packages/hive-conductor/backend/tests/
test_rum_routes.py tests/test_check_frontend_typed_client.py tests/test_ratchet_provenance.py -q`
→ **103 passed**, `uv run python scripts/check-suite-inventory.py --suite
packages/hive-conductor/backend/tests` → ok (4244 identities). No tests were added this round,
so no `docs/testing/inventory-notes/` delta is required.

## Conclusion

No production-code change is warranted: every previously-red gate is now green at the assigned
head on GitHub, and the decisive ones were reproduced locally with CI's exact arguments.
This file is the only artifact of the round.
