# Issue #860 — round 32: independent re-validation of the lane tip at `3435f0a5b` (repair round)

**Not promotion evidence or integration approval.** The previous round ended
`NEEDS-DEEP-REVIEW`; this round re-attempted resolution of that block by
re-executing every deterministic gate at the exact assigned head
`3435f0a5b85f0b9fd3cc88b9e9a321bc75f4b24b` (tree clean at start; develop base
`df00785bb41b` still `origin/develop` — fetched, no sync conflict), replaying
the evidence pack, and re-scanning issue activity for the missing AC8
prerequisite. No prior claim was trusted without re-execution.

## Deterministic gates re-executed at head (all PASS)

| Check | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3094 files already formatted |
| `uv run python scripts/check-backlog-consistency.py` | OK — 168 items |
| `bash scripts/verify-monorepo-layout.sh` | ok: monorepo layout |
| `uv run python scripts/check-suite-inventory.py` | ok — 17 suites match |
| `git diff --numstat origin/develop -- quality/` | empty — `quality/` untouched |
| `uv run mypy` (CI's exact ten-package argv) | Success: no issues found in 1000 source files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0 — 1332 reviewed == 1332 findings |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | **56 passed** |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **38 passed, 6 skipped** (round-22 check-3 regression stays fixed) |
| `uv run pytest tests/ -q` | **4684 passed, 128 skipped** |
| `uv run pytest packages/maistro-server/tests -q` | **532 passed, 9 skipped** |
| `uv run pytest packages/maistro-core/tests -q` | **13656 passed, 969 skipped, 1 xfailed** |

## Evidence-pack replay (round-30 pack, not regenerated)

- `failed_promotion_checks(evidence/m3a-round30-shakedown.json)` →
  `['sustain_duration', 'exact_rc_artifact']` — identical to rounds 6, 26–31.
- Metrics trace: **212 rows**.
- `nginx_rendered_conf_sha256` recomputed from the committed render:
  `86291c53ab2a81fdac9e89bc4d5902bd2049039047bd0cd527e24116b19467e1` — matches
  the pack byte-exactly; `hashes.git_head=c4f45b309`, `git_clean=true`.
- Functional threshold checks re-read from the pack: exactly-once task
  admission (12 concurrent submissions → 1 distinct run, 11 duplicates,
  statuses `{202}`), two-process schedule occurrence race (1 occurrence →
  1 run, 1 loser claim, 0 multi-run occurrences), rate limiting
  (`enforced_everywhere=true`, per-replica direct probes with
  `x-ratelimit-*` headers and `Retry-After`), SIGTERM drain (1.0 s, exit 143,
  0 drain 5xx/conn errors, failover window 7.03 s, replica rejoined),
  0 non-terminal runs (2265 completed).
- `git diff --name-only c4f45b309..3435f0a5b` touches only
  `docs/testing/soak/**` — every head after the boot-hygiene fix is
  docs-only, so AC8's change clause is not re-triggered.

## AC8 block re-resolution attempt (this round's purpose)

1. **RC designation**: issue #860 comments re-scanned from the round-32
   dispatch capture (164 comments through `2026-10-06T22:40:41Z`, the latest
   activity). All are `maistro-progress` bot markers; **no release-owner RC
   designation exists**. `preflight_artifact_check` (run_soak.py:686) returns
   `ok=False` with the docstring "There is deliberately no CLI override" —
   by design, so `exact_rc_artifact` cannot pass without that external
   designation.
2. **14400 s floor**: `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`
   (run_soak.py:67) implements the issue's own AC ("at least one long-running
   soak of the exact RC artifact"); lowering it would weaken a promotion gate
   and is out of scope. A ≥ 14400 s production Compose soak exceeds the lane's
   5400 s budget and the no-background-commands rule.

**Conclusion (unchanged, now triple-confirmed):** both remaining failed
promotion checks are blocked on actors outside lane authority. No in-lane
code change can advance them; further rounds should not retry the same
battery without new external input (an RC designation or a promotion-runner
grant). Deterministic state of the branch is clean and stable at
`3435f0a5b`; promotion sign-off belongs to the release owner.
