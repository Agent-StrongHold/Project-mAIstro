# Merge queue

**Status:** repository support prepared for `develop`; live queue still requires the canary/read-back sequence below.

The reviewed queue parameters live in [`.github/merge-queue.json`](../../.github/merge-queue.json). The initial scope is **`develop` only**.

The trusted PR-head `gates-ran` publisher is already on `develop` via #543. This change extends the required workflow set and that publisher to GitHub's synthetic `merge_group` candidates. The live queue must not become authoritative until this repository-side support is on `develop` and a canary proves every required context reports on the synthetic queue SHA.

## Why the queue exists

`develop` is a high-concurrency integration branch. With strict required-status freshness and no queue, one merge can make another already-green PR stale and force a full rebase/rerun. A merge queue moves the final freshness proof to the merge boundary: GitHub constructs a synthetic candidate containing current `develop` plus the queued change and runs the required gates on that exact tree.

A green feature-branch head is not enough. The tree that will actually land must be green too.

## Initial policy

| Setting | Value |
|---|---|
| Branch | `develop` |
| Merge method | `SQUASH` |
| Max entries building | 3 |
| PRs merged per group | 1 |
| Minimum merge group | 1 |
| Minimum wait | 0 minutes |
| Grouping | `ALLGREEN` |
| Check response timeout | 60 minutes |

One PR per merge group is deliberate for rollout. Widening grouping requires a separate reviewed change after real queue behavior is measured.

## Required workflow contract

Every ordinary Actions check required on `develop` must handle:

```yaml
merge_group:
  types: [checks_requested]
```

`scripts/check-required-checks.py` enforces that property from the checked-in required-check set and pins the queue policy to `SQUASH` with one PR per group.

Where a workflow compares revisions, it normalizes the two event shapes:

- PR base: `github.event.pull_request.base.sha`
- merge-group base: `github.event.merge_group.base_sha`
- PR head: `github.event.pull_request.head.sha`
- merge-group head: `github.event.merge_group.head_sha`

The base-trusted `autonomous-merge-admissibility` producer is also merge-group aware, so the synthetic candidate remains subject to the same trusted-policy classification as an ordinary PR.

## `gates-ran`

`gates-ran` is a trusted `workflow_run` publisher. Its native workflow-run job is attached to the protected default-branch execution, not the candidate being judged, so the publisher writes the `gates-ran` commit-status context directly onto the triggering candidate SHA.

For ordinary PRs, #543 already resolves the PR head/base and requires real execution rather than accepting skipped/cancelled checks as evidence. For merge groups, this change accepts only the reviewed `develop` queue namespace (`gh-readonly-queue/develop/`) and publishes the same aggregate verdict on the synthetic queue SHA. Any other merge-group base fails closed until separately reviewed.

## Live rollout

1. Land this queue-readiness change through the independent/manual trusted-policy path. Its `autonomous-merge-admissibility` RED result is expected because it changes trusted CI.
2. On a fresh `develop` PR, verify the protected default-branch publisher creates a `gates-ran` status on the PR's exact head SHA. If this PR receives that status after #543, it is valid bootstrap evidence too.
3. Correct the known live `develop` ruleset drift so `autonomous-merge-admissibility` is required alongside the checked-in contract.
4. Enable the live `develop` merge queue using `.github/merge-queue.json`, with merge method `SQUASH`.
5. Enqueue a harmless canary and capture GitHub's synthetic merge-group SHA.
6. Verify every required context, including `autonomous-merge-admissibility` and `gates-ran`, reports on that synthetic SHA.
7. Let the canary land and verify `develop` receives exactly one squash commit.
8. Queue a deliberately failing canary and prove it is rejected or removed rather than merged.
9. Only after queue-owned freshness is proven should `develop` consider relaxing pre-queue strict/up-to-date freshness. That is a separate reviewed protection change.

## Not yet covered

The initial queue is `develop` only. `main` has additional release-tier required checks, especially the CodeQL matrix and container scan. Before `main` gets a queue, those producers and the trusted `gates-ran` merge-group base resolver must be extended and proven there. Do not infer develop readiness means the release tier is ready.
