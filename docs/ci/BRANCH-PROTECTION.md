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

Two required checks sit outside the generated PR-job grid below because their
publishers do too: `gates-ran` is produced by `workflow_run` and is recorded
under the policy's Ruleset-only `additional_required_checks`, while
`autonomous-merge-admissibility` — required live on `main`, but its former
`pull_request_target` producer is disabled — is not declared in the policy at all. Both facts
are visible in the read-back region below and recorded in `known_live_drift`.

## Required set

● required here · ○ cannot report here · `adv` advisory by declaration.

<!-- protection:tables -->

| Branch | PR | Approvals | Linear history | Force-push | Deletion | Required checks |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `develop` | yes | **0** | yes | no | no | **25** |
| `main` | yes | **1** | no | no | no | **39** |

| Check | `develop` | `main` |
|---|:--:|:--:|
| `Analyze (actions)` | adv | ● |
| `Analyze (javascript-typescript)` | adv | ● |
| `Analyze (python)` | adv | ● |
| `Compliance registry` | ● | ● |
| `Container scan + SBOM + cosign` | ○ | ● |
| `Coverage gate (publish-set floor + diff coverage)` | ● | ● |
| `DevSkim` | adv | ○ |
| `Gate C — canonical clean install` | ● | ● |
| `JS supply chain (npm audit + GuardDog + policy gate)` | ● | ● |
| `Mutation gate (changed critical lines)` | ○ | ○ |
| `Quality / Acceptance state` | adv | adv |
| `Quality / Agent store writes` | adv | adv |
| `Quality / Architecture fitness` | adv | adv |
| `Quality / BFCL provenance` | adv | adv |
| `Quality / Backlog consistency` | adv | adv |
| `Quality / Contract markers` | adv | adv |
| `Quality / Convergence matrix` | adv | adv |
| `Quality / Credential authority` | adv | adv |
| `Quality / Docstring coverage` | adv | adv |
| `Quality / Documentation links` | adv | adv |
| `Quality / Enumeration coverage` | adv | adv |
| `Quality / Execution lifecycles` | adv | adv |
| `Quality / Foreign-harness egress` | adv | adv |
| `Quality / Frontend typed client` | adv | adv |
| `Quality / Hypothesis` | adv | adv |
| `Quality / IFEval provenance` | adv | adv |
| `Quality / Image inventory` | adv | adv |
| `Quality / Image pins` | adv | adv |
| `Quality / Installed proof CLI` | adv | adv |
| `Quality / Model egress` | adv | adv |
| `Quality / Mypy strict` | adv | adv |
| `Quality / Principal identity` | adv | adv |
| `Quality / Pyright` | adv | adv |
| `Quality / Radon` | adv | adv |
| `Quality / Reachability` | adv | adv |
| `Quality / Reachability dispositions` | adv | adv |
| `Quality / Release consistency` | adv | adv |
| `Quality / Route permissions` | adv | adv |
| `Quality / Ruff` | adv | adv |
| `Quality / Security inventory` | adv | adv |
| `Quality / Selected model-call CLI` | adv | adv |
| `Quality / Version consistency` | adv | adv |
| `Quality / Vulture` | adv | adv |
| `Quality / Wiring reads` | adv | adv |
| `Quality / Workflow inventory` | adv | adv |
| `Quality / Workspace retirement` | adv | adv |
| `Quality / Xenon` | adv | adv |
| `Quality gate (Pillars 1–4, 7, 8)` | ● | ● |
| `SAST (bandit + semgrep + gitleaks)` | ● | ● |
| `SAST / Bandit` | adv | adv |
| `SAST / Gitleaks` | adv | adv |
| `SAST / Semgrep` | adv | adv |
| `Supply chain (pip-audit)` | ● | ● |
| `Validate ADR/spec front-matter` | ● | ● |
| `block` | ● | ● |
| `coverage (MinIO)` | ● | ● |
| `coverage (PostgreSQL)` | ● | ● |
| `coverage (design + registry + extensions)` | ● | ● |
| `coverage (hive-conductor backend)` | ● | ● |
| `coverage (no services)` | ● | ● |
| `coverage (scripts producer)` | ● | ● |
| `coverage (server + turing)` | ● | ● |
| `cross-product-parity` | ● | ● |
| `docker-build` | adv | ● |
| `docker-rebuild-compare` | adv | ● |
| `durable-events` | adv | ● |
| `exact-debt-ledger` | ● | ● |
| `formal-conformance` | ● | ● |
| `hive-conductor-compose-durability` | adv | ● |
| `hive-conductor-e2e` | adv | ● |
| `hive-conductor-e2e-ui` | adv | ● |
| `integration-scope` | ● | adv |
| `lint-and-type-check` | ● | ● |
| `object storage (MinIO)` | adv | ● |
| `postgres (pg17)` | adv | ● |
| `postgres (pg18)` | adv | ● |
| `pr-base` | adv | adv |
| `sandbox-conformance` | ● | ● |
| `security` | ● | ● |
| `strike-ladder` | adv | ● |
| `test` | ● | ● |
| `wheel-imports` | adv | ● |
| `workflow-lint` | ● | ● |

