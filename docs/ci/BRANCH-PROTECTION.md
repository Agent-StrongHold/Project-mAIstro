# Merge-boundary protection

**Status: live and enforced.** M0 #162 uses active GitHub repository Rulesets on
`develop` and `main`. `integration` is retired.

Source of truth: [`.github/branch-protection.json`](../../.github/branch-protection.json),
checked against [`REQUIRED-CHECKS.md`](REQUIRED-CHECKS.md) by
`scripts/check-branch-protection.py` in the `workflow-lint` job. The branch-shaped
fields retain the existing offline contract audit; each branch's `ruleset` block
records the GitHub Ruleset semantics that do not exist in classic protection.

## Live topology

```text
topic branches -> develop -> main
```

`develop` is the canonical integration branch. `main` is a release/promotion
ledger and ordinarily receives one `develop -> main` PR at release time.

Both branches have strict required checks, stale-review dismissal, required
conversation resolution, restricted creation, deletion protection, and
non-fast-forward protection. `develop` remains linear. `main` deliberately
permits a release merge commit as an explicit promotion marker and therefore
does not require linear history.

`autonomous-merge-admissibility` is a first-class required PR check. `gates-ran`
is also required live on both branches; because it is produced by
`workflow_run`, it is recorded under the policy's Ruleset-only
`additional_required_checks` rather than in the generated PR-job grid below.

## Required set

● required here · ○ cannot report here · `adv` advisory by declaration.

<!-- protection:tables -->

| Branch | PR | Approvals | Linear history | Force-push | Deletion | Required checks |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `develop` | yes | **0** | yes | no | no | **17** |
| `main` | yes | **1** | no | no | no | **29** |

| Check | `develop` | `main` |
|---|:--:|:--:|
| `Analyze (actions)` | ○ | ● |
| `Analyze (javascript-typescript)` | ○ | ● |
| `Analyze (python)` | ○ | ● |
| `Container scan + SBOM + cosign` | ○ | ● |
| `Coverage gate (publish-set floor + diff coverage)` | ● | ● |
| `Gate C — canonical clean install` | ● | ● |
| `Quality gate (Pillars 1–4, 7, 8)` | ● | ● |
| `SAST (bandit + semgrep + gitleaks)` | ● | ● |
| `Supply chain (pip-audit)` | ● | ● |
| `Validate ADR/spec front-matter` | ● | ● |
| `block` | ● | ● |
| `coverage (MinIO)` | ● | ● |
| `coverage (PostgreSQL)` | ● | ● |
| `coverage (no services)` | ● | ● |
| `docker-build` | adv | ● |
| `durable-events` | adv | ● |
| `exact-debt-ledger` | ● | ● |
| `formal-conformance` | ● | ● |
| `hive-conductor-e2e` | adv | ● |
| `hive-conductor-e2e-ui` | adv | ● |
| `integration-scope` | ● | adv |
| `lint-and-type-check` | ● | ● |
| `object storage (MinIO)` | adv | ● |
| `postgres (pg17)` | adv | ● |
| `postgres (pg18)` | adv | ● |
| `security` | ● | ● |
| `strike-ladder` | adv | ● |
| `test` | ● | ● |
| `wheel-imports` | adv | ● |
| `workflow-lint` | ● | ● |

<!-- /protection:tables -->

○ means the check cannot report as a real executed check on that PR base and
therefore must not be required there. The CodeQL matrix and container image scan
are intentionally main-only.

## Review and bypass model

- `develop`: zero required approvals. Organization/repository admins retain the
  administrative bypass used for independently authorized trusted-policy
  changes that the autonomous judge correctly refuses.
- `main`: one required approval. Admin bypass is **pull-request-only**, so even
  emergency authority does not create an ordinary direct-update path to the
  release branch.
- stale approvals are dismissed after a push and review threads must be resolved.

## Behavioral evidence

The closeout proof for #162 is not merely a settings screenshot:

- PR #517 is an agent-authored trusted-policy change. On its exact head,
  `autonomous-merge-admissibility` concludes **failure** and GitHub reports the
  PR non-mergeable. This proves a PR-authoring agent cannot approve its own
  merge oracle.
- The live Rulesets require conversation resolution. Existing unresolved review
  state remains non-mergeable under the live merge boundary; `main` additionally
  requires its one explicit release approval.
- Repository auto-merge is enabled only behind this required-check/review
  boundary.

## Reconstructing the settings

Use `.github/branch-protection.json` as the reviewable contract. The `ruleset`
section records the live target, merge methods, `gates-ran`, and bypass mode;
the surrounding branch fields record strictness, review count, stale-review and
conversation behavior, creation/deletion/non-fast-forward restrictions, and the
machine-checked required contexts.

If the live settings drift, reconcile GitHub back to this artifact or amend the
ADR and artifact together. Do not silently weaken a required check to make a PR
green.
