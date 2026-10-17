# Issue #860 — round 25 independent revalidation (repair round)

**Not promotion evidence or integration approval.** This round independently
re-executed the deterministic battery and the promotion-gate evaluator at the
assigned head `c144a92b6a4f` (job `c567bd1788524dd7994311ff20a0acc5`), without
trusting any prior round's claims. Both blockers the previous repair round was
dispatched for remain resolved; the issue's soak acceptance remains blocked on
unchanged external prerequisites.

## Re-executed at `c144a92b6a4f` (all commands run this round)

| Command | Result |
| --- | --- |
| `git merge-base --is-ancestor bc40b6cda HEAD` (develop sync) | PASS — `bc40b6cda` is an ancestor of `c144a92b6a4f` via merge `09ed6e6da` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` (round-22 verifier argv, failed `24 == 21` at `872fd2cea`) | PASS: 38 passed, 6 skipped in 2.14 s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS (3065 files) |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | PASS: 52 tests |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests` | PASS |
| `git diff --numstat origin/develop -- quality/` | empty — no ledger rows lost |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (exact CI argv) | PASS: 1332/1332 identities, base `bc40b6cda`, candidate `c144a92b6a4f` |
| `uv run python scripts/check-backlog-consistency.py` | PASS (168 items) |
| `bash scripts/verify-monorepo-layout.sh` | PASS |
| merge-marker grep over the repaired conflict files | clean |

## Promotion-gate evaluator re-run (honesty check, both directions)

Imported the current `scripts/soak/run_soak.py` and evaluated every committed
evidence pack (`docs/testing/soak/evidence/m3a-*.json`):

- `PROMOTION_MIN_SUSTAIN_SECONDS` = **14400**.
- Every pack fails `sustain_duration` and `exact_rc_artifact` (and each fails
  at least one more gate). Best committed observation:
  `m3a-round8-prodstack-extended.json` `thresholds.checks.sustain_duration`
  records `observed_s: 1200.0, required_s: 14400, ok: false` at
  `hashes.git_head = 20c975f3b`.
- `preflight_artifact_check()` (`scripts/soak/run_soak.py:641-652`) returns
  `ok: false, topology: host-uvicorn-preflight` with "deliberately no CLI
  override" — a host-process run cannot manufacture the `exact_rc_artifact`
  gate by design.

## Why the remaining acceptance blockers are external (unchanged)

1. **AC3/AC8 (sustained soak, exact RC artifact):** 1200 s < 14400 s; no
   release-owner RC image/config designation exists; runtime config changed
   after the last observation (`b6c50ef99` Gauntlet columns merged at
   `20c975f3b`; develop M9 changes merged at `09ed6e6da`), so the issue's own
   "any code/runtime-config change requires a new soak" clause already
   invalidates the 1200 s window. No in-lane path exists: the evaluator
   hard-refuses host topology.
2. **AC5 (rate limiting cannot be bypassed by replica selection):**
   `packages/maistro-server/src/maistro_server/api/rate_limit.py` documents
   process-local enforcement per the #842 AC (aggregate = N x configured
   limit, "deliberately NOT advertised as cluster-wide"); the
   `rate_limit_enforced` gate fails on every pack. Cross-replica budget
   ownership is #842's decision, outside this lane's authority.
3. **AC9 (findings filed on GitHub):** filing is a GitHub mutation —
   prohibited in-lane. Classification is recorded locally in the round
   handoffs.

No tests were added this round (no inventory delta required); no production
code, gates, ledgers, or soak evidence were modified.
