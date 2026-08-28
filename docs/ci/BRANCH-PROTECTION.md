# Branch protection

**Status:** the policy is written down and machine-checked. **It is not applied
yet** — applying it needs repository-admin scope in the GitHub UI or API, which
no CI job in this repository holds.

Source of truth: [`.github/branch-protection.json`](../../.github/branch-protection.json),
checked against [`REQUIRED-CHECKS.md`](REQUIRED-CHECKS.md) by
`scripts/check-branch-protection.py` in `ci.yml`'s `workflow-lint` job.

## What is true today

Both live protection targets, `main` and `develop`, report `protected: false`.
The ADR-095 `integration` tier remains in the reviewed policy, but there is no
live `integration` branch at the M0 closeout point. Therefore:

- no required status checks — **a red PR can be merged**;
- no required review;
- no required conversation resolution — an unresolved P1 thread does not block;
- no up-to-date-with-base requirement.

Every gate in `quality.yml`, `ci.yml`, `security.yml`, `registry.yml`, the
base-trusted autonomous-merge workflow, and the ratchet scripts is still
**advisory at the live merge boundary** until #162 is applied.

This is also the direct answer to *"are unresolved comments why PRs are not
auto-merging?"* — **no.** Nothing is blocking a merge, and equally nothing is
requiring anything. Enabling *Allow auto-merge* before this policy is applied
would be actively harmful: GitHub's auto-merge waits for *required* checks, so
with none configured it merges as soon as it is armed.

## The required set

Every field follows [`ADR-095`](../adr/ADR-095-four-tier-branch-model.md)'s
protection table, which is the accepted decision. An earlier draft of this
change diverged from it in four places without saying so; review caught all
four. A governance artifact that quietly contradicts the governing ADR is worse
than none, because it looks authoritative.

`enforce_admins` is **false** on all three declared tiers, per ADR-095: *"a solo
maintainer/agent isn't deadlocked"*. That is also load-bearing for the cage
guard, whose own failure message promises that an admin may merge a legitimate
`cage/` or `eval/` change manually — true only while an admin can bypass a
required check.

Both tables below are **generated from `.github/branch-protection.json`** and
checked on every PR by `scripts/check-branch-protection.py`. They were
hand-maintained until #268, and had drifted: the counts read 15/15/19 while the
ruleset required 24/24/28, and nine checks were missing from the grid. Refresh
with `--update-doc`; do not hand-edit between the markers.

● required here · ○ cannot report here · `adv` advisory by declaration.

<!-- protection:tables -->

| Branch | PR | Approvals | Linear history | Force-push | Deletion | Required checks |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `develop` | yes | **0** | yes | no | no | **26** |
| `integration` | yes | **0** | yes | no | no | **26** |
| `main` | yes | **1** | yes | no | no | **30** |

| Check | `develop` | `integration` | `main` |
|---|:--:|:--:|:--:|
| `Analyze (actions)` | ○ | ○ | ● |
| `Analyze (javascript-typescript)` | ○ | ○ | ● |
| `Analyze (python)` | ○ | ○ | ● |
| `Container scan + SBOM + cosign` | ○ | ○ | ● |
| `Coverage gate (publish-set floor + diff coverage)` | ● | ● | ● |
| `Gate C — canonical clean install` | ● | ● | ● |
| `Quality gate (Pillars 1–4, 7, 8)` | ● | ● | ● |
| `SAST (bandit + semgrep + gitleaks)` | ● | ● | ● |
| `Supply chain (pip-audit)` | ● | ● | ● |
| `Validate ADR/spec front-matter` | ● | ● | ● |
| `autonomous-merge-admissibility` | ● | ● | ● |
| `block` | ● | ● | ● |
| `coverage (MinIO)` | ● | ● | ● |
| `coverage (PostgreSQL)` | ● | ● | ● |
| `coverage (no services)` | ● | ● | ● |
| `docker-build` | ● | ● | ● |
| `durable-events` | ● | ● | ● |
| `exact-debt-ledger` | ● | ● | ● |
| `formal-conformance` | ● | ● | ● |
| `hive-conductor-e2e` | ● | ● | ● |
| `hive-conductor-e2e-ui` | ● | ● | ● |
| `lint-and-type-check` | ● | ● | ● |
| `object storage (MinIO)` | ● | ● | ● |
| `postgres (pg17)` | ● | ● | ● |
| `postgres (pg18)` | ● | ● | ● |
| `security` | ● | ● | ● |
| `strike-ladder` | ● | ● | ● |
| `test` | ● | ● | ● |
| `wheel-imports` | ● | ● | ● |
| `workflow-lint` | ● | ● | ● |

