# Merge queue

**Status:** live and authoritative on `develop` as of 2026-08-30.

The repository-side workflow support is checked in, the default-branch ruleset has an active `merge_queue` rule with merge method `SQUASH`, and strict required-status freshness remains enabled. GitHub Actions has produced more than one thousand `merge_group` runs for this repository, including successful synthetic `gh-readonly-queue/develop/...` candidates on 2026-08-30.

That is the serialization proof this document originally required before treating the queue as authoritative. A green feature-branch head is still not sufficient to land; GitHub constructs and checks a synthetic candidate against current `develop` before merge.

The reviewed bootstrap parameters remain in [`.github/merge-queue.json`](../../.github/merge-queue.json). That file is evidence of the repository-reviewed rollout policy, not a claim that the live ruleset still has byte-for-byte identical parameters. The current live read-back is recorded below so documentation does not confuse bootstrap intent with deployed state.

## Why the queue exists

`develop` is a high-concurrency integration branch. With strict required-status freshness and no queue, one merge can make another already-green PR stale and force a full rebase/rerun. A merge queue moves the final freshness proof to the merge boundary: GitHub constructs a synthetic candidate containing current `develop` plus the queued change and runs the required gates on that exact tree.

A green feature-branch head is not enough. The tree that will actually land must be green too.

## Reviewed bootstrap policy

The checked-in rollout record currently says:

| Setting | Value |
|---|---|
| Branch | `develop` |
| Merge method | `SQUASH` |
| Max entries building | 3 |
| PRs merged per group | 3 |
| Minimum merge group | 1 |
| Minimum wait | 2 minutes |
| Grouping | `ALLGREEN` |
| Check response timeout | 60 minutes |

One PR per merge group was deliberate for rollout, and widening grouping was
intended to require a separate reviewed change once real queue behavior was
measured. That reviewed change is this batching posture: a single verification
cycle now covers up to three compatible candidates, and a group forms once
either three candidates wait or the two-minute wait elapses with at least one
present. `scripts/check-required-checks.py` enforces the batching bounds (1–3
per group; waits limited to 0, 2, 3, or 5 minutes), pins `ALLGREEN` grouping,
and fails closed on anything else.

How a group actually fails, read off the Actions API rather than assumed:
GitHub builds one entry branch per queued PR, `gh-readonly-queue/develop/
pr-N-<sha>`, on top of the entry ahead of it — the trailing SHA is that
entry's head, or the develop head at the front of the queue — and every entry
runs the full required set on its own tree. Under `ALLGREEN` a failing entry
is ejected and the entries behind it are rebuilt without it, so one bad
candidate costs the PRs behind it one rebuild, not their place in the queue.
`ALLGREEN` is what makes that safe: `HEADGREEN` would land every member on
the strength of the head entry alone, which is why the gate pins it.

Two consequences follow for the tooling around the queue:

- **Failed heads are quarantined, not re-queued.** The enqueue controller
  (`scripts/check-enqueue-merge-queue.py`, every 30 minutes and after each
  Gates Ran completion) used to re-request any PR whose exact head was still
  policy-green — including a head that had just failed inside the queue,
  which then dragged each new group through a rebuild. It now reads the
  recent merge-group run history, attributes each failed entry to its own
  tree or to a failed entry ahead of it via the branch-name chain, and holds
  any head whose own entry failed after that head's `gates-ran` first went
  green (the earliest moment a queue entry for it could exist). A new push or
  a human enqueue lifts the hold; the bot never does. If the history cannot
  be read, the controller refuses every admission rather than guess.
- **The latency measurement attributes rebuilds.** `measure-merge-latency.py`
  keys every candidate to its own `pr-N` (each grouped PR has its own entry
  and run set, so batching omits none) and now walks the same chain to report
  how many dequeued candidates were rebuilt behind another PR's failure — the
  share of the retry multiplier the batch itself pays, which is the
  before/after figure this posture change should move.

## Live ruleset read-back

The active default-branch ruleset named `Pr merge`, read back on 2026-08-30, reports:

| Setting | Live value |
|---|---|
| Enforcement | `active` |
| Strict required-status freshness | `true` |
| Merge queue | active |
| Merge method | `SQUASH` |
| Max entries building | 10 |
| Minimum merge group | 1 |
| Max entries merged per group | 10 |
| Minimum wait | 0 minutes |
| Grouping | `ALLGREEN` |
| Check response timeout | 60 minutes |

This differs from the bootstrap file's `3`/`3` build/group limits. That is configuration drift to reconcile explicitly; it is **not** evidence that the queue is inactive. The live ruleset is the authority for whether GitHub currently serializes merges.

The same read-back shows `gates-ran` among the required contexts and strict freshness still enabled. It does not currently list `autonomous-merge-admissibility` among those required contexts, so the older rollout checklist's desired protection alignment should not be described as completed merely because the queue itself is live.

## Required workflow contract

Every ordinary Actions check required on `develop` must handle:

```yaml
merge_group:
  types: [checks_requested]
```

`scripts/check-required-checks.py` enforces that property from the checked-in required-check set and pins the repository-reviewed queue policy to `SQUASH`.

Where a workflow compares revisions, it normalizes the two event shapes:

- PR base: `github.event.pull_request.base.sha`
- merge-group base: `github.event.merge_group.base_sha`
- PR head: `github.event.pull_request.head.sha`
- merge-group head: `github.event.merge_group.head_sha`

The base-trusted `autonomous-merge-admissibility` producer is also merge-group aware, so synthetic candidates can be classified by the same trusted-policy logic even though the live required-context set must be read independently from GitHub.

## `gates-ran`

`gates-ran` is a trusted `workflow_run` publisher. Its native workflow-run job is attached to the protected default-branch execution, not the candidate being judged, so the publisher writes the `gates-ran` commit-status context directly onto the triggering candidate SHA.

For ordinary PRs, #543 resolves the PR head/base and requires real execution rather than accepting skipped/cancelled checks as evidence. For merge groups, the publisher accepts only the reviewed `develop` queue namespace (`gh-readonly-queue/develop/`) and publishes the same aggregate verdict on the synthetic queue SHA. Any other merge-group base fails closed until separately reviewed.

## Live activation evidence

The original rollout checklist is no longer a future-tense prerequisite. The important deployed facts are now observable directly:

1. The default-branch ruleset is active.
2. `strict_required_status_checks_policy` is `true`.
3. The ruleset contains an active `merge_queue` rule using `SQUASH`.
4. GitHub has generated more than one thousand `merge_group` workflow runs.
5. Recent runs use the `gh-readonly-queue/develop/...` namespace and have completed successfully on synthetic candidate SHAs.

Together those facts prove that `develop` merge freshness is queue-owned today. Code that relies on queue serialization must remain scoped to canonical `develop` CI; local, imported, synthetic, or other-branch execution must not infer that this deployment contract applies to them.

## Remaining alignment work

Queue activation and configuration parity are separate questions. The following are still worth reconciling in their own reviewed changes:

- decide whether the live `10`/`10` build/group limits are intentional, then update `.github/merge-queue.json` or restore the reviewed `3`/`3` live settings;
- reconcile the live required-status set with the checked-in required-check contract, including the intended status of `autonomous-merge-admissibility`; and
- keep strict freshness unless a separate reviewed protection change demonstrates that relaxing it preserves the same merge-boundary guarantees.

## Not yet covered

The queue evidence above is for `develop` only. `main` has additional release-tier required checks, especially the CodeQL matrix and container scan. Before `main` gets a queue, those producers and the trusted `gates-ran` merge-group base resolver must be extended and proven there. Do not infer `develop` readiness means the release tier is ready.