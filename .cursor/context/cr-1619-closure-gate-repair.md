# CR1619 — closure-gate repair handoff at bb8e09e26

Repair round for issue #1619 / PR #1619, branch `issue-1614-pack-extension`,
head `bb8e09e261bf81463a05b1013e66bc2c2a372338`, base `e12e11288`. Lane
CR1619. This round changed no code: the single failing required check is
caused by GitHub-side data (the PR body keyword), which the lane is prohibited
from mutating. This note hands the one-line repair to whoever holds that
authority.

## The failing check, reproduced (read, not guessed)

CI at bb8e09e26: `lint-and-type-check` = failure, all other checks success
(70+ check-runs inspected in the dispatch snapshot, including `Quality /
Ruff`, `Quality / Mypy strict`, `test`, `exact-debt-ledger`). Job log (run
40201421871 / job 121193209281) ends with:

    ##[error]closing keyword outruns the acceptance evidence: #1614's
    acceptance record shows 5 of 5 registered criteria unproven (unticked:
    AC-1, AC-2, AC-3, AC-4, AC-5); a locally green diff does not discharge
    them

Reproduced locally with CI's own script against the live PR body:

    GITHUB_TOKEN=... uv run python scripts/check-closure-targets.py \
      --body-file /tmp/pr-1619-body.md --repo Agent-StrongHold/Project-mAIstro
    -> ::error::closing keyword outruns the acceptance evidence: #1614's
       acceptance record shows 5 of 5 registered criteria unproven ...
    -> exit 1

## Root cause

- PR #1619's body opens with `Fixes #1614` (verified via `gh pr view 1619`).
- Issue #1614 ("[M7-A15] Pack extension rule ...") registers 5 acceptance
  criteria under `## Acceptance`, all unticked in its body.
- `scripts/check-closure-targets.py` refuses any closing keyword whose target
  has unticked registered criteria; the workflow comment at
  `.github/workflows/ci.yml` (step "No PR closes an epic or an issue with
  unproven acceptance by keyword") states the verdict "reads the PR body and
  the GitHub issue state only; the candidate controls neither". No tree
  change can alter this verdict.

## The repair (GitHub-side, one line)

Edit the PR #1619 body's first line from `Fixes #1614` to `Part of #1614`
(`Refs #1614` / `Progresses #1614` are equally accepted by the gate; see the
FAIL message in `check-closure-targets.py`). Proven locally:

    sed 's/^Fixes #1614$/Part of #1614/' pr-body.md > pr-body-fixed.md
    uv run python scripts/check-closure-targets.py \
      --body-file pr-body-fixed.md --repo Agent-StrongHold/Project-mAIstro
    -> ok: PR body closes no issue by keyword
    -> exit 0

The `pull_request.edited` trigger is load-bearing for exactly this: ci.yml's
comment above `types: [opened, reopened, synchronize, edited]` says a body
edit "must re-run check-closure-targets against the payload's current body".
So the gate re-runs green on the body edit alone, without a new push.

Why not instead tick #1614's boxes: that is also a GitHub mutation, and the
evidence does not support it — #1614 AC-5 demands branch
`feat/m7-a15-pack-extension`, while this PR is `issue-1614-pack-extension`;
#1614's closeout belongs to the explicit reviewed closeout process
(`check-ac-state`), not to this slice PR.

## Merge state (develop sync)

- The earlier CONFLICTING report was resolved by merge commit `25cc5373b`
  (merge of origin/develop at `e12e11288`), already on the PR head.
- origin/develop has since advanced one commit to `37b649f36` (M3-B3 Canvas
  worker). `gh pr view 1619` reports `mergeable: MERGEABLE`,
  `mergeStateStatus: BEHIND` — no conflict; a sync is routine, not a repair.
- Ledger hygiene per AGENTS.md: `git diff origin/develop...HEAD -- quality/`
  is empty — this branch adds no quality/ rows; the two-dot `quality/` diff
  against the new develop tip is develop's own commit, not dropped rows.

## Tree validation battery, all green at bb8e09e26

- `bash scripts/verify-monorepo-layout.sh` -> ok
- `python3 scripts/check-merge-markers.py` -> ok
- `python3 scripts/check-cross-package-imports.py` -> ok (3503 files)
- `uv run ruff check .` -> All checks passed!
- `uv run ruff format --check .` -> 3516 files already formatted
- `uv run mypy` over the workflow's exact 10-package list -> Success, 1106
  source files
- `uv run pytest packages/maistro-design/tests -q` -> 669 passed, 1 skipped
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-design/tests` -> ok, 670 node IDs match recorded inventory
- vulture/exact-debt-ledger: success in CI at this head; no ledger edits made.

## Issue #1619 acceptance criteria vs reachable behavior

1. Registry documents the extension rule (required rubric + graph template;
   canvas cannot be pack_id) -> `packages/maistro-design/src/maistro_design/
   packs/registry.py`: `LEGACY_REQUIRED_FIELDS`, `_require_contract_fields`
   (raises on missing fields and on pack_id in {canvas, atelier, design_run});
   tests `test_missing_rubric_is_rejected`, `test_canvas_cannot_be_a_pack_id`.
   Proven.
2. Five new manifests plus product/game/book load through one registry ->
   `packs/catalog/*.json` (book, game, interactive, novel, product,
   small_business, training_program, website) all load via
   `load_bundled_packs()`; `test_bundled_packs_load_through_one_registry`
   asserts the exact 8-id set against the real bundled files. Proven.
3. Same Goal bound to game, novel, training_program, product shares identity
   scheme -> `test_same_goal_two_packs_share_identity_scheme` binds one goal
   id through the real registry and asserts shared `goal_id` /
   `run_identity: canonical` with differing rubric dimensions. Proven.
4. Adding a pack does not add a package or Design Studio route -> the branch
   diff vs develop adds files only under `packages/maistro-design` plus one
   `docs/testing/inventory-notes/` delta; no new `packages/maistro-<pack>`,
   no route or workflow changes. Proven structurally.
5. (unticked, by design) Full Graph/Run execution belongs to M1 spine + #795
   -> #795 is open; the registry enforces shared canonical Run identity
   (`test_noncanonical_run_identity_is_rejected`) and advertises no
   execution. Correct deferral, not a gap.
