# Issue #860 — round 31: independent verification of round 30 at `9731afbf2` (verifier round)

**Not promotion evidence or integration approval.** This round re-verified, from
scratch, every deterministic gate and every acceptance claim of round 30 at the
assigned head `9731afbf251916547877753afa7b22fc2fd43532` (tree clean, no local
edits to production or test code). No prior claim was trusted without re-execution.

## Deterministic gates re-executed at head (all PASS)

| Check (CI argv where applicable) | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3094 files already formatted |
| `uv run python scripts/check-backlog-consistency.py` | OK — 168 items |
| `bash scripts/verify-monorepo-layout.sh` | ok: monorepo layout |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | **56 passed** |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **38 passed, 6 skipped** (round-22 check-3 regression stays fixed) |
| `uv run pytest tests/ -q` | **4684 passed, 128 skipped** |
| `uv run pytest packages/maistro-server/tests -q` | **532 passed, 9 skipped** |
| `uv run pytest packages/maistro-core/tests -q` | **13656 passed, 969 skipped, 1 xfailed** |
| `uv run mypy` (CI's full ten-package argv) | Success: no issues found in 1000 source files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0 — 1332 reviewed == 1332 findings |
| `uv run python scripts/check-suite-inventory.py` | ok — 17 suites match |
| `git diff --numstat origin/develop -- quality/` | empty — `quality/` untouched |

(The six mypy complaints from a two-package narrowing are invocation artifacts:
`maistro_bootstrap`/`maistro_canvas` resolve once CI's full package list is
passed; CI's exact command is clean.)

## Discriminated-test claim re-proven independently

`tests/test_soak_promotion_gates.py`'s four boot-hygiene tests were executed
against the **pre-fix** module (`c4f45b309^` = `f11927956`, extracted to a
scratch tree, loaded via the same importlib seam the fixture uses): all four
**fail** (`resolve_out_dir`, `ensure_replica_ports_free`,
`kill_replicas_and_collect_orphans` do not exist pre-fix), and pre-fix
`boot_stack` provably raises `RuntimeError("LB did not become ready")` at
line 1172 **without killing the replicas**, while the fix commit's LB path
kills both and reports surviving orphans before raising. The same four tests
pass at head (within the 56). Discrimination holds in both directions.

## Round-30 evidence pack re-validated (not regenerated)

- `failed_promotion_checks()` replay over
  `evidence/m3a-round30-shakedown.json` → `['sustain_duration',
  'exact_rc_artifact']` — identical to the handoff's claim and to rounds 6, 26–29.
- Metrics trace: **212 rows, 0 incomplete**.
- `nginx_rendered_conf_sha256` recomputed from the committed render matches
  the pack byte-exactly (`86291c53…`).
- LB log contains only the kill-window/drain error lines; replica logs show a
  real 2.5 s boot (no "boot completed in 0.0s" orphan adoption).
- `git diff --stat c4f45b309..9731afbf2` touches only
  `docs/testing/soak/**` — the docs-only head does not change code or
  runtime config, so AC8's change clause (new soak required on code/runtime
  change) is not re-triggered.

## Acceptance state (unchanged, confirmed)

AC1 profile defined · AC2 two replicas proven · AC3 sustained-load behaviors
observed (420 s round-30 + 1200 s round-8 production stack; **14400 s
promotion floor NOT met**) · AC4 exactly-once proven (task dup + two-process
schedule race) · AC5 rate limiting proven per the decided #842 per-replica
policy · AC6 212 thresholded metric rows gated by 56 tests · AC7 drain /
bounded failover / rejoin proven · **AC8 NOT MET — external**: no
release-owner RC designation exists (checked the 162 issue comments this
round: only bot progress markers through 2026-10-06T21:55:05Z), and the
harness by design refuses host-topology equivalence
(`preflight_artifact_check` hard-fails with no CLI override), while a
promotion-signing Compose soak needs a runner window ≥ 14400 s — beyond the
lane's 5400 s budget and no-background-commands rule · AC9 findings
classified external in rounds 21–30 (GitHub filing prohibited in-lane) ·
AC10 evidence bound to exact hashes.

## Residual blockers (external to lane authority, unchanged)

1. Release-owner designation of the RC artifact/configuration (#89's
   selection) — without it `exact_rc_artifact` cannot pass **by design**.
2. A ≥ 14400 s sustained soak of that exact artifact on a production Compose
   runner — impossible in-lane.

No in-lane repair can advance these; further code changes would be cosmetic.
Lane handoff ends here; promotion sign-off belongs to the release owner.
