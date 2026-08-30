# Autonomous merge safety

The autonomous merge gate answers a different question from ordinary CI:
**is this change safe to merge without a human deciding that the change itself
may redefine the evidence used to approve it?**

## Trust boundary

`.github/workflows/autonomous-merge.yml` runs on `pull_request_target`, so GitHub
loads the workflow from the protected base branch. It also checks out the exact
base SHA into `trusted/` and runs `trusted/scripts/check-autonomous-merge.py`.
The candidate is fetched only as git objects for `git diff`. Candidate code,
actions, tests, and scripts are never executed by this gate.

This matters because an autonomous author must not be able to weaken the same
workflow or script that decides whether its PR is autonomous-merge eligible.

The workflow also listens for `merge_group/checks_requested`. In merge-group
mode a trusted-surface change is rejected regardless of branch identity. Yellow
changes may enter a merge group only after the PR-time gate has already made the
autonomous-vs-human decision.

## Risk classes

### Green

Low-blast-radius changes that do not touch the trusted judge, critical execution
or persistence surfaces, dependency manifests, or test-integrity suppressions.
An agent-authored green PR is autonomous-merge eligible once the repository's
ordinary required checks are green.

### Yellow

High-blast-radius but legitimate changes, including execution, graph, runs,
scheduling, persistence, migrations, security/auth/vault/warden boundaries, and
dependency manifests/lockfiles. Adding test/type/security suppressions or
removing tests is also yellow.

The initial policy deliberately does **not** autonomously merge yellow changes.
They require a human until dedicated invariant, fault-injection, and behavioral
differential gates exist for those classes.

### Red

A change to the judge or immutable evaluation surface. This includes workflows,
local actions, branch-protection policy, the autonomous merge checker itself,
required-check/gates-ran safety scripts, quality baselines, CODEOWNERS, and the
Hive cage/eval trees.

Agent-authored red changes fail the gate. Human-authored red changes are allowed
to proceed through the ordinary manual review/merge path. A red change also
fails in merge-group mode.

## How a PR is recognized as autonomous

The gate treats these branch prefixes as agent-authored:

- `claude/`
- `chatgpt/`
- `codex/`
- `agent/` and `agents/`
- `dependabot/`
- `renovate/`

A PR can also opt in with the `autonomous-merge`, `agent-authored`, or
`automerge-agent` label. This is necessary because multiple agents may commit
through the maintainer's GitHub identity, making author identity alone
insufficient evidence.

## Test-integrity ratchet

For autonomous PRs the gate requires human review when the diff adds:

- `pytest.mark.skip`, `skipif`, or `xfail`
- `pragma: no cover`
- `# noqa`
- `# type: ignore`
- `# nosec`
- an explicit coverage-ignore marker

It also requires human review when a test definition or test file is deleted.
These operations are not automatically wrong. They are powerful enough to make
an implementation appear safer by weakening its measurement, so the initial
policy refuses to let the implementation author make that decision alone.

## Required-check configuration

`autonomous-merge-admissibility` is intentionally not generated into
`REQUIRED-CHECKS.md`: that generator currently walks `pull_request` workflows,
while this gate uses `pull_request_target` so the candidate cannot replace the
judge. Configure the check as required in GitHub branch protection/rulesets for
branches where autonomous merging is permitted.

Like `gates-ran`, the workflow first becomes live **after** the change adding it
is on the default branch, because `pull_request_target` loads the base-branch
copy. The introducing PR therefore requires a human merge. That is also the
correct outcome because it changes the trusted CI surface.
