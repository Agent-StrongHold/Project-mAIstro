# Repair round: #1820 — Coverage gate failure at be901b83f

## What CI actually failed on

The merge-queue evaluation of `auto-1820` (run 39152988496, job 117754336856)
failed `Coverage gate (publish-set floor + diff coverage)`. The job log shows
this was **not** a coverage-arithmetic failure: the publish-set floor and the
diff-coverage gate were never reached. The scripts producer (root suite,
`pytest tests/ … --timeout=30 -q`) crashed on

```
FAILED tests/test_restore_oracle_characterization.py::test_real_verify_restore_drill_passes_end_to_end
[verify-restore] VERIFIER FAIL: scratch postgres did not become ready
1 failed, 5453 passed, 135 skipped in 732.25s
```

`deploy/scripts/verify-restore.sh` had started its scratch pgvector container
successfully, then expired its 60-probe (~60 s) readiness wait — on a runner
that had just executed a 12-minute root suite.

## Evidence this is congestion, not the #1820 diff

- The diff does not touch `deploy/` or the failing test
  (`git diff 420d503d...be901b83f -- deploy/ tests/test_restore_oracle_characterization.py`
  is empty).
- In the same 10-minute window (18:10–18:11Z), unrelated branches failed the
  identical job on *different* timing-sensitive tests: `auto-1821` (run
  39153019082) died on
  `tests/test_bootstrap_runtime.py::TestEnsureUv::test_interrupted_installer_stops_the_run_and_never_reports_ready`
  (pytest-timeout >30 s); `auto-1851` (run 39152966558) failed the same job
  too. One shared runner population, one failure class, three different
  victims.
- Locally (WSL host congested by ~a dozen leftover pg containers from other
  worktrees) the same producer's module fixture reproduced a sibling race
  twice: `pg_isready` answers during initdb's temporary-server window, so the
  post-probe `CREATE TABLE` hit the restart gap and failed with exit 2 —
  flipping between pass and fail across runs, then passing three consecutive
  runs after the probe hardening below.

## Repair (evidence-addressed, not cosmetic)

1. `deploy/scripts/verify-restore.sh` — scratch readiness now:
   - budgets **180 probes (~3 min)** instead of 60, so a loaded runner's slow
     initdb does not read as a verifier failure;
   - **fails fast** when the scratch container has exited
     (`docker inspect .State.Running`), dumping the engine's last 40 log
     lines — a dead container costs seconds, not the whole budget, and the
     message names the exit;
   - confirms readiness with a **real query** (`psql … SELECT 1`), not
     `pg_isready` alone, because `pg_isready` also answers during initdb's
     temporary-server window (a pg_isready-keyed loop can break mid-init and
     turn the restart gap into a bogus RESTORE failure).
2. `tests/test_restore_oracle_characterization.py::_wait_ready` — same
   hardening for the characterization fixtures (real-query confirmation,
   180-probe budget).
3. `tests/test_backup_restore_oracle.py` — two new node IDs
   (`tests/: +2`, note `docs/testing/inventory-notes/1820-restore-drill-readiness.md`):
   - `test_verify_drill_fails_fast_when_scratch_container_dies` — hermetic
     fake-`docker` shim (the #1820 harness technique); asserts VERIFIER FAIL
     names the exit, carries the engine log, and stops after few probes
     (probe *count*, not wall-clock, so the assertion does not pin host
     speed). Fail-before proven against the pre-change script: 61 probes,
     61 s, "did not become ready" instead of the exit.
   - `test_verify_drill_readiness_budget_absorbs_a_loaded_runner` — pins the
     180-probe budget, the liveness check, and the real-query probe as script
     text.

## Validation run locally

- `uv run ruff check .` — pass; `uv run ruff format --check .` — pass.
- `uv run pytest tests/test_backup_restore_oracle.py tests/test_restore_oracle_characterization.py -q`
  — 17 + 4 passed; characterization module green 3× consecutively (the drill
  end-to-end included).
- `uv run pytest packages/maistro-bootstrap/tests packages/maistro-core/tests/cli/test_upgrade.py tests/test_install_runtime_selection.py tests/test_install_compose_floor.py tests/test_install_engine_floor.py -q`
  — 391 passed, 7 skipped.
- `scripts/check-suite-inventory.py --suite tests/` (5580 collected, matches
  baseline + deltas, including this round's +2), `--suite
  packages/maistro-bootstrap/tests`, `--suite packages/maistro-core/tests` — ok.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — 1322 reviewed identities = 1322 findings
  (no delta; the repair touches no `packages/*/src` code).

The #1820 acceptance evidence itself (runtime-selection regression matrix,
rootless transcripts, support matrix in `docs/install/default-installer.md`,
evidence in `docs/install/runtime-selection-evidence-1820.md`) was re-verified
this round: all listed suites pass at be901b83f + this repair.
