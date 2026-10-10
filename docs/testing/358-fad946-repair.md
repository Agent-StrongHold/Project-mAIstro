# Issue #358 repair — job fad946

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-358`, branch `auto-358`.
- Starting HEAD `0ebd6c6286e94d09ba3aec4c34c38d4e779156b7`; develop base
  `ed5613457d6fa54e99d0b968b72870cb96938573` (branch merge-base with
  `origin/develop`: `790f343fa263`).
- One item: #358 / PR #1712. No GitHub mutations.
- Named CI failure to repair: **Quality gate (Pillars 1–4, 7, 8)** at
  `787dd07eb`, failing step `acceptance-state ratchet + mandate`.
- Starting tree clean; no incoming changes to salvage.

## Diagnosis (from the failing run's own log, job 113800900269)

The quality-gate job at `787dd07eb` failed on exactly one step:

```
FAIL: the repository moved away from its recorded state
  - markers_without_criterion: 3 exceeds the ceiling of 2
```

Everything else in that job (ruff, radon/xenon, version/release/doc gates,
mypy, pyright ratchet, vulture) passed. The measured `markers_without_criterion`
set was:

- `ADR-070126-6386/persist`, `ADR-070126-6386/stage3` — pre-existing on
  `develop`, inside the banked ceiling of 2 (`quality/ac-state-notes/_baseline.json`).
- `CI devskim DS126858` — introduced by this branch's own commit `787dd07eb`
  on `tests/test_check_suite_inventory.py`, a free-form `@pytest.mark.ac`
  string that names no declared `**AC-N**` criterion. That is the regression:
  the marker vocabulary is a claim that a test proves a declared criterion,
  and this test pins a scanner constraint instead.

The same CI log printed `review-time AC-state improvement observed; no bank is
required` for design coverage (44.2377 measured vs 43.8998 floor), i.e. the
improvement slack was not a failure in that review context; the markers
ceiling was the only FAIL.

## Repair

1. `tests/test_check_suite_inventory.py`: remove the unanchored
   `@pytest.mark.ac("CI devskim DS126858")` decorator. The test itself stays
   (it is load-bearing: a revert to sha1 fails a named test); the docstring
   records why no AC claim is made. Measured `markers_without_criterion`
   returns to 2, exactly on the ceiling.
2. `quality/ac-state-notes/auto-358.json`: banked this branch's own measured
   counters per the gate's prescribed flow (`check-ac-state.py --run-tests
   --ratchet --bank`), recording `markers_without_criterion: 2` and the
   design-coverage improvement. This is the per-branch measurement note the
   gate writes for each lane (37 prior notes), not a debt-ledger or grant
   amendment.

## Driver check-3 (e2e) diagnosis — environmental, not a code defect

Driver check-3 failed
`packages/hive-conductor/tests/e2e/test_pm_workflow_api.py::TestAuditTrail::test_audit_log_has_entries`
(200 where canonical expects 403) against the live server on `localhost:8101`.
That server is the compose project `project-maistro` container
(`maistro-hive-conductor`, image built 23:02 CDT) whose served route is the
old develop shape: OpenAPI shows parameters `action/severity/actor` only and a
bare-array 200 response, no `AuditPage` envelope, `limit` ignored. It was
built from the canonical clone `~/Git/Project-mAIstro` (branch
`ops/pending-tree-landings`), not from this worktree, so the e2e failure is a
stale-harness artifact. The same contract is proven against this branch's code
in-process by
`test_audit_convergence.py::test_pm_audit_contract_against_each_production_authority[legacy]`/`[canonical]`,
which runs the e2e assertion itself against both production authorities.

Fresh HTTP evidence from this worktree's code (app booted on a scratch port
from `packages/hive-conductor/backend`, then stopped):

- `test_pm_workflow_api.py::TestHealthCheck + ::TestAuditTrail`: **3 passed**.
- `/v1/audit?limit=2` → `{entries, next_cursor}` envelope, exactly 2 entries.
- `limit=100000` → clamped (retention declares `max_page_size: 200`,
  `default_page_size: 50`, `export_max_entries: 10000`, keyset ordering).
- Cursor walk with `limit=3`: no repeated ids across pages.
- Scope isolation before pagination: admin sees system+admin+pmuser entries;
  pmuser sees only own-actor entries (`scope: "own"` in retention).

## Final validation (this worktree, current HEAD + repair)

| Command | Result |
| --- | --- |
| `MAISTRO_TEST_PG_DSN=... DATABASE_URL=... RATCHET_BASE_REV=origin/develop uv run python scripts/check-ac-state.py --run-tests --ratchet` | **PASS (exit 0)**: `markers naming no criterion: 2`; `OK: 10 debt counters sit exactly on their ceilings and 1 progress counter sits exactly on its floor` |
| same + `--bank` | banked `quality/ac-state-notes/auto-358.json` |
| `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_degraded_mode_surface.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -q` | **92 passed** |
| `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -q` | **50 passed, 4 skipped** (PostgreSQL-marked skips without DSN) |
| `uv run pytest tests/test_check_suite_inventory.py -q` | **88 passed** |
| `uv run ruff check .` / `uv run ruff format --check .` | PASS / PASS (3,265 files) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,323/1,323 identities |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` / `--suite packages/hive-conductor/tests/e2e` / `--suite packages/maistro-core/tests` | PASS, recorded inventory matched (no test count changed) |

No test added or removed, so no suite-inventory delta note is required.

## Residual risks

- The driver's e2e harness container is rebuilt from the canonical clone, not
  the assigned worktree; until the harness is rebuilt from the branch,
  check-3-style live-server probes keep exercising stale code. Documented
  here and in the handoff; not fixable inside this worktree.
- Design coverage 44.2377 is now banked on this branch's note; later branches
  that measure below it must restore evidence or bank their own fall, which is
  the gate's normal flow.
