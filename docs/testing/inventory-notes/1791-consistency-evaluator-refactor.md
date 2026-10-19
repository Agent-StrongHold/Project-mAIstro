---
inventory-delta:
  packages/maistro-design/tests: +3
---
# Refactor the consistency evaluator's three C-complexity blocks (#1791)

Three new collected cases in `packages/maistro-design/tests/test_consistency.py`
pin the extracted decision paths of the #1663 consistency evaluator at their
observable behavior, so the #1791 decomposition (17/16/15 → 8/6/6) cannot
quietly change routing:

- `test_local_sibling_contradiction_targets_both_branches` — a sibling
  contradiction neither side grounds in a consumed decision must degrade to
  LOCAL origin with the union of the two local closures as impact, in both
  match orientations; refinement routes exactly both branches with nothing
  requiring unlock. Existing coverage only had the shared-origin sibling.
- `test_locked_decision_requires_unlock_on_consumers_only` — lock state flows
  to targets through consumption edges: an unlocked artifact consuming a
  locked decision is `requires_unlock` while its own `locked` stays false, a
  mere dependent of a consumer stays freely refinable, and the
  `locked_decisions` dimension cites the decision. Existing coverage only had
  artifact-locked targets.
- `test_target_reason_merges_every_finding_touching_the_artifact` — one
  artifact hit by several errors is proposed once, with one reason per finding
  joined in finding order and exactly those finding ids attached.

Both named regression suites (#1663's evaluator suite and the
hive-conductor consistency route) pass unchanged; a normalized
findings/refinement fingerprint over eight snapshot shapes is byte-identical
before and after the refactor. No grant is raised: the three radon ledger rows
and their #1682 grants are removed (the rows became stale when the blocks
dropped below C), and the xenon block ceiling moves 137 → 134 by the same
−3, following the #1674 precedent.

## Complexity, before → after (acceptance #4)

All figures measured with the repository's configured instruments — `radon cc`
over the maistro-design source tree (the `check-radon-baseline.py` scan scope;
the file contains no `third_party` code) and xenon over the ten shipped
`packages/*/src` roots with `-i third_party` (quality.yml's exact invocation).
Re-measured at this branch's develop-sync merge `0c09af90c302` (which carries
the evaluator unchanged through two develop syncs) — not quoted from the
ledger.

The three named blocks (issue #1791, authored values from the `b4b9e187`
ledger, re-measured on base `35a72ff54`):

| Block | before | after |
|---|---|---|
| `consistency.py::_build_refinement` | C (17) | B (8) |
| `consistency.py::_check_sibling_contradictions` | C (16) | B (6) |
| `consistency.py::evaluate_project_snapshot` | C (15) | B (6) |