<!-- /protection:tables -->

○ means the check cannot report as a real executed check on that PR base and
therefore must not be required there. `adv` means the workflow reports on that
base but is deliberately advisory; `DevSkim` remains outside both required sets
until the owner promotes it into the merge contract. The CodeQL matrix and
container image scan are intentionally main-only.

## Live read-back

Rendered from [`.github/live-merge-boundary.json`](../../.github/live-merge-boundary.json), a recorded read of the live repository rulesets and classic protection taken with `python3 scripts/check-branch-protection.py --refresh-live`. The generated region above says what the policy *declares*; this one says what GitHub *enforced* when it was read.

Where the two disagree, the divergence is written down — with a reason and an owner — under `known_live_drift` in `.github/branch-protection.json`. An unrecorded divergence fails `scripts/check-branch-protection.py` in CI, and so does a recorded one that no longer exists, so the record cannot outlive its fact. CI compares against the committed read-back (a pull request has no admin-scoped token). **This offline consistency check does not prove policy compliance.** `--verify` re-reads GitHub and fails on every declared-vs-live divergence, even a documented one, or a stale read-back. Explicit live verification without credentials fails rather than reporting success. No snapshot refresh or exception note authorizes a policy change.

The divergences recorded today are not cosmetic: six checks the policy declares required on each branch are not required by the live rulesets, the live merge queue is wider than the reviewed batching posture on five parameters, and `main` requires an
`autonomous-merge-admissibility` check whose producer workflow is disabled. Each carries its reason and owner in `known_live_drift`; none of them is closed by editing this document.

<!-- protection:live -->

| Branch | Ruleset | Enforcement | Approvals | Stale dismissal | Code-owner review | Last-push approval | Merge methods | Required checks (live) |
|---|---|:--:|:--:|:--:|:--:|:--:|---|:--:|
| `main` | Main merge | active | **1** | yes | no | no | merge, rebase, squash | **31** |
| `develop` | Pr merge | active | **0** | no | no | no | rebase, squash | **25** |

| Check | `main` | `develop` |
|---|:--:|:--:|
| `Analyze (actions)` | ● | - |
| `Analyze (javascript-typescript)` | ● | - |
| `Analyze (python)` | ● | - |
| `Compliance registry` | - | - |
| `Container scan + SBOM + cosign` | ● | - |
| `Coverage gate (publish-set floor + diff coverage)` | ● | ● |
| `DevSkim` | - | - |
| `Gate C — canonical clean install` | ● | ● |
| `JS supply chain (npm audit + GuardDog + policy gate)` | - | - |
| `Mutation gate (changed critical lines)` | - | - |
| `Quality / Acceptance state` | - | - |
| `Quality / Agent store writes` | - | - |
| `Quality / Architecture fitness` | - | - |
| `Quality / BFCL provenance` | - | - |
| `Quality / Backlog consistency` | - | - |
| `Quality / Contract markers` | - | - |
| `Quality / Convergence matrix` | - | - |
| `Quality / Credential authority` | - | - |
| `Quality / Docstring coverage` | - | - |
| `Quality / Documentation links` | - | - |
| `Quality / Enumeration coverage` | - | - |
| `Quality / Execution lifecycles` | - | - |
| `Quality / Foreign-harness egress` | - | - |
| `Quality / Frontend typed client` | - | - |
| `Quality / Hypothesis` | - | - |
| `Quality / IFEval provenance` | - | - |
| `Quality / Image inventory` | - | - |
| `Quality / Image pins` | - | - |
| `Quality / Installed proof CLI` | - | - |
| `Quality / Model egress` | - | - |
| `Quality / Mypy strict` | - | - |
| `Quality / Principal identity` | - | - |
| `Quality / Pyright` | - | - |
| `Quality / Radon` | - | - |
| `Quality / Reachability` | - | - |
| `Quality / Reachability dispositions` | - | - |
| `Quality / Release consistency` | - | - |
| `Quality / Route permissions` | - | - |
| `Quality / Ruff` | - | - |
| `Quality / Security inventory` | - | - |
| `Quality / Selected model-call CLI` | - | - |
| `Quality / Version consistency` | - | - |
| `Quality / Vulture` | - | - |
| `Quality / Wiring reads` | - | - |
| `Quality / Workflow inventory` | - | - |
| `Quality / Workspace retirement` | - | - |
| `Quality / Xenon` | - | - |
| `Quality gate (Pillars 1–4, 7, 8)` | ● | ● |
| `SAST (bandit + semgrep + gitleaks)` | ● | ● |
| `SAST / Bandit` | - | - |
| `SAST / Gitleaks` | - | - |
| `SAST / Semgrep` | - | - |
| `Supply chain (pip-audit)` | ● | ● |
| `Validate ADR/spec front-matter` | ● | ● |
| `block` | ● | ● |
| `coverage (MinIO)` | ● | ● |
| `coverage (PostgreSQL)` | ● | ● |
| `coverage (design + registry + extensions)` | - | - |
| `coverage (hive-conductor backend)` | - | - |
| `coverage (no services)` | ● | ● |
| `coverage (scripts producer)` | - | - |
| `coverage (server + turing)` | - | - |
| `cross-product-parity` | - | - |
| `docker-build` | ● | ● |
| `docker-rebuild-compare` | - | - |
| `durable-events` | ● | ● |
| `exact-debt-ledger` | ● | ● |
| `formal-conformance` | ● | ● |
| `hive-conductor-compose-durability` | - | - |
| `hive-conductor-e2e` | ● | ● |
| `hive-conductor-e2e-ui` | ● | ● |
| `integration-scope` | - | - |
| `lint-and-type-check` | ● | ● |
| `object storage (MinIO)` | ● | ● |
| `postgres (pg17)` | ● | ● |
| `postgres (pg18)` | ● | ● |
| `pr-base` | - | - |
| `sandbox-conformance` | - | - |
| `security` | ● | ● |
| `strike-ladder` | ● | ● |
| `test` | ● | ● |
| `wheel-imports` | ● | ● |
| `workflow-lint` | ● | ● |

