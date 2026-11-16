# M2 #448 repair round at 244dbe1fb (inventory-ledger truth + coverage-gate proof)

Lane L448 (issue #448 → PR #2179), job 5a419b178a304ef38215fc9cf3b51eea.
Incoming state: head fe5823181 (develop-sync merge already resolved and
committed; worktree clean), last merge-queue evaluation FAILED at 56a8cec33 —
Coverage gate (publish-set floor + diff coverage), job 117729747048, and the
driver's deterministic battery failed `check-suite-inventory.py
--suite packages/maistro-core/tests` (expected 16562, collected 16531, net
−31).

## What actually failed, from the CI log (not guessed)

Fetched `actions/runs/39144525906/logs` (job 117729747048, head 56a8cec33):
the gate's `combine` step died in the root-suite producer — 4 fixture ERRORS
in `tests/test_restore_oracle_characterization.py`
(`docker exec … psql … CREATE TABLE … exit status 2`), 5377 passed/135
skipped/4 errors. The publish-set floor had already passed (the step reached
the root producer past the `--fail-under=87` check); diff coverage never ran.

That failure mode was already repaired on this branch by 2ee4033ed
(`_wait_ready` polls the statement path, not the initdb-window
`pg_isready`), documented in `auto-448-ci-repair-56a8cec3.md`.

## The −31 inventory drift was a real ledger overcount, not a host gap

`448-tools-capture-drain-helpers.md` had attributed the −31 to bwrap
capability parametrization collecting 31 fewer nodes on this host. Re-measured
on pristine develop (throwaway worktree at e708451b, removed after):
`pytest packages/maistro-core/tests --collect-only -q` → **16503**, exactly
develop's own expected, while `detect_host_capabilities()` refuses bubblewrap
here. Collection is capability-independent (no test parametrizes over live
host tiers), so the environmental story was false.

Root cause of the overcount: the develop syncs (c9a18d300, a77e2edf9,
fe5823181) adopted develop's per-stream capture policy and took its 9-test
`tests/sandbox/test_capture.py` verbatim, while the branch's own
18-test `tests/tools/sandbox/test_capture_helpers.py` landed beside it. Two
lane notes still carried pre-sync deltas (+3 in `auto-448-a9e4`, +28 in
`auto-448-c63b`) for tests that had been consolidated/verbatim-replaced —
+59 recorded against a true increment of +28 (helpers 18 + import-layering 3
+ docker 4 + microvm 3). CI would have drifted −31 at the inventory step of
the `test` job.

Repair (244dbe1fb): withdrew the stale core deltas in those two notes (rsi +7
and bootstrap +3/+2 kept — they reconcile: bootstrap 247 and rsi 1702 match
collection), and replaced the false caveat paragraph in the 448-tools note.
`check-suite-inventory.py`: **17/17 suites match** (core 16531 == expected;
tests/ 5587; full-report unique-evidence clean).

## Coverage gate proven at 244dbe1fb

- Restore-oracle leg against the real image (`pgvector/pgvector:pg17`,
  docker): `tests/test_restore_oracle_characterization.py` +
  `tests/test_backup_restore_oracle.py` → **22 passed**.
- The exact failed producer:
  `coverage run --branch --source=scripts -m pytest tests/
  tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py
  --timeout=30 -q` → **5460 passed, 138 skipped, 0 errors** (11m33s local;
  CI had 4 errors).
- Unit producer (five publish-set suites under coverage, per-package
  invocations): core 15450 passed/1078 skipped, canvas 465, evolve 998,
  rsi 1698, bootstrap 240 — combined with the scripts producer:
  publish-set-scoped `coverage report --fail-under=87` → **92%** (pass);
  whole-combined TOTAL 91%.
- `coverage xml` + `scripts/check-diff-coverage.py coverage.xml --base
  e708451b…` → **9/9 measured production files ≥90% lines / ≥80% branch
  arcs** (container_sandbox.py, settings.py, sandbox/__init__.py, fence.py,
  tools/sandbox/_capture.py, tools/sandbox/docker.py, microvm.py,
  rsi/_capture.py, rsi/local.py); 11 test files exempt by declaration.
- Vulture exact-debt-ledger with CI's exact arguments:
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → 1321 reviewed identities == 1321 findings, exit 0. No
  `quality/*.json` amendment needed (gate green without it).
- ruff check + format: clean. Targeted sandbox battery (driver check-3's
  exact argv): 120 passed.

## Residual risks

- CI's `coverage (PostgreSQL)` producer was still in progress on fe5823181 at
  capture time; the floor locally is proven on unit+scripts only, but CI's
  archive/postgres producers only ADD covered arcs for publish-set files, so
  the 92% local floor is a lower bound for CI's floor measurement.
- If origin/develop advances past e708451b before the next queue run, the
  merge-group diff base moves and the queue re-evaluates a new merge commit;
  the ledger corrections here are base-relative and remain true (deltas sum
  to the branch's own increment over whatever develop tip is merged).
- The bwrap runtime skips on this host (tests, not collection) mean local
  coverage of `sandbox/backends/bubblewrap.py` is thinner than CI's; that
  file is not in this branch's diff.
