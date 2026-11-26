# REPAIR-NOTES #1450 round 9 — the `test` gate's npm audit step is unsatisfiable upstream; replace it with the triaged-waiver gate

Branch `auto-80`, head before this round `a910213fdecc` (already merged with
develop tip `d0e8e235a8`), 2026-11-18. Driver checks were green; the named
failure was hosted run 44221118363 job 134522924599 (`test`).

## Root cause: GHSA-fc5q-39xc-vjpf has no patched release

The failing step is `npm audit --audit-level=high` over
`packages/maistro-canvas/frontend` (the `Event loop is closed` `##[error]`
lines in the same log are the known-benign aiosqlite
`PytestUnhandledThreadExceptionWarning` annotations from
`packages/maistro-server/tests/api/test_tasks_run_identity.py`, re-derived in
rounds 8/33 and re-confirmed here: every earlier step passed).

The advisory lists *every published picomatch* as vulnerable
(`<=4.0.7`; 4.0.7 is the newest release, published 2026-08-24) with
`first_patched_version: null`, and picomatch is a hard dependency of the
frontend's dev toolchain (`vite@8.3.8` depends on `picomatch ^4.0.7`
directly; tinyglobby 0.2.17 too). Executed evidence that no lock-based
repair exists:

- `npm audit --audit-level=high` at the head: exit 1, 6 high.
- `npm audit fix --force` in a scratch copy (`/tmp/audit-test`): exit 1, and
  the resulting tree still fails — the forced fix downgrades into an older
  vite tree carrying additional launch-editor/vite advisories (1 moderate,
  4 high, 2 critical).
- develop tip carries the identical lock versions (picomatch 4.0.7, vite
  8.3.8, vitest 5.1.0): the step fails on `origin/develop` too. Develop-borne
  supply-chain landmine, not branch-borne.

This is the npm twin of the Python situation `scripts/pip_audit_gate.py`
already solved for PYSEC-2026-1325 ("upstream states there is no planned
fix"): the same shape, so the same answer — one list, one verdict.

## Repair

- `scripts/npm_audit_gate.py` (new): reads the `npm audit --json` report,
  resolves npm's "Depends on vulnerable versions of X" cascade transitively
  to root advisory IDs, and fails on any high/critical advisory whose ID is
  not in the triaged `ALLOWED` dict. npm's `fixAvailable` is quoted as the
  hint. Empty/unparseable/registry-error reports exit 3 (infrastructure —
  retry, never a clean verdict). Two-way ratchet: a waiver whose advisory
  stops being reported fails as stale, so the waiver must be deleted the
  moment picomatch ships a patch and the lock is refreshed. A future
  advisory on the same packages has a different ID and blocks until triaged.
- `.github/workflows/ci.yml` (`test` job): the audit step now writes
  `npm audit --json > /tmp/npm-audit.json || true` and
  `python scripts/npm_audit_gate.py /tmp/npm-audit.json` owns the verdict,
  mirroring the pip-audit pair at ci.yml's `security` job.
- `tests/test_npm_audit_gate.py` (new, +12 nodes, inventory note
  `docs/testing/inventory-notes/l80-npm-audit-picomatch-waiver.md`): the
  fixtures mirror the real report shape captured at this head; they caught
  two implementation defects before they could ship (cascade resolution
  seeded the cycle guard with the package itself, dropping every cascaded
  package from the verdict; npm error payloads carry `summary`, not
  `message`).

Nothing else was weakened: the gate still audits dev + production
dependencies at every severity, and the single waiver is the documented
unfixable advisory, in the house style of `ALLOWED` in
`scripts/pip_audit_gate.py` and `quality/direct-dependency-exceptions.json`.

## Local evidence (this round)

| step | command | result |
| --- | --- | --- |
| named gate, CI-exact | `npm audit --json > /tmp/npm-audit.json \|\| true` + `python scripts/npm_audit_gate.py /tmp/npm-audit.json` | rc 0, `allowed: GHSA-fc5q-39xc-vjpf ... npm audit OK (1 advisories reported, all triaged in ALLOWED)` |
| new tests | `uv run pytest tests/test_npm_audit_gate.py -q` | 12 passed |
| root suite (the step the new tests join) | `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/ --ignore=tests/tools/registry -q` | 5832 passed, 140 skipped |
| suite inventory | `python scripts/check-suite-inventory.py` (CI's exact no-argument form) | ok: 21 suites, 35504 node IDs |
| duplicates | `python scripts/check-test-duplicates.py` | ok |
| partition + wiring | `uv run pytest tests/test_unit_suite_execution_partition.py tests/test_check_wiring_reads.py -q` | 42 passed |
| ruff | `uv run ruff check .` / `uv run ruff format --check .` | pass / 3575 files formatted |
| workflow gates | `check-workflow-inventory.py`, `check-required-checks.py`, `check-merge-markers.py`, `check-doc-links.py` | all rc 0; shellcheck over the new run block clean |
| M2-B5 surface re-proven | `pytest packages/maistro-bootstrap/tests/test_container_sandbox.py test_container_sandbox_hardening.py test_container_lane.py -q` | 22 passed, 1 skipped (posture) |
| escape conformance | `uv run pytest packages/maistro-core/tests/sandbox/ -q` | 248 passed, 38 skipped (live-VM/posture-gated) |

## Deliberately not done

- `--omit=dev` on the audit step (it would pass today) was rejected: it
  silently drops ALL dev-dependency coverage forever, while the waiver gate
  keeps full coverage for every future advisory and self-removes the one
  waiver when it becomes obsolete.
- No `quality/*.json` ratchet ledger was touched: the new script lives under
  `scripts/`, outside the `packages/*/src` scan CI's vulture job runs, and
  the repository-facing ratchet self-checks in the root suite passed as-is.
