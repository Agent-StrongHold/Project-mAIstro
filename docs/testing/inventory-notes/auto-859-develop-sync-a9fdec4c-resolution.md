---
inventory-delta:
  tests/: +0
  packages/maistro-turing/backend/tests: +0
  packages/maistro-turing/tests: +0
---

# auto-859-develop-sync-a9fdec4c-resolution

Repair round for #859 ([M5-A][#27] Scope Turing self-model/chat state to
canonical Workspace principals and enforce bounded state writes). The round
completed the blocked develop sync — the worktree held an **in-progress**
merge of `origin/develop` (`a9fdec4cb`) with one unmerged path:
`deploy/scripts/verify-restore.sh` — and re-proved the branch's two open
blocks at the merged head: the container-scan gate fix (`12fdab726`) and the
#859 Turing state-scoping acceptance battery. **No test node was added or
removed by this round** — the merged test files are the union of both
parents' node sets, and `scripts/check-suite-inventory.py` reports all 21
suites matching the recorded inventory at the merged head (`c8ac7339e`).

## Merge state found and completed

Three-way conflict in the scratch-Postgres readiness loop of
`deploy/scripts/verify-restore.sh` between this branch (`HEAD` =
`12fdab726`: 120-probe budget, TCP-loopback `-h 127.0.0.1` + `SELECT 1`
query, `ready`-flag guard, full `docker logs >&2 2>/dev/null`), the merge
base `bb9a7fbbc` (120 probes, socket-only query), and develop `a9fdec4cb`
(180-probe budget, socket-only query, `2>&1 | tail -40` logs, `within 180s`
message). Resolution (union, keeping the stronger half of each
independently-pinned property), committed as `c8ac7339e`:

- **TCP-loopback probe kept** (`-h 127.0.0.1` + `-d "${PG_DB}" -c 'SELECT
  1;'`): the entrypoint's temporary bootstrap server is socket-only
  (`listen_addresses=''`), so only a TCP round-trip proves the FINAL server
  answers — pinned by
  `test_scratch_readiness_probes_final_server_and_target_db` and
  `_readiness_violations`.
- **180-probe budget taken from develop** (supersedes the branch's 120),
  absorbing congested-runner initdb — pinned by
  `test_verify_drill_readiness_budget_absorbs_a_loaded_runner`
  (`READINESS_BUDGET_PROBES = 180`); the script comment records the
  reconciliation (#2185 set 120 on develop; #1820's failure class motivated
  the longer pin).
- **`docker logs … 2>&1 | tail -40 >&2` on both failure paths** (develop's
  form): the branch's `>&2 2>/dev/null` form discards the engine's stderr,
  which `test_verify_drill_fails_fast_when_scratch_container_dies` proves
  must surface (the fake-docker shim writes its FATAL line to stderr).
- Post-loop `ready`-flag guard fails as VERIFIER (`did not become ready …
  within 180s`) before `pg_restore` — pinned by
  `test_scratch_ready_means_the_target_database_answers`'s ordering
  assertion; the loop's `done` remains the first `done` in the file, so that
  test's split-based isolation still holds.

Post-merge hygiene: `scripts/check-merge-markers.py` → `ok: no conflict
markers in any tracked file`; `git diff --numstat HEAD origin/develop --
quality/` shows only the branch's intentional deltas (`image-pins.json`
9/9 pin refresh; the branch-only `ac-state-notes/auto-859.json`) — no
develop rows lost.

## Evidence at the merged head (`c8ac7339e`)

- `uv run pytest tests/test_backup_restore_oracle.py
  tests/test_restore_oracle_readiness_gate.py
  tests/test_restore_oracle_characterization.py -q` → **31 passed** against
  the resolved script.
- Container gate re-proven on the merged tree: `docker build -f Dockerfile`
  from HEAD → `trivy image --severity HIGH,CRITICAL --exit-code 1
  --ignore-unfixed --ignorefile .trivyignore.yaml` (trivy 0.73.0, DB
  2026-10-22, CI's flags) → **exit 0**; in-image `dpkg -l libexpat1` →
  `2.5.0-1+deb12u5` (the CVE-2025-59375 / CVE-2026-77214 fix the
  `12fdab726` pin refresh targets). `tests/test_pinned_digest_references.py`
  → 8 passed; `scripts/check-image-pins.py` + `check-image-inventory.py` →
  pass.
- Issue #859 acceptance battery: `packages/maistro-turing/backend/tests` +
  `packages/maistro-turing/tests` → **350 passed** (two-user/two-Workspace
  isolation, session-id guessing collapse, registry cardinality/TTL bounds,
  scope-less refusal, write-seam mood/facet boundaries, weight clamp at the
  single `store_episode` seam, replica-authority guard, restart defaults).
- Root `tests/` → **5670 passed, 140 skipped**, plus the one documented
  environmental failure
  (`test_branch_independence_repository.py::
  test_every_quality_json_state_surface_is_classified_once`): caused by the
  gitignored, locally generated `quality/ac-state.json` artifact in this
  worktree, not by any committed change — proven by moving the artifact
  aside (test passes) and restoring it. CI checkouts never materialize the
  ignored file.
- Merge-touched packages: `packages/hive-conductor/backend/tests/
  test_canonical_run_inspection.py` + `packages/maistro-bootstrap/tests` +
  `packages/maistro-core/tests/cli` → **513 passed, 7 skipped**.
- `uv run ruff check .` → all checks passed; `uv run ruff format --check .`
  → 3452 files already formatted.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact args) → `1314 reviewed
  identities -> 1314 findings`, base `a9fdec4cb`, candidate `c8ac7339e` —
  no unbanked identities, no ledger amendment needed.
- `uv run python scripts/check-suite-inventory.py` → `ok: 21 suite(s) match
  the recorded inventory`.
- `uv run mypy --strict packages/maistro-core/src` (CI's exact command) →
  `Success: no issues found in 816 source files`.
