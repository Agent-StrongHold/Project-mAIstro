# PR check contract

**Status:** enforced — `scripts/check-required-checks.py` runs in `ci.yml`'s
`workflow-lint` job and fails the build when this table disagrees with
`.github/workflows/`.

This table is the contract [#162](https://github.com/Agent-StrongHold/Project-mAIstro/issues/162)
pins branch protection against. Branch protection names required checks as
**strings**; nothing in GitHub links that string back to the job that produces
it, so a renamed job silently stops being required and the protection rule keeps
reporting green. That failure is invisible by construction, which is why the
names live here and are machine-checked rather than remembered.

A check's name is its job's `name:`, or the job id when there is none — and for
a **matrix** job, the name GitHub evaluates for each combination. CodeQL's
`Analyze (${{ matrix.language }})` is three checks, not one; the generator
expands them, and refuses rather than guessing when a name uses an expression it
cannot resolve.

Two names are also refused outright: a collision between workflows (branch
protection keys checks by bare name, so two jobs sharing one give the rule an
ambiguous status to wait on) and a `matrix: exclude:`, which would need
GitHub's own matching rules to expand correctly.

Regenerate after changing a workflow:

```bash
python3 scripts/check-required-checks.py            # check (what CI runs)
python3 scripts/check-required-checks.py --update   # rewrite the table below
```

Runner cost for the check set is measured in
[`RUNNER-COST.md`](RUNNER-COST.md).

## One required check the table cannot list: `gates-ran`

`.github/workflows/gates-ran.yml` evaluates the whole required set and publishes
a Checks API result named **`gates-ran` directly onto the candidate SHA**. It is
absent from the table by construction because the generator walks workflows
reachable from either a `pull_request:` or base-trusted `pull_request_target:`
trigger, while the evaluator uses `workflow_run:`. A job inside `ci.yml` cannot
know whether `quality.yml` ran; the trusted workflow that wakes after sibling
workflows complete can.

The explicit publish step is load-bearing. A `workflow_run` job's own check is
attached to the workflow-run execution, not to the PR or merge-group SHA being
judged. Naming that job `gates-ran` is therefore not enough. The publisher uses
`checks: write` to create the required context on
`github.event.workflow_run.head_sha` after evaluating the checks on that exact
commit.

It exists because a check that never reports is not red, it is *absent*, and
absence renders as an empty space where a tick would go. On
[#242](https://github.com/Agent-StrongHold/Project-mAIstro/pull/242) a workflow
pushed with the default `GITHUB_TOKEN`, which GitHub deliberately will not use
to recursively start further workflows, and the gate set never reached the new
head. See [#262](https://github.com/Agent-StrongHold/Project-mAIstro/issues/262).

There is a deliberate bootstrap rule: **do not make `gates-ran` required live
until the publisher is already on `develop` and a fresh PR proves the custom
check appears on its actual head SHA.** GitHub loads `workflow_run` workflows
from the default branch, so the PR introducing the publisher cannot prove the
new publisher itself. Once that canary succeeds, add `gates-ran` to both the
live required set and the checked-in protection contract. Requiring it earlier
would leave every PR waiting on `Expected`.

The publisher accepts both `pull_request` and `merge_group` candidate heads, so
the same completeness check can gate the merge queue after rollout. It does not
include base-coupled checks that legitimately do not report on `develop`.

## Merge-group coverage is part of the contract

`develop` is being prepared for GitHub's merge queue. Every ordinary Actions
check required on `develop` must also be able to report on
`merge_group: checks_requested`, because the queue judges a synthetic SHA rather
than the feature-branch head.

`scripts/check-required-checks.py` now reads the reviewed `develop` required set
and fails if one of its producer workflows lacks a usable `merge_group` trigger.
It also checks `.github/merge-queue.json` for the initial `SQUASH`, one-PR-group
policy. Synthetic contexts such as `gates-ran` are tested by their own publisher
contract rather than being fabricated into this PR-job table. See
[`MERGE-QUEUE.md`](MERGE-QUEUE.md) for the staged rollout.

## Scope: what decides whether a check runs

Three values appear in the `Runs on` column, and the distinction is the whole
point of [#161](https://github.com/Agent-StrongHold/Project-mAIstro/issues/161):

- **every PR** — no trigger filter. The check is a function of the change. This
  includes base-trusted `pull_request_target` judges; the trigger changes where
  the workflow definition is loaded from, not whether the check reports on the
  PR.
- **paths** — a `paths:` filter. Still a function of the change, so still
  legitimate. See the caveat below before making one of these required.
- **base `<branch>`** — a `branches:` filter on `pull_request` or
  `pull_request_target`, which matches the PR's **base**. A check scoped this way
  means something different depending on what the PR is stacked on. Every one
  of these was removed in #161 except the deliberate exclusions named below; do
  not add another without recording why here.
- **`job if:` on base_ref** — the same coupling one level down. The workflow
  triggers on every PR, and the *job* declines to run unless the base matches.

`security.yml`'s container scan is the current job-level example. The workflow
triggers on every PR, but that job is only a real required check on the branch
where it executes.

### Resolved by #162: a check that reports `skipped`

A job that declines to run still produces a check run, with conclusion
`skipped`. Whether branch protection accepts that as satisfying a required check
depends on configuration, so **a check that can report `skipped` must not be
added to the required set without deciding that explicitly**.

**Decided:** `Container scan + SBOM + cosign` is required on `main`, not on
`develop`. Its PR job condition targets `main`, and its merge-group condition is
also main-only. The initial queue rollout is `develop` only; CodeQL and the other
release-tier details must be proven before a future `main` queue is enabled.

### Resolved by #162: paths-filtered checks and "Expected"

A required check whose workflow does not trigger never reports, and protection
leaves the candidate waiting on an `Expected` status forever. So a
**paths-filtered check must not be added to the required set as-is.**

**Decided:** both formerly paths-filtered checks were fixed rather than left
advisory. `Registry CI` lost its filter, and `Cage Guard` runs on every candidate
and passes unless the diff touches `cage/` or `eval/`.

A future `paths:`-filtered check reintroduces the hazard, so the rule stands:
make the job always run and early-exit, or record it as advisory in
`.github/branch-protection.json`.

## The checks

<!-- checks:table -->

| Workflow | Check name | Runs on |
|---|---|---|
| Autonomous Merge Safety | `autonomous-merge-admissibility` | every PR |
| CI | `docker-build` | every PR |
| CI | `durable-events` | every PR |
| CI | `hive-conductor-e2e` | every PR |
| CI | `hive-conductor-e2e-ui` | every PR |
| CI | `lint-and-type-check` | every PR |
| CI | `object storage (MinIO)` | every PR |
| CI | `postgres (pg17)` | every PR |
| CI | `postgres (pg18)` | every PR |
| CI | `security` | every PR |
| CI | `strike-ladder` | every PR |
| CI | `test` | every PR |
| CI | `wheel-imports` | every PR |
| CI | `workflow-lint` | every PR |
| Cage Guard — Auto-reject PRs touching cage/ or eval/ | `block` | every PR |
| CodeQL Advanced | `Analyze (actions)` | base `main` |
| CodeQL Advanced | `Analyze (javascript-typescript)` | base `main` |
| CodeQL Advanced | `Analyze (python)` | base `main` |
| Formal Conformance | `formal-conformance` | every PR |
| Gate C | `Gate C — canonical clean install` | every PR |
| Registry CI | `Validate ADR/spec front-matter` | every PR |
| Vulture Ratchet | `exact-debt-ledger` | every PR |
| quality | `Coverage gate (publish-set floor + diff coverage)` | every PR |
| quality | `Quality gate (Pillars 1–4, 7, 8)` | every PR |
| quality | `coverage (MinIO)` | every PR |
| quality | `coverage (PostgreSQL)` | every PR |
| quality | `coverage (no services)` | every PR |
| security | `Container scan + SBOM + cosign` | every PR, job `if:` on base_ref |
| security | `SAST (bandit + semgrep + gitleaks)` | every PR |
| security | `Supply chain (pip-audit)` | every PR |

<!-- /checks:table -->

## Deliberate exclusions

| Workflow | Why it is not on every PR |
|---|---|
| CodeQL Advanced | Deep dataflow analysis on `main` and a schedule. PRs are covered by `security.yml`'s SAST job. Before `main` gets a merge queue, CodeQL must also be proven on `merge_group`. |
| security → `Container scan + SBOM + cosign` | Builds and scans the container image; required only for the release-tier path. It is merge-group-aware for `main`, but the initial queue rollout remains `develop` only. |
| Mutation | Long-running and sampled; it is a trend instrument, not a merge gate. |
| Formal Conformance (nightly) | The per-PR `Formal Conformance` job is the gate; the nightly is a deeper sweep. |

## Draft pull requests

Draft PRs run the full set, deliberately. Skipping jobs on drafts would save
runner time, but a skipped job still produces a check run, and a required check
that reports `skipped` rather than `success` behaves differently across
protection configurations. Cost is managed by the concurrency groups instead:
superseded PR and merge-group runs cancel so repeated candidate updates do not
pile up runner work.