<!-- /protection:tables -->

○ means **cannot be required there**, not "chosen not to". A required check
whose workflow never triggers never reports, and classic branch protection
leaves the PR waiting on an `Expected` status forever.

### One approval, only on `main`

ADR-095 puts the approval on the release tier and nowhere else, and this file
follows it. There is a real argument for requiring one on `develop` too — CI
cannot tell whether a test *proves* its criterion or merely restates it, and a
tautological test passes every gate in the chain; #130 is the worked example, a
canonical Run that existed, resolved, and described work that never ran, with
everything green. But that argument is a **change to an accepted decision**, so
it belongs in an ADR revision rather than in a JSON file that silently disagrees
with one. Raised here, not applied.

### Base couplings are declared, not guessed

`base_coupled_to` names the checks whose scope the contract can see is
base-coupled but whose *target branch* it cannot read — a job `if:` narrows on a
GitHub expression, and evaluating that language is out of scope for the contract
generator. Today that is one entry: `Container scan + SBOM + cosign → ["main"]`.

If a check gains a `base_ref` condition and is not listed there, the audit
refuses to let any branch require it. Guessing "main" would be right today and
silently wrong the first time someone couples a job to a different branch.

### The autonomous judge is now part of the same contract

#476 landed the base-trusted `pull_request_target` judge. The required-check
contract now recognizes `pull_request_target` alongside `pull_request`, so
`autonomous-merge-admissibility` is not a manually remembered exception. It is
required on all three declared tiers.

That requirement is intentionally self-referential in the safe direction: a PR
that changes `.github/branch-protection.json`, required-check policy, workflows,
or the autonomous judge is a red trusted-surface change. An agent-authored PR
for such a change must fail autonomous admissibility and take the independent
manual path. The candidate does not get to approve a new rule that would let the
same candidate merge.

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

- **Stale reviews dismissed on a new push**, on all three declared tiers.
  Without it an approval survives a force-push that replaces the diff it
  approved.
- **Linear history required** on all three (ADR-095), so merges are squash or
  rebase, never merge commits.
- **Conversation resolution required.** This is the setting that makes an
  unresolved review thread actually block, which is what was assumed to be
  happening already.
- **Up to date with base required** (`strict: true`). Without it two
  individually-green PRs can merge into a broken `develop`. This repository
  already sees `SUITE-INVENTORY.md` and `quality/ac-state.json` conflict on
  essentially every concurrent pair, which is that failure mode in its mildest
  form. A merge queue is the alternative and would cost less rebasing; it is a
  later change, not a blocker for this one.
- **No force pushes, no deletions**, on all three declared tiers.

## Applying it

Needs a token with **admin** scope on the repository. The script prints the call
and deliberately does not make it — a script that silently held such a token
would be a worse problem than the one it solves.

For the branches that exist now:

```bash
python3 scripts/check-branch-protection.py --apply develop
python3 scripts/check-branch-protection.py --apply main
```

If the ADR-095 stabilization tier is recreated, apply its already-reviewed
contract too:

```bash
python3 scripts/check-branch-protection.py --apply integration
```

Then read the live API back and prove it matches. Only after that should **Allow
auto-merge** be enabled in repository settings.

```bash
GH_TOKEN=<admin token> python3 scripts/check-branch-protection.py --verify
```

`--verify` currently iterates every declared tier, so while `integration` does
not exist its 404 is expected and must not be mistaken for a failure of the two
live branch protections. Direct live read-back of `develop` and `main` is the M0
proof unless the branch is recreated before closeout.

## Verifying it works

The acceptance for #162 is behavioural, not a settings screenshot:

- a PR with a failing required check cannot be merged on each live protected
  branch;
- a PR with an unresolved review thread cannot be merged;
- a PR into `main` without an approving review cannot be merged (`develop`
  requires none, per ADR-095);
- a merge commit is refused on the live protected branches, since linear history
  is required;
- auto-merge, when armed, waits for all of the above;
- `autonomous-merge-admissibility` is required before an autonomous PR may
  merge.

`--verify` checks these are *configured* — every field the policy declares, not
just the context list. That they *bind* is worth one deliberate red PR to
observe, once, after applying.