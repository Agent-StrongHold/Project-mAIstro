---
inventory-delta:
  packages/maistro-rsi/tests: +68
---
# claude-issue-356-rsi-harvest-target-and-patch-policy

Sixty-eight new node IDs across two files: fifty in
`test_export_policy.py` (the policy) and eighteen in
`test_harvest_entry_point.py` (that the policy is reached through the command
the workflow actually runs). Nothing removed or reparametrised.

## The claim the trust model rests on, and the half of it that was true

`rsi-harvest.yml` runs with `contents: write` and `pull-requests: write`. Its
own header states the trust model (ADR-070126-6386 / ADR-093): **no
agent-authored code runs here — the exports are data.**

That held for *execution*. The job checks out the trusted default branch rather
than `export_ref`, pulls only `.rsi-exports/` from the untrusted branch, and
refuses that directory if it holds anything but `*.patch` and `manifest.json`.
All correct, and all about what gets *run*.

It did not hold for *content*. Those patches went straight to `git am`, and a
patch is a program for the working tree. It can create a symlink, move a
submodule pointer, write to a path the manifest never mentions, or edit the
files that decide what a future self-modification is allowed to do — and none
of that is executable code in the export directory, so none of it was checked.

## Where a harvested PR was allowed to go

ADR-095 defines four tiers: topic branches → `develop` → `integration` →
`main`, with `main` requiring an approving review. A harvest branch is a topic
branch.

`rsi-harvest.yml` took `pr_base` as a `workflow_dispatch` **input defaulting to
`main`**, and `maistro_rsi harvest` defaulted `--pr-base` the same way. So the
documented way to run a harvest opened agent-authored PRs directly against the
release tier, skipping both integration tiers *and* the approval — with the
target chosen by whoever dispatched the run rather than by policy.

`resolve_pr_base` makes it policy. The default is the canonical development
branch; a release tier raises unless `release_tier_authorized` is passed, and
that is a parameter of the *caller* — the workflow decides it from its own
configuration. Nothing in the export, the manifest, or a dispatch value can
express it. `test_nothing_in_the_manifest_can_choose_the_tier` pins that
directly, because "candidate-controlled" is about reachability rather than
about which field name carries it.

`clone_base` followed the same default, and moves with it: branching off the
release tier and then targeting the development tier would put every commit
between them into the PR.

## The containment surface, on the way out as well as in

`quarantine.py` already owns `matches_sensitive_pattern` and applies it to a
run's diff **inside** the loop. `validate_patch` applies the same function to
the exported artifact, which is the AC's "the same protected-path policy
governs workspace, export, PR, and merge".

Deliberately a re-check rather than a delegation. The two scans read different
objects: the loop scans what the agent produced, this scans what arrived on the
export branch, and a trusted orchestrator sits between them. "The earlier check
passed" is not evidence about the bytes `git am` is about to consume.

## Four things a path check cannot see

* **Symlink** (`mode 120000`). A later write through it lands wherever it
  points. Resolving symlinks in the export directory does not cover this,
  because the link does not exist yet — it is being created by the patch.
* **Submodule** (`mode 160000`). Nothing downstream of the harvest reviews the
  history it would point at.
* **Binary hunk.** The promotion contract is a minimal, reviewable edit to one
  source file. No reviewer of the resulting PR can read a blob.
* **Deletion of a protected file.** Removal is the cheapest way to disable a
  check, and a deletion diff has no `+++ b/` side to notice.

## The manifest's claim is checked, not trusted

The harvester groups by the manifest's `file`, names the branch after it, and
puts it in the PR title. A patch touching anything else produces a PR whose
every human-readable label is wrong about its own contents — and the manifest
and the patch come off the same branch, so one is no evidence about the other.
`test_a_second_file_smuggled_alongside_the_declared_one_is_refused` is the
realistic shape: the declared edit is genuine and something else rides along.

## Reading the patch the manifest names

`patch_file` is attacker-influenced in exactly the way a filename can be. The
previous code did `(export / patch.patch_file).resolve()` — which **follows** a
symlink and normalises a traversal away, turning both into a valid-looking path
rather than an error.

`resolve_export_path` resolves and then checks against the *resolved* root, so
a link cannot land outside even when every textual component looks innocent. A
symlink that stays inside the export is allowed: the property is where it
lands, not that it is a link, and refusing every link would refuse a legitimate
export layout for nothing.

## A defect this PR's own tests found

`_DIFF_HEADER` was anchored on `diff --git a/`. git wraps a side in quotes when
the path holds a byte it will not print raw, and **the quote comes before the
`a/`** — so a quoted header did not match at all.

On its own that fails closed: no paths parsed means the "nothing here
identifies what it changes" refusal fires. The bypass needs a second header. One
ordinary path makes the list non-empty, that refusal never fires, and the quoted
path — which could be anything, including `.github/` — is never examined.
`test_a_quoted_header_beside_an_ordinary_one_is_still_checked` is that exact
composition.

## Validated before git, not during

The first version checked each patch inside the apply loop, after
`git checkout -B`. That is a worse shape for a fatal refusal: patch 3 of file 2
failing would leave branches already created for file 1. `_validated_export`
runs the whole export through the policy before the clone, and returns the
resolved path per entry so the apply loop uses the path that was vetted rather
than re-deriving it — re-deriving is how a check and the thing it checked drift
apart.

A refusal fails the **whole** harvest rather than skipping one patch, unlike the
unappliable case beside it. A stale patch is an accident and the rest of the run
is still good; a patch reaching for `.github/` is a statement about this export,
and opening the other PRs from it would be treating one artifact as trustworthy
and untrustworthy at the same time.

## Two more the coverage number asked for

`export_policy.py` came out at 98%, and both gaps were real cases rather than
unreachable defensiveness:

* The "strip a surrounding quote pair" branch in `_unquote` was never taken,
  because the header pattern captures the *inside* of the quotes. The rename
  lines are the only place quotes arrive still attached — and git quotes those
  too, so a quoted rename onto the containment surface would have been compared
  against a name no pattern matches.
* The loop arc where a deleted path is *not* protected. That is the
  counterweight to the protected-deletion check: a promotion removing a dead
  ordinary module is a legitimate improvement, and a policy refusing every
  deletion would block it for nothing.

100% lines and branches on the module after those.

## Discrimination, measured

Against the real pre-fix `__main__.py` and `rsi-harvest.yml` (restored with
`git checkout origin/develop --`, with the new module present so the difference
measured is the *wiring* rather than the module's existence): **15 of the 18
entry-point tests fail**.

The three that pass are invariants this change must not break — the workflow's
least-privilege permission block, the ADR constant still naming `develop`, and
an ordinary export still getting past the policy into git.

## Not covered here

The issue's remaining two criteria are not in this change, and are not claimed:

* *"Patch metadata, base/head SHA, quarantine evidence, and approvals are
  immutable and correlated."* That is a provenance record spanning the run, the
  export, and the PR — a different object from the admission check here.
* *"The same protected-path policy governs workspace, export, PR, and **merge**."*
  The workspace and export halves are done. The merge half is a branch-protection
  and required-check question, not something the harvester can enforce: it opens
  PRs and deliberately cannot merge them.
