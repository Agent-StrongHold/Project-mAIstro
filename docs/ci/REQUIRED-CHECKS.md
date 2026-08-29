# PR check contract

**Status:** enforced — `scripts/check-required-checks.py` runs in `ci.yml`'s
`workflow-lint` job and fails the build when this table disagrees with
`.github/workflows/`.

This table is the contract [#162](https://github.com/Agent-StrongHold/Project-mAIstro/issues/162)
pins merge rules against. Required checks are names, so a renamed job can silently
detach from the rule unless this contract is kept machine-checked.

The generator includes both `pull_request` and base-trusted `pull_request_target`
workflows. The latter is required for judges such as Autonomous Merge Safety,
whose definition must come from the protected base rather than the candidate.

Regenerate after changing a workflow:

```bash
python3 scripts/check-required-checks.py
python3 scripts/check-required-checks.py --update
```

## One required context the table cannot list: `gates-ran`

`.github/workflows/gates-ran.yml` is intentionally a `workflow_run` publisher,
so it is absent from the generated PR-job table by construction. Its native job
runs from the protected default branch and is named `gates-ran-publisher`.
After evaluating the exact triggering PR or merge-group candidate with trusted
default-branch code, it publishes the required **`gates-ran`** commit-status
context onto that candidate SHA. Both live protected branches require that
context.

This distinction is deliberate. A `workflow_run` job's native check is attached
to the default-branch execution; requiring that native check on a candidate
would wait for a context that can never report where merge enforcement looks.
Publishing the aggregate verdict onto the triggering candidate SHA keeps the
judge protected while putting the result exactly where GitHub evaluates it.

`gates-ran` is stricter than GitHub's raw required-check semantics: GitHub treats
a skipped required check as successful, while this aggregate requires real
execution evidence. On `main` promotions it also includes the main-only CodeQL
and container-scan checks; those are excluded on `develop` candidates where they
do not execute by design.

For merge groups, the initial trusted resolver is intentionally **develop-only**.
It accepts GitHub queue refs under `gh-readonly-queue/develop/` and refuses any
other merge-group base. A future `main` queue must extend this resolver in the
same reviewed change that makes the release-tier checks merge-group capable.

## Merge-group coverage is part of the develop contract

The merge queue judges a synthetic current-base + candidate SHA rather than the
feature-branch head. Every ordinary Actions check required on `develop` must
therefore also handle:

```yaml
merge_group:
  types: [checks_requested]
```

`scripts/check-required-checks.py` enforces this from the checked-in
`.github/branch-protection.json` required set. It also reads
`.github/merge-queue.json` and pins the initial queue to `SQUASH` with one PR per
merge group. A future required check cannot silently become PR-only while the
queue waits forever for an `Expected` context.

Synthetic aggregate contexts such as `gates-ran` are covered by their trusted
publisher contract rather than fabricated into the PR-job table below. See
[`MERGE-QUEUE.md`](MERGE-QUEUE.md) for the live canary sequence.

## Scope

- **every PR** — reports for every pull request, including base-trusted
  `pull_request_target` judges.
- **base `<branch>`** — the workflow trigger is coupled to the PR base.
- **`job if:` on base_ref** — the workflow triggers broadly but that job only
  runs on the named base.

A check that cannot report on a branch must not be required there, or GitHub can
wait forever for an `Expected` result.

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

## Deliberate base-coupled checks

`Analyze (actions)`, `Analyze (javascript-typescript)`, `Analyze (python)`, and
`Container scan + SBOM + cosign` are required on `main` only. They do not report
as real executed checks on a `develop`-based PR or develop merge group.

## Draft pull requests

Draft PRs run the required workflow set deliberately. Cost is controlled with
workflow concurrency cancellation rather than changing the meaning of a
required check between draft and ready states. Merge-group runs use the same
supersession policy so stale synthetic candidates do not pile up runner work.
