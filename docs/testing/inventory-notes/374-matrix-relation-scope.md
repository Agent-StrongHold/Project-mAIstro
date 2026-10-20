---
inventory-delta:
  tests/: +171
---
# #374 matrix relation scope repair

## Frozen scope

Process only issue #374 at starting head
`c3af929a26da1e17cada1549aea84145a55342ed`: repair the demonstrated matrix
historical-note bypass in `scripts/check-citation-status.py`, add regression
coverage in `tests/test_check_citation_status.py`, and record validation here.
Inspect registry citations/tests, ADR governance and CI gate configuration as
context. Amend `quality/vulture-baseline.json` only if the explicitly requested
exact-debt-ledger check identifies reviewed retained/deleted identities.

## Initial evidence / assumptions

- Assigned worktree is clean; no preserved conflict or uncommitted salvage exists.
- `git fetch origin` succeeded; `origin/develop` resolves to the supplied base
  `176043b01e3627735b8db8b07ef022a0f1d4843c`. `git merge origin/develop`
  reports `Already up to date`; no conflict-resolution commit is necessary.
- Current job directory contains no `check-*.log` files. Prior result artifact
  confirms the mixed-parenthetical bypass; earlier validation claims will be rerun.
- Preserve the canonical execution model; this is documentation validation only.

## Repair and policy

ADR-031 makes front-matter relationships canonical; ADR-097 supplies the status
machine. Existing Accepted/Implemented authority policy is preserved (Implemented
is a post-acceptance status, not an alternative acceptance path). No runtime
execution or authorization authority changes.

Matrix exemptions now bind only to directly qualified IDs or comma-only lists.
Semicolons, parentheses, and intervening prose terminate the relation. Lists such
as `(proposed in ADR-002, SPEC-003)` retain their explicit shared provenance;
`(historical ADR-002; ADR-003)` does not qualify ADR-003. Unknown forms fail closed.

## Validation

- Before repair: `uv run pytest tests/test_check_citation_status.py --collect-only -q`
  collected 75 nodes.
- Red regression: `uv run pytest tests/test_check_citation_status.py -x -q -k
  matrix_relation_does_not_exempt_unqualified_neighbor` failed on the exact
  reported Proposed target; actual problems were `[]` instead of ADR-003.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence
  60 --exclude '*/third_party/*'`: PASS, 1405 findings, zero unclassified or
  never-allowlist findings. No new unbanked or stale retained identities to amend.

### Post-repair results

- `uv run pytest tests/test_check_citation_status.py -x -q`: 246 passed
  (75 before; measured delta +171). Includes all 144 source/target status pairs,
  36 mixed-note cases through the CI entry point, and three explicit-relation
  cases. The status truth table uses an independent explicit policy oracle.
  Supersession transitions also verify that retargeting remains invalid while
  the successor is Proposed and succeeds once Accepted. Cycles and
  contradictory branches are covered by the existing tests.
- `uv run ruff check .` and `uv run ruff format --check .`: PASS.
- `uv run python scripts/check-citation-status.py`: PASS, zero exceptions.
- `uv run pytest packages/maistro-registry/tests tests/tools/registry
  tests/tools/test_lint_lifecycle.py -x -q --confcutdir=tests/tools`: 98 passed.
- `RATCHET_BASE_REV=176043b01e3627735b8db8b07ef022a0f1d4843c uv run python
  scripts/check-citation-status-provenance.py`: PASS, 46 reviewed exceptions
  at trusted base to zero current exceptions; no baseline expansion.
- `uv run python scripts/check-convergence-matrix.py`: PASS, 52 subsystems,
  1135 production modules; `uv run python tools/lint_lifecycle.py`: PASS,
  zero baseline exceptions.
- `uv run python -m maistro_registry.cli lint . --strict`: PASS, 411 clean
  documents, zero errors/warnings/DAG/dangling-reference findings.
- `uv run pytest tests/test_check_citation_status.py tests/test_check_reachability.py
  tests/test_m1_542_policy_coverage.py -x -q`: 286 passed.
- `uv run python scripts/check-suite-inventory.py --suite tests/` before recording
  delta: expected 3816, collected 3987, exactly the +171 added nodes. Delta
  recorded above; recheck PASS, expected and collected both 3987.
- Additional `uv run mypy packages/maistro-registry/src` failed because installed
  `maistro.http` lacks stubs/py.typed; no changed source involved. Resolved by
  supplying its source path: `MYPYPATH=packages/maistro-core/src uv run mypy
  packages/maistro-registry/src` PASS (9 source files), with no suppression.
- `uv run python scripts/check-merge-markers.py`: PASS, no tracked conflict
  markers. `git diff --check`: PASS.

## Acceptance and residual scope

- Allowed relationships/source/target status policy: registry definitions and
  exhaustive status tests; `substrate`/`implements` normative, `related` and
  `supersedes` historical/navigational tests pass.
- Governing citations require active accepted authority: executed corpus gate
  and strict link/lifecycle gates pass, zero citation exceptions. Implemented
  remains valid as a post-acceptance lifecycle state under ADR-097.
- Proposed cannot silently govern: exact reported negative regression reproduced
  before repair and rejected through `main([])` after repair, also exercising
  Deprecated/Superseded and an Accepted control.
- Superseded citations name the active successor; chain/cycle/contradictory
  branch tests and transition-to-Accepted tests execute the registry checker.
- Historical citations remain possible: explicit relation/list tests and the
  live matrix pass; adjacent unqualified references remain governing.
- Canonical active spec/AC governing relationships and matrix citations pass the
  corpus gates; 14 existing prose-disclaimer regressions also pass. ADR-031
  makes front matter canonical; this repair does not invent a general natural-
  language authority parser for arbitrary Markdown prose.
- Hosted CI/integration approval is not claimed. No GitHub mutation or push.

Final focused rerun: `uv run ruff check .`, `uv run ruff format --check .`,
`uv run pytest tests/test_check_citation_status.py packages/maistro-registry/tests
-x -q` (251 passed), `uv run python scripts/check-suite-inventory.py --suite tests/`,
`uv run python scripts/check-citation-status.py`, and `git diff --check` all PASS.

Checkpoint: checked 1 assigned issue, done 1 repair, skipped 0, unresolved errors 0.
Ready for local commit and independent handoff review, not integration approval.