Required live but published outside the PR-job grid (a `workflow_run` or `pull_request_target` publisher):
- `autonomous-merge-admissibility` on `main`
- `gates-ran` on `main`

<!-- /protection:live -->

## Review and bypass model

- `develop`: zero required approvals. Organization/repository admins retain the
  administrative bypass used for independently authorized trusted-policy
  changes that the autonomous judge correctly refuses.
- `main`: one required approval. Admin bypass is **pull-request-only**, so even
  emergency authority does not create an ordinary direct-update path to the
  release branch.
- review threads must be resolved. Stale approvals are dismissed after a push
  on `main`'s ruleset and on classic `develop` protection; the live read-back
  shows the `develop` **ruleset** does not dismiss them, which is recorded under
  `known_live_drift` rather than described here as if it did.

### Residual risk: no reviewer separation is enforced (#85)

The live boundary does **not** enforce code-owner review or last-push approval
anywhere: `require_code_owner_review` and `require_last_push_approval` are
`false` on both live rulesets, and `develop` requires no approvals at all. A PR
touching `/quality/`, `/scripts/check-branch-protection.py`, `CODEOWNERS`, or
any other path in `.github/CODEOWNERS` can therefore be authored and merged by
the same account while satisfying GitHub completely.

That is the current, explicit state, not an oversight for a later reader to
rediscover: `.github/CODEOWNERS` names the accountable human authority and
claims no enforcement. Turning the separation on is a live-settings change
(reviewer separation, code-owner review, or a non-zero `develop` approval
count) that belongs to #564/#85 and must not be applied blindly — it can
deadlock the autonomous queue, which today relies on `develop`'s zero-approval
posture and on the admin bypass recorded above. Until then the residual risk
is: **an account with merge authority on `develop` can merge governance and
quality changes without a second pair of eyes.** Ordinary `main` PRs still
require one approval; neither code-owner review nor approval of the latest
push is required there. The documented bypass actors can bypass requirements
in their configured modes. This is not a claim that arbitrary accounts have
merge permission, or that ordinary `main` PRs need no independent approval.

## Behavioral evidence

The closeout proof for #162 is not merely a settings screenshot:

- PR #517 is an agent-authored trusted-policy change. On its exact head,
  `autonomous-merge-admissibility` concludes **failure** and GitHub reports the
  PR non-mergeable. This proves a PR-authoring agent cannot approve its own
  merge oracle. The producer workflow was later disabled
  (`.github/workflows/autonomous-merge.yml` deleted in `14a67ddf5a`,
  2026-08-28) while `main`'s live ruleset still requires the check; that
  divergence is recorded under `known_live_drift`, and re-enabling the trusted
  gate is a human decision, not a documentation fix.
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
