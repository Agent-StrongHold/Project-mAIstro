# L337 repair round — handoff (2026-10-24)

Head entering this round: e32a2068e4d7 (develop base 4de7e906d9dc). Head leaving: ce7933dac36b.

## Reproduced + fixed + proven locally
1. **Quality / Acceptance state** (`quality-acceptance`): `check-ac-state.py --run-tests --ratchet`
   failed with `markers_without_criterion: 8 exceeds the ceiling of 2`. Root cause: the
   #337 tests carried `@pytest.mark.ac("M1-E/...")` ids; no document declares an `M1-E`
   id. Fix: declared SPEC-083026-2642 AC-6..AC-10 (+ amendment paragraph, ac-modules,
   tests front-matter), re-pointed 5 markers there and `history-replica-refresh` to
   SPEC-083026-2601/AC-1 (its reload-before-read scenario). Post-fix:
   `--run-tests --ratchet --mandate 4de7e906d9dc` → OK (ratchet on ceilings, 5 new
   criteria proven, chain clean).
2. **Coverage gate** (`coverage-gate`): `check-diff-coverage.py coverage.xml --base 4de7e906d9dc`
   failed 3 files (feedback.py 85.7% lines, metrics.py 78.6%, node_metrics_store.py 70.8%
   arcs). Fix: 8 new tests (helper-door 404/503 in `_execution_identity`, retention
   endpoint, 5 store-mechanics tests). Post-fix: `ok: every measured file ... at or above
   90% lines / 80% branch arcs`. Suite +8, delta note
   `docs/testing/inventory-notes/auto-337-a36c.md`, gate green.
3. **Quality gate (Pillars 1–4, 7, 8)**: dependency of quality-acceptance → resolves with it.

## Repaired in the containers lane (evidence-based, full local chain green)
- hive-conductor Dockerfile forced `setuptools==84.0.0` after uv.lock moved to 84.2.1
  (the pin's own comment requires the lock's version). Dockerfile + security.yml
  `--member setuptools==` → 84.2.1. Rebuilt image: identity smoke OK
  (`setuptools=84.2.1`), lock reconciliation OK, trivy HIGH/CRITICAL exit 0, grype
  `--fail-on high --only-fixed` exit 0 (trivy 0.73.0, DB 2026-10-24).
- hive-conductor frontend: zod 4.4.3 < fix floor 4.6.6 (GHSA-mrhx-c7xc-m3w5, HIGH);
  package-lock → 4.6.7. `npm audit --audit-level=high` exit 0; lint/build/types.gen
  clean; npm ci sync clean in both frontends.

## NOT reproduced locally (left untouched — no evidence for a code change)
- **test** job: 15× `RuntimeError('Event loop is closed')` in CI. Reproduction attempts,
  all green locally at base and at new head: full hive suite (venv, 3966 passed; under
  coverage; fresh-resolve pins sqlalchemy 2.1.6/fastapi 0.162/starlette 1.9/anyio 4.15.1;
  clean python3.12 venv from requirements.txt alone; combined
  `pytest tests/ packages/hive-conductor/backend/tests packages/maistro-design/tests -q
  --timeout=60` → 10349 passed, 169 skipped). Canvas `npm audit --audit-level=high` → 0.
  Suspicion: runner/annotation-pooling artifact; next round should read the fresh CI log
  for the failing step names before changing anything.
- **Container scan** residual: every locally executable sub-gate passes (build, smoke,
  reconcile, trivy, grype, npm ci, frontend builds). The 2-annotation failure at
  e32a2068 may have been the setuptools drift (now fixed) or a scan-DB/runner difference;
  verify against the fresh CI run.

## Gates run green at final head
ruff check/format · full hive suite under coverage (3966 passed, 25 skipped) ·
check-ac-state (ratchet+mandate) · check-diff-coverage · check-suite-inventory (+8) ·
check-contract-markers · check-wiring-reads · check-backlog-consistency ·
check-vulture-baseline (CI args, 1302==1302) · docker build + smoke + reconcile +
trivy + grype · hive frontend lint/build/audit/types-gen.
