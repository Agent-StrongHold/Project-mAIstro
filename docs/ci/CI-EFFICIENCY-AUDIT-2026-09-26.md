# CI efficiency audit: preservation and first implementation

Status: in progress, not a closure record.
Owners: #160 / #1357. Coverage/test coalescing: #1605.
Inspected baseline: `8bfd35903f497c6082bdc06d115ecefcb5d5f0b4`.

## Objective

Audit every CI workflow and its underlying commands, actions, scripts and test
profiles. Preserve every distinct validation obligation while removing
proven-equivalent repeated work. Total runner-minutes, setup/build work,
latency, queue wait and retry cost all matter. More parallel jobs alone are
not evidence of a compute saving.

## Preserve #1357 before superseding it

The current `792a580d` net patch is not the original CI refactor. Preserve its
history; do not merge its unrelated runtime/migration/test reversions.

| Historical commit | Recoverable work | Current disposition |
| --- | --- | --- |
| `b3f0ef5f` | Original check inventory, Quality/SAST decomposition, Ruff/pip-audit deduplication | Reuse the analysis; adapt selected deltas after current profile/event equivalence is established. Not ported by this slice. |
| `df7c657a` | Reusable-workflow name resolution, PostgreSQL wiring, Vulture topic-push coverage | Recover together with all relevant policy consumers before migrating reusable producers. Not ported by this slice. |
| `36a9a734` | Migrations before isolated Hypothesis; gate/scope contract repairs | Preserve these setup and contract requirements when splitting jobs. |
| `1df6d670` | Five fail-closed reusable-discovery tests | Recover with their corresponding implementation, not as unrelated tests. |
| `5e9fe962` | Pre-rollback inspection snapshot | Compare its 17-file CI delta to then-current develop; do not cherry-pick the merge wholesale. |
| `3be6e0e2` | Actual rollback despite the empty-retrigger commit message | Do not port. Classify non-CI hunks before final branch disposition. |
| `792a580d` | Vulture ledger bookkeeping | Recompute against current source rather than copy mechanically. |

Each recovered delta still needs its destination, dependency and validation
record. This table does not declare all non-CI hunks reconciled.

## First implemented reduction: Pyright

`quality.yml` ran `pyright --outputjson` and then ran the same analysis again
only to display its findings. This slice performs the original JSON scan once
and uses `scripts/check-pyright-report.py` to display the complete report and
apply the unchanged 21-error allowance.

The report consumer makes normal type-error exit 1 distinct from fatal/tool
failure. Empty/missing/malformed reports, unsupported exits, zero analyzed
files and counts that disagree with diagnostics cannot pass. Warning and
information diagnostics remain visible and do not acquire new thresholds.
Diagnostic text is JSON-escaped rather than printed as executable workflow
annotation lines.

No new job, event filter, runner, dependency, service or required context is
introduced. All workflow YAML semantics outside this one run block remain
unchanged. The source tree analyzed by Pyright is unchanged. The consumer is
rooted by its actual workflow invocation, not just by an import or a comment.

### Evidence and limits

- 63 focused tests passed locally under Python 3.13.5, including five real Bash
  executions of the workflow step with a controlled external analyzer.
- The new consumer had 69 statements and 30 branches measured, all covered.
- The fetched baseline workflow was checked against Git blob
  `96b0a657fbe201f1e7851682428a77b2f673e639` before editing. Parsed workflow
  objects differ only in the Pyright run block; the patch also clarifies two
  nonfunctional comments.
- Repository-wide Ruff, full suites, live analyzer compatibility, merge-group
  checks and runner-cost measurements remain pending. No total-CI speedup or
  net compute percentage is claimed from this focused suite.

The upstream JSON/exit contract is documented in Microsoft's Pyright
`docs/command-line.md`. The workflow does not use `--warnings` or a diagnostic
level filter, which would change that report/exit contract.

## Remaining execution map

| Work family | Evidence established | Next proof before changing execution |
| --- | --- | --- |
| Ruff | CI and Quality both invoke lint and format | Compare locked tool/config/source/event scope, then select one producer without dropping branch coverage. |
| Vulture | Quality and Vulture Ratchet invoke the same ledger checker | Preserve topic-push coverage and independent trusted-base semantics when assigning one owner. |
| pip-audit | CI and security repeat freeze/audit/gate commands | Compare resolved versions for dev and all-extras profiles; do not assume one is a safe superset. |
| Tests and coverage | Overlapping trees plus a serial collector tail | #1605 owns equivalent-profile coalescing, complete exact-candidate evidence and removal of collector test execution. |
| Isolated and same-process suites | They check different failure modes | Retain the deliberate cross-suite leakage test and required backend/version profiles. |
| Reachability, matrix and dispositions | Related inputs, distinct decisions | Share only proven-common measurement/parsing, preserving each verdict and its failure tests. |
| Image/wheel build, smoke, E2E and scanning | Potential shared artifact consumers | Prove exact build-profile identity; retain clean-install, observability-extra, trust and refreshed security-feed obligations. |
| Status publishing | Historical empty-retrigger workaround | Diagnose exact-candidate publication/reconciliation without requesting a new full validation merely to publish an existing result. |
| Other workflow families | Baseline directory inventory contains 23 workflow files | Complete recursive command/profile and cost census; directory inventory alone is not an underlying-check audit. |

Use the existing `scripts/measure-ci-cost.py` / Runner cost workflow for the
measurement authority. Record repeated executions and setup overhead as well as
wall time. Result reuse must account for candidate/base, toolchain, rules,
configuration, external security feeds and stochastic profile; an unchanged
source filename or older green SHA is not sufficient.

## Closeout boundary

This Pyright slice does not close #1357, #160 or #1605. The reusable-workflow
ports, cross-workflow deduplication, coverage producer changes and complete
underlying-check audit remain explicitly open. Required checks and trusted
policy must never be weakened to make an optimization mergeable.
