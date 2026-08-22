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

A check's name is its job's `name:`, or the job id when there is none.

Regenerate after changing a workflow:

```bash
python3 scripts/check-required-checks.py            # check (what CI runs)
python3 scripts/check-required-checks.py --update   # rewrite the table below
```

## Scope: what decides whether a check runs

Three values appear in the `Runs on` column, and the distinction is the whole
point of [#161](https://github.com/Agent-StrongHold/Project-mAIstro/issues/161):

- **every PR** — no trigger filter. The check is a function of the change.
- **paths** — a `paths:` filter. Still a function of the change, so still
  legitimate. See the caveat below before making one of these required.
- **base `<branch>`** — a `branches:` filter on `pull_request`, which matches the
  PR's **base**. A check scoped this way means something different depending on
  what the PR is stacked on. Every one of these was removed in #161 except the
  single deliberate exclusion named below; do not add another without recording
  why here.

### Caveat for #162: paths-filtered checks and "Expected"

A required check whose workflow does not trigger never reports, and classic
branch protection leaves the PR waiting on an `Expected` status forever. So a
**paths-filtered check must not be added to the required set as-is.** The two
ways out are a always-running job that early-exits when the paths do not match,
or leaving the check advisory. Decide per check in #162; this file only records
which ones carry the hazard.

## The checks

<!-- checks:table -->

| Workflow | Check name | Runs on |
|---|---|---|
| CI | `docker-build` | every PR |
| CI | `hive-conductor-e2e` | every PR |
| CI | `hive-conductor-e2e-ui` | every PR |
| CI | `lint-and-type-check` | every PR |
| CI | `security` | every PR |
| CI | `test` | every PR |
| CI | `wheel-imports` | every PR |
| CI | `workflow-lint` | every PR |
| Cage Guard — Auto-reject PRs touching cage/ or eval/ | `block` | paths |
| CodeQL Advanced | `Analyze (${{ matrix.language }})` | base `main` |
| Formal Conformance | `formal-conformance` | every PR |
| Registry CI | `Validate ADR/spec front-matter` | paths |
| Vulture Ratchet | `exact-debt-ledger` | every PR |
| quality | `Quality gate (Pillars 1–4, 7, 8)` | every PR |
| security | `Container scan + SBOM + cosign` | every PR |
| security | `SAST (bandit + semgrep + gitleaks)` | every PR |
| security | `Supply chain (pip-audit)` | every PR |

<!-- /checks:table -->

## Deliberate exclusions

| Workflow | Why it is not on every PR |
|---|---|
| CodeQL Advanced | Deep dataflow analysis on `main` and a schedule. PRs are covered by `security.yml`'s SAST job (bandit + semgrep + gitleaks), which runs on every PR and is fast enough to gate on. Running CodeQL per-push on a stack costs far more than it finds there. |
| Mutation | Long-running and sampled; it is a trend instrument, not a merge gate. |
| Formal Conformance (nightly) | The per-PR `Formal Conformance` job is the gate; the nightly is a deeper sweep. |

## Draft pull requests

Draft PRs run the full set, deliberately. Skipping jobs on drafts would save
runner time, but a skipped job still produces a check run, and a required check
that reports `skipped` rather than `success` behaves differently across branch
protection configurations. Introducing that ambiguity into the required set
would reintroduce, in a new spelling, exactly the "the tick means different
things on different PRs" problem #161 removed. Cost is managed by the
`concurrency` groups instead: every workflow that runs on PRs cancels its own
superseded runs, so a branch pushed ten times in an hour costs one run, not ten.