The seven helpers this decomposition introduced, with their measured rank
after the refactor (each was previously inline logic inside the named blocks
above, counted in that block's before figure — none exists on the base):

| New helper | after |
|---|---|
| `consistency.py::_refinement_target` | B (7) |
| `consistency.py::_evaluation_provenance` | B (6) |
| `consistency.py::_sibling_contradiction_sides` | A (5) |
| `consistency.py::_dimension_results` | A (5) |
| `consistency.py::_error_impact` | A (5) |
| `consistency.py::_sibling_shared_origin` | A (4) |
| `consistency.py::_sibling_affected` | A (2) |

No new C-or-worse block exists in the file (worst new helper: B 7), and the
project-wide xenon ceiling drops 137 → 134 block identities with zero
module-rank and zero project-average violations — matching the
`XENON_BASELINE: 134` recorded in quality.yml and pinned against the radon
ledger's length by `tests/test_complexity_gate_scope.py`.

## Gate evidence (acceptance #6)

Tested at `0c09af90c302d1dc26ca2b6052c3a75d4aed19b3` — the branch's
`Merge origin/develop (e0cca7024) into auto-1791: develop sync` commit. That
merge resolved the branch's divergence from develop (develop had absorbed this
PR's content as #2204 and added #2180 on top), so the branch tree is now
develop's tree plus this note and nothing else — the merge-queue's synthetic
base+candidate tree is identical to it (verify with
`git diff --stat e0cca7024..HEAD`). Gate results gathered here therefore apply
verbatim to the synthetic commit the queue builds.

Commands and observed results:

- `uv run radon cc -s packages/maistro-design/src/maistro_design/consistency.py`
  on base `35a72ff54`: `_build_refinement` C (17),
  `_check_sibling_contradictions` C (16), `evaluate_project_snapshot` C (15);
  at `0c09af90c`: B (8) / B (6) / B (6) plus the helper table above.
- `uv run xenon --max-absolute B --max-modules B --max-average A -i third_party`
  over the ten shipped src roots (quality.yml:1368 exact):
  base `35a72ff54` = 137 block violations; `0c09af90c` = 134 block violations,
  0 module, 0 average — equal to `XENON_BASELINE: 134`, gate passes.
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-radon-baseline.py` (CI-exact base resolution): exit 0;
  `134 reviewed C-or-worse blocks -> 134`, 0 new, 0 regressed, 0 improved,
  0 stale (base `e0cca7024`, candidate `0c09af90c`) — the earlier
  `137 -> 134` drop was banked by the #2204 merge into develop, so this
  branch now carries no radon delta at all.
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  (CI-exact arguments): exit 0, `1321 reviewed identities -> 1321 findings`
  (develop's #2180 trim accounts for the one-identity drop from 1322); no
  ledger amendment needed or made.
- `uv run pytest packages/maistro-design/tests/test_consistency.py -q`:
  22 passed. `uv run pytest
  packages/hive-conductor/backend/tests/test_design_consistency_route.py -q`:
  8 passed (acceptance #2).
- `uv run pytest tests/test_complexity_gate_scope.py -q`: 5 passed (ceiling ⇔
  ledger pin). `python scripts/check-suite-inventory.py` over all suites:
  every suite with a collectable interpreter reports ok — design 576,
  server 579 (including #2180's new startup tests), and 13 more — with the
  two hive-conductor suites erroring only on this machine's bare-`python3`
  missing pydantic (their import chain is byte-identical to `origin/develop`,
  and the same collection command gathers 3743 node IDs under the project
  venv), i.e. an environment gap, not inventory drift.
- `uv run pytest packages/maistro-server/tests/test_model_config_process_startup.py
  -q`: 6 passed (the #2180 suite this sync brought in).
- The `lint-and-type-check` job (ci.yml) that failed at the merge queue: every
  step re-run locally on `0c09af90c` — `verify-monorepo-layout.sh`,
  `check-merge-markers.py`, `mypy` over the ten canonical src trees (Success:
  no issues found in 1062 source files), `check-cross-package-imports.py`,
  `check-extension-imports.py`, `check-reference-extension.py`,
  `check-extension-scaffold.py`, `check-frontend-api-routes.py`,
  `check-frontend-typed-client.py`, `check-api-route-contracts.py`,
  `check-deployment-claims.py`, `check-secret-field-labels.py`,
  `check-retired-guidance.py`, `check-compose-secrets.py`,
  `check-compose-resources.py`, `check-durable-table-inventory.py`,
  `check-promotion-surface.py`, `check-connection-credentials.py`,
  `check-owned-store-access.py`, `check-public-routes.py`,
  `check-closure-targets.py`, `check-shell-execution.py`,
  `check-build-context.py` — all pass (both heavy extension gates included:
  the reference extension builds and tests in a clean venv, and the scaffold
  gate certifies all five family templates plus the built-in reference
  extension); `ruff check .` and `ruff format --check .` clean; `mypy` over
  the ten canonical src trees: `Success: no issues found in 1062 source
  files`. The develop-sync merges (`da3b04438` at `52f7059e`, then
  `e0cca7024` at `0c09af90c`) are the fix the gate failure was blocked on.
