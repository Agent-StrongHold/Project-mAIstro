# Branch protection

**Status:** the ruleset is written down and machine-checked. **It is not applied
yet** — applying it needs repository-admin scope in the GitHub UI or API, which
no CI job in this repository holds.

Source of truth: [`.github/branch-protection.json`](../../.github/branch-protection.json),
checked against [`REQUIRED-CHECKS.md`](REQUIRED-CHECKS.md) by
`scripts/check-branch-protection.py` in `ci.yml`'s `workflow-lint` job.

## What is true today

Every branch in this repository reports `protected: false` — `main` and
`develop` included. So:

- no required status checks — **a red PR can be merged**;
- no required review;
- no required conversation resolution — an unresolved P1 thread does not block;
- no up-to-date-with-base requirement.

Every gate in `quality.yml`, `ci.yml`, `security.yml`, `registry.yml` and the
ratchet scripts is **advisory**. They run, they are read, and nothing enforces
them at the merge boundary.

This is also the direct answer to *"are unresolved comments why PRs are not
auto-merging?"* — **no.** Nothing is blocking a merge, and equally nothing is
requiring anything. Enabling *Allow auto-merge* before this ruleset is applied
would be actively harmful: GitHub's auto-merge waits for *required* checks, so
with none configured it merges as soon as it is armed.

## The required set

15 checks on `develop`, 19 on `main`. Both lists are in the JSON; the split is
the four checks that only run on a `main`-based PR.

| Check | `develop` | `main` | Why |
|---|:--:|:--:|---|
| `lint-and-type-check`, `test`, `wheel-imports`, `workflow-lint`, `docker-build`, `security`, `hive-conductor-e2e`, `hive-conductor-e2e-ui` | ● | ● | CI, every PR |
| `Quality gate (Pillars 1–4, 7, 8)` | ● | ● | the ratchets, coverage, the AC mandate |
| `SAST (bandit + semgrep + gitleaks)`, `Supply chain (pip-audit)` | ● | ● | security, every PR |
| `exact-debt-ledger` | ● | ● | the Vulture identity ledger |
| `formal-conformance` | ● | ● | property-based conformance |
| `Validate ADR/spec front-matter` | ● | ● | the ADR → spec → AC chain |
| `block` | ● | ● | cage/eval immutability |
| `Container scan + SBOM + cosign` | ○ | ● | its job `if:` tests `base_ref == 'main'` |
| `Analyze (actions \| javascript-typescript \| python)` | ○ | ● | CodeQL triggers on base `main` |

○ means **cannot be required there**, not "chosen not to". A required check
whose workflow never triggers never reports, and classic branch protection
leaves the PR waiting on an `Expected` status forever.

### Two checks were changed to make them requirable

[`REQUIRED-CHECKS.md`](REQUIRED-CHECKS.md) deferred both of these to #162, and
the decision in each case was to fix the workflow rather than leave the check
advisory — because both sit on claims this repository actually makes.

**`Registry CI → Validate ADR/spec front-matter`** was `paths:`-filtered. It
validates the ADR → spec → AC chain, which is the fifth of the five mandates
#160 wants CI to hold; leaving it advisory would have gutted the epic to save
~20s of runner time. The filter was also close to unfalsifiable already — it had
grown to include `tests/**`, `packages/**/tests/**` and `pyproject.toml`, which
between them match nearly every PR here. Filter removed.

**`Cage Guard → block`** was unrequirable in two ways at once. It triggered only
on `cage/` and `eval/`, so on a normal PR it never reported; and its only step
was `exit 1`, so it had **no success path at all**. A check that can only ever
fail cannot be a required check — and a *failing advisory* check does not block
a merge, so under protection the guard would have been decorative exactly when
it mattered. It now runs on every PR and passes unless the diff touches those
paths.

### Nothing is advisory by accident

`scripts/check-branch-protection.py` fails when a PR check is in neither a
branch's `contexts` nor the `advisory` map. Adding a gate to CI is therefore a
decision about whether it belongs to the merge contract, made in a diff, rather
than a default reached by forgetting. The `advisory` map is empty today: every
check that can be required, is.

## The rest of the rule

- **One approving review**, with stale reviews dismissed on a new push. This is
  deliberate and belongs in the same change: CI cannot tell whether a test
  *proves* its criterion or merely restates it, and a tautological test passes
  every gate in the chain. #130 is the worked example — a canonical Run that
  existed, resolved, and described work that never ran, with everything green.
  The design-coverage ADR (`ADR-082226-ff3c`) makes the same point from the
  other side: a criterion can be tautological and still reach `reachable`.
- **Conversation resolution required.** This is the setting that makes an
  unresolved review thread actually block, which is what was assumed to be
  happening already.
- **Up to date with base required** (`strict: true`). Without it two
  individually-green PRs can merge into a broken `develop`. This repository
  already sees `SUITE-INVENTORY.md` and `quality/ac-state.json` conflict on
  essentially every concurrent pair, which is that failure mode in its mildest
  form. A merge queue is the alternative and would cost less rebasing; it is a
  later change, not a blocker for this one.
- **No force pushes, no deletions**, on both branches.
- **`enforce_admins` on `main` only.** `main` is the published branch, and an
  admin bypassing the gate set on it is the one case where the audit trail
  matters more than the convenience.

## Applying it

Needs a token with **admin** scope on the repository. The script prints the call
and deliberately does not make it — a script that silently held such a token
would be a worse problem than the one it solves.

```bash
python3 scripts/check-branch-protection.py --apply develop   # prints the gh api call
python3 scripts/check-branch-protection.py --apply main
```

Then, in **Settings → General → Pull Requests**, tick **Allow auto-merge** — and
only then, for the reason at the top of this file.

Afterwards, confirm the live state matches:

```bash
GH_TOKEN=<admin token> python3 scripts/check-branch-protection.py --verify
```

## Verifying it works

The acceptance for #162 is behavioural, not a settings screenshot:

- a PR with a failing required check cannot be merged;
- a PR with an unresolved review thread cannot be merged;
- a PR without an approving review cannot be merged;
- auto-merge, when armed, waits for all three.

`--verify` checks the first three are *configured*. That they *bind* is worth
one deliberate red PR to observe, once, after applying.
