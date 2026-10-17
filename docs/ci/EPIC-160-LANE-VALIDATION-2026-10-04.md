# EPIC #160 lane validation record — 2026-10-04

Validation of the #160 epic acceptance criteria against reachable production
behavior at head `29af8200e4a8` (worktree `auto-160`, base identical). The
driver recorded no deterministic checks for this lane, so every item below was
executed inside the lane. No source or gate files were modified; this record
and the evidence it cites are the only writes.

## Per-mandate evidence

1. Full gate set on every PR (#161): `ci.yml`, `quality.yml` and
   `security.yml` all declare an unconditioned `pull_request` trigger (no
   branch or path filter), plus `merge_group` and protected-branch pushes.
   Execution evidence is enforced by `gates-ran.yml`, which re-evaluates the
   candidate on every producer completion and publishes a pending status until
   evidence is complete. Tests: `tests/test_check_gates_ran.py`,
   `tests/test_gates_ran_merge_group_scope.py`,
   `tests/test_gates_ran_publisher_contract.py`,
   `tests/test_check_required_checks.py`,
   `tests/test_check_branch_protection.py` — 155 passed.

2. Required checks / auto-merge trust set (#162): `docs/ci/REQUIRED-CHECKS.md`,
   `docs/ci/MERGE-QUEUE.md`, `enqueue-merge-queue.yml` (fail-closed per-PR
   admission behind the `Gates Ran` publisher). Same 155-test batch covers the
   evaluators.

3. Diff coverage (#163): `scripts/check-diff-coverage.py` with
   `MEASURED_ROOTS`; the workflow/declaration drift test at
   `tests/test_check_diff_coverage.py` asserts the workflow's measured roots
   equal `MEASURED_ROOTS` (line 248) and `scripts` is a measured root.
   Tests: `tests/test_check_diff_coverage.py`,
   `tests/test_m1_542_diff_coverage_edges.py` — passed.

4. AC→spec / spec→ADR chain, absent direction and registry integrity
   (#164, #812, #813, #814): executed locally, CI arguments —
   `python -m maistro_registry.cli lint . --strict` (427 files checked:
   427 clean, 0 errors, 0 warnings, 0 extra, DAG / dangling refs),
   `tools/lint_lifecycle.py` (pass), `scripts/check-adr-index.py` (OK),
   `scripts/check-adr-status-language.py` (0 baselined contradictions).
   Anchor resolution (#812) additionally covered by
   `tests/test_ac_state_anchor_resolution.py` — passed.

5. A PR proves its own declared criteria (#165): `quality.yml`
   "acceptance-state ratchet + mandate" step runs
   `check-ac-state.py --run-tests --ratchet --mandate <base sha>` on PR and
   merge-group candidates. Tests: `tests/test_check_ac_state.py`,
   `tests/test_check_ac_state_ratchet.py`, `tests/test_ac_state_*.py` —
   359 passed in the combined batch.

6. Design coverage published and ratcheted (#166):
   `quality/ac-state-notes/_baseline.json` publishes `design_coverage`
   36.5259 with `measured_with_tests: true`, and
   `criteria_claimed_but_unproven: 0`. The floor is a floored counter
   (`design_coverage@<value>`, folded by maximum) per
   `scripts/check_ac_state_impl.py`. Live behavior demonstrated: running the
   gate in ratchet mode without `--run-tests` is refused fail-closed because
   27 banked notes were measured with tests, so the counters are not
   comparable — the ratchet cannot be satisfied by an unmeasured run.

7. CI scripts themselves measured (#257): ADR-082526-9fa2 (Accepted) puts
   `scripts/` inside `MEASURED_ROOTS` with the drift test named in item 3.

8. Pytest isolated from repository-root `.env` (#300):
   `tests/test_secret_env.py` and `scripts/secret_env.py` — passed.

9. Mutation gate (#419): the `mutation_*` script family and their tests —
   109 passed, 4 skipped; 4 failures in `tests/test_mutation_baseline.py`
   were reproduced, diagnosed, and resolved as an environment artifact, see
   below. `mutation.yml` remains deliberately parked (self-hosted runners),
   with its parked-state tests conditional.

10. Autonomous-merge policy vs generated ledgers (#562):
    `tests/test_check_autonomous_merge.py`,
    `tests/test_autonomous_merge_policy_inputs.py`,
    `tests/test_autonomous_merge_quality_classes.py`,
    `tests/test_autonomous_merge_review_regressions.py` — passed.

11. Production composition integrity (#1082):
    `BaseNode.required_authorities` /
    `optional_authorities` declarations
    (`packages/maistro-core/src/maistro/graph/nodes/base.py`), consumed by
    the production resolver in
    `packages/maistro-core/src/maistro/graph/nodes/__init__.py`, which
    refuses construction when a declared authority is missing. Tests:
    `packages/maistro-core/tests/graph/nodes/test_node_composition.py`,
    `test_container_node_composition.py` — 72 passed.

12. Closure-keyword integrity (#1141): `scripts/check-closure-targets.py`
    parses GitHub closing keywords and fails when a same-repo target is an
    EPIC / MILESTONE / INITIATIVE or has sub-issues; outside pull_request
    events it skips, on API failure it fails closed.
    `tests/test_check_closure_targets.py` — passed.

## Environment artifacts encountered (not defects)

- `scripts/check-citation-status-provenance.py` exits non-zero locally
  because head equals the integration base, so the baseline would be read
  from the commit under judgement. Fail-closed by design; it needs the CI
  event's own base in `RATCHET_BASE_REV`.
- The four `test_mutation_baseline.py` failures share one cause: the
  `real_repository_ratchet_base` fixture re-exports the ambient
  `RATCHET_BASE_REV` captured at conftest import, which is unset in a local
  run, so the resolver's local fallback degenerates to head and the gate
  refuses the self-referential comparison. Re-running with the base named
  explicitly (`RATCHET_BASE_REV=<base>~1`) turns all 61 tests in
  `tests/test_mutation_baseline.py` and `tests/test_credential_authority.py`
  green, exactly as the fixture docstring prescribes.
- `check_ac_state_impl.py` line 478 emits a pre-existing `SyntaxWarning`
  (invalid escape sequence in a docstring); cosmetic, no gate fails on it.

## Commands

- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 2881 files already formatted.
- Targeted pytest batches cited per item above (total 871 passed,
  4 skipped, 0 failed after naming the ratchet base).
- Registry / ADR gates cited per item 4.
