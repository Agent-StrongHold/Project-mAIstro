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

A tracked `quality/**` file may also be yellow when the protected-base
`quality/branch-independence.json` registry classifies it as `base_derived` or
`generated`. That classification means the candidate copy is evidence about the
candidate, not the oracle used to judge it. The owning checker must first have
moved its comparison authority to trusted-base provenance before the registry is
changed to either of those kinds.

The initial policy deliberately does **not** autonomously merge yellow changes.
They require a human until dedicated invariant, fault-injection, and behavioral
differential gates exist for those classes. Reclassifying a generated quality
file from RED to YELLOW removes the false claim that the author edited the judge;
it does not silently expand autonomous merge authority to that class.

### Red

A change to the judge or immutable evaluation surface. This includes workflows,
local actions, branch-protection policy, the autonomous merge checker itself,
required-check/gates-ran safety scripts, CODEOWNERS, the Hive cage/eval trees,
and quality state that is policy, durable authorization, legacy shared state,
unknown, or ambiguously classified.

Agent-authored red changes fail the gate. Human-authored red changes are allowed
to proceed through the ordinary manual review/merge path. A red change also
fails in merge-group mode.

## Typed quality state

`quality/**` is deny-by-default. The autonomous-merge checker does not carry a
second list of exempt ledgers. It reads the protected-base
`quality/branch-independence.json` registry and applies these rules:

| Registry kind | Autonomous-merge risk | Why |
| --- | --- | --- |
| `base_derived`, `generated` | YELLOW | Candidate content is measurement/evidence after the owning gate is trusted-base resolved. |
| `specification`, `per_identity_policy`, `folded_notes` | RED | The file is reviewed policy, durable decision state, or a trusted bound input rather than disposable observation. |
| `legacy_shared_aggregate`, `retired_compat` | RED | The migration is incomplete or compatibility semantics still need explicit review. |
| missing, malformed, unknown, or multiply matched | RED | An unavailable classification cannot safely grant less scrutiny. |

The registry itself is a `specification`, so changing the classification table
is RED. Because the judge and registry are both loaded from the protected base,
a candidate cannot make its own quality edit safer by editing its own registry
copy in the same PR.

`quality/wiring-reads-baseline.json` is the first migrated example. Its checker
measures the candidate but resolves the comparison ledger and any authorization
from the trusted base, so banking on the candidate cannot approve newly unread
wiring. Other legacy quality files remain RED until their own provenance and
representation migrations are independently proven.

AC-state is a separate transition. Since #723, ordinary PR review no longer has
to bank every observed AC-state improvement; merge-time actual-base comparison
owns monotonicity. The old contradiction where adding an AC-marked test forced a
shared generated AC-state commit is therefore no longer a reason to weaken the
quality trust boundary.

Stale-branch diffs are also separate. Repository-owned queue admission compares
the current fetched `develop` tree with the prospective merge tree, so target-side
changes that landed after a branch was cut are not charged to that candidate.
The quality classifier does not duplicate that merge-diff authority.

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
