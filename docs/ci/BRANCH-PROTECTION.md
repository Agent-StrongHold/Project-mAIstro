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

`autonomous-merge-admissibility` is **not** in this file's required sets. The
repository owner decided (#564, 2026-10-26) that it stays advisory pending #562:
requiring it froze every ledger-banking agent-authored PR, several of them red on
it by design, so an apply of the declared ruleset must be the direction that
*removes* the requirement, not the one that creates it. The one live place that
still required it at the last read-back (below) is drift to reconcile through
the GitHub settings surface, not by re-adding the context here.

`gates-ran` is declared required on both branches; because it is produced by
`workflow_run`, it is recorded under the policy's Ruleset-only
`additional_required_checks` rather than in the generated PR-job grid below.
Whether each branch's live ruleset currently carries it is a measured fact, not
an assumption — see the read-back.

## Required set

● required here · ○ cannot report here · `adv` advisory by declaration.

<!-- protection:tables -->

| Branch | PR | Approvals | Linear history | Force-push | Deletion | Required checks |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `develop` | yes | **0** | yes | no | no | **21** |
| `main` | yes | **1** | no | no | no | **35** |

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
| `coverage (no services)` | ● | ● |
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
container image scan are intentionally main-only. The table reflects what this
file declares — which contexts are actually required live is the read-back's
subject, below.

## Live read-back (measured, not inferred)

Read through the Rulesets API on **2026-11-26** — ruleset `21421373` "Pr merge"
(controls `~DEFAULT_BRANCH` = `develop`) and `21701487` "Main merge" (controls
`refs/heads/main`), both `active`, default branch `develop`. Required contexts,
strictness, and queue posture are the values the API returned, and the delta
against this file is computed, not guessed (#564 AC-1):

| | live `develop` (25 contexts) | live `main` (31 contexts) |
|---|---|---|
| strict required-status freshness | yes | yes |
| merge queue | `SQUASH`, grouping `HEADGREEN`, build ≤ 10, merge ≤ 15, group ≥ 1, wait 5 min, timeout 90 min | none |
| `autonomous-merge-admissibility` | not required | **required** |

Live `develop` requires: docker-build, hive-conductor-e2e, hive-conductor-e2e-ui,
lint-and-type-check, workflow-lint, security, test, wheel-imports, block,
formal-conformance, Coverage gate (publish-set floor + diff coverage), Gate C —
canonical clean install, Quality gate (Pillars 1–4, 7, 8), Validate ADR/spec
front-matter, exact-debt-ledger, SAST (bandit + semgrep + gitleaks), Supply
chain (pip-audit), coverage (MinIO), coverage (PostgreSQL), coverage (no
services), strike-ladder, durable-events, object storage (MinIO), postgres
(pg17), postgres (pg18).

Live `main` requires that set plus: autonomous-merge-admissibility, gates-ran,
Container scan + SBOM + cosign, Analyze (actions), Analyze
(javascript-typescript), Analyze (python).

The measured declared/live delta on that date:

- **live-only on `develop`** (required live, absent from this file):
  docker-build, hive-conductor-e2e, hive-conductor-e2e-ui, wheel-imports,
  strike-ladder, durable-events, object storage (MinIO), postgres (pg17),
  postgres (pg18) — and `gates-ran`, which this file declares but which no live
  develop ruleset currently carries;
- **declared-only on `develop`** (an apply would newly require them):
  Compliance registry, integration-scope, cross-product-parity,
  sandbox-conformance, JS supply chain (npm audit + GuardDog + policy gate);
- **live-only on `main`**: `autonomous-merge-admissibility` — required live with
  **no producing workflow** (the autonomous-merge workflow was retired; #579),
  so a `develop -> main` PR cannot satisfy it. Removing it there is the
  settings-surface action that finishes #564 AC-2 in the decided direction and
  belongs to the policy owner (#162, #562); this repository cannot make it;
- **declared-only on `main`**: Compliance registry, docker-rebuild-compare,
  hive-conductor-compose-durability, cross-product-parity, sandbox-conformance,
  JS supply chain (npm audit + GuardDog + policy gate);
- **merge queue**: live `HEADGREEN`/10/15/5/90 against the reviewed
  `.github/merge-queue.json` `ALLGREEN`/3/3/2/60. The live rule is the authority
  for what GitHub enforces today; the checked-in file is the reviewed posture.
  The divergence is measured drift to reconcile explicitly (#162/#564) — not
  evidence that either side is inert, and not a licence to apply either blindly.

Re-read this section whenever `--verify-rulesets` goes red. The command, not
this prose, is the live detector; this section records what it measured.

## Verifying declared against live

- `scripts/check-branch-protection.py` bare (offline, the `workflow-lint` job)
  checks this file against the workflows' check-name contract; it never touches
  the network.
- `--verify-rulesets` reads the live Rulesets API with any repository-read
  token (`GH_TOKEN`/`GITHUB_TOKEN`) and fails on declared/live drift — required
  contexts in either direction (the declared set includes
  `additional_required_checks`), the strict-freshness flag, a declared branch
  with no governing ruleset, and merge-queue posture against
  `.github/merge-queue.json`. It needs no admin scope, which is what lets
  `.github/workflows/branch-protection-drift.yml` run it on a weekly schedule
  (#564 AC-4): drift is detected when it appears, not when someone applies.
- `--verify` compares the classic branch-protection endpoint instead. It needs
  admin scope and stays a by-hand check. Since #162 moved the required contexts
  into Rulesets, that endpoint carries no `required_status_checks` at all for
  this repository, so only its non-context fields are meaningful there.
- `--apply BRANCH` prints the exact API call, guarded (#564 AC-3): it first
  reads the live ruleset and every open PR head, and refuses — naming the PRs —
  when the apply would newly require a context that a PR head has never
  reported (it would wait on `Expected` forever) or currently reports not-success
  (it would flip from mergeable to blocked silently). Without a token it
  refuses unconditionally: an apply whose freeze impact is unknown is precisely
  the accident #564 was filed to prevent. `--allow-freeze` is the explicit
  override once the named PRs have been read, and its output says so.

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
