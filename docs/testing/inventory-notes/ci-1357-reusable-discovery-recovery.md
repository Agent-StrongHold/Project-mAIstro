---
inventory-delta:
  tests/: +43
---

# Recover reusable check discovery from #1357

Refs #1357 and #160. This is a prerequisite slice, not completion of the
CI-efficiency audit or the coverage work in #1605.

## Preservation provenance

The caller/callee check-name composition is adapted from `df7c657a` on the
historical #1357 branch. The five fail-closed regression scenarios introduced
by `1df6d670` are preserved as behavioral tests using valid repository-root
workflow paths: unresolved input, external workflow, missing callee, empty
callee, and unresolvable callee name. The old branch and its rollback are not
merged or rewritten. The original workflow split, PostgreSQL migration wiring,
Vulture trigger migration and broader check-policy rollout remain separate.

The current source baseline is `develop@8b494ea3f369704414561c5c26fa9a6ccd73e362`.
The fetched script was checked against Git blob
`7d791eb5bfe14bfff2a25b25a1ce0b163beb21b4` before editing.

## Supported contract

Single-level, same-revision local reusable callers emit literal caller/callee
names. Declared string inputs and literal defaults can supply callee names.
Missing or unsupported evidence is a ContractError, not an invented name.
The adaptation additionally checks callable workflow structure, path containment,
nonempty names, duplicate callee names and input-map shape. Unsupported nested,
matrix or conditional callee jobs are refused explicitly. Existing direct-job
and direct-matrix handling is unchanged. The caller remains responsible for
merge_group coverage and PR-base scope.

No workflow, trigger, job, permission, required context, baseline or service
profile changes here. This parser alone does not authorize switching production
jobs to reusable workflows: workflow-write safety, reachability and every other
policy consumer must support the selected topology before that migration.

## Executed evidence

43 focused tests pass under Python 3.13.5 with PyYAML 6.0.3 and pytest 9.0.2.
They drive the real collect() entry point over temporary workflow trees and the
real merge_group_gaps() decision over temporary protection declarations.
Coverage of all four added helper functions has no missing statements or branch
arcs in this focused run. This is not a claim of whole-script or whole-repository
100% coverage. All pre-existing function/class ASTs except collect() are
unchanged. No test count was removed to make room for these cases.

Local environment does not have the complete locked repository or Ruff. Full
repository CI, format/lint, suite inventory and independent review are still
required on the published candidate. No compute or wall-time saving is claimed
for this prerequisite; runtime deduplication remains the broader audit's goal.
