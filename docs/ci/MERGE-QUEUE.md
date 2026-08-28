# Merge queue

**Status:** prepared in the repository, not yet safe to enable live.

The reviewed queue parameters live in [`.github/merge-queue.json`](../../.github/merge-queue.json). The initial scope is **`develop` only**. The queue must not be made authoritative until the workflow changes in the same change are on `develop` and a live canary proves every required context reports on the synthetic merge-group SHA.

## Why the queue exists

`develop` is a high-concurrency integration branch. Without a queue, `required_status_checks.strict=true` makes a green PR stale every time another PR lands, which forces repeated rebases and full CI reruns. A merge queue moves that freshness check to the merge boundary: GitHub constructs a synthetic candidate containing the current `develop` tip plus the queued change and the required gates run on that exact tree.

That is the property we want. A PR being green on its feature-branch head is not enough; the tree that will actually land must be green too.

## Merge method

The queue uses **SQUASH**.

ADR-095 requires linear history, so ordinary merge commits are not allowed. Squash also fits this repository's operating model: one independently reviewable PR becomes one durable commit on `develop`, while fixups and agent iteration remain on the topic branch.

Initial queue policy:

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

The one-PR group size is intentional for rollout. Once the queue has real history and failure behavior is understood, grouping can be widened in a separate reviewed change.

## Required workflow contract

Every ordinary Actions check required on `develop` must handle:

```yaml
merge_group:
  types: [checks_requested]
```

`scripts/check-required-checks.py` enforces that property from the checked-in required-check set. A future required check cannot silently become PR-only while the queue waits forever for it.

Where a workflow only needs to test the candidate tree, `actions/checkout` on a `merge_group` run naturally checks out the synthetic merge-group SHA. Workflows that need a comparison range normalize the two event shapes explicitly:

- PR base: `github.event.pull_request.base.sha`
- merge-group base: `github.event.merge_group.base_sha`
- PR head: `github.event.pull_request.head.sha`
- merge-group head: `github.event.merge_group.head_sha`

The base-trusted `autonomous-merge-admissibility` workflow already follows this model and continues to judge merge groups from trusted base code.

## `gates-ran` is a two-stage rollout

`gates-ran` is unusual because its evaluator is triggered by `workflow_run`. A `workflow_run` job's own status belongs to that workflow execution, not to the PR or merge-group commit being judged, so merely naming the job `gates-ran` does **not** create a usable required context on the candidate SHA.

The prepared workflow fixes that by using the trusted `workflow_run` evaluator to publish a Checks API result named **`gates-ran`** directly onto the candidate SHA. It evaluates both `pull_request` and `merge_group` candidates and fails closed when the check set is unreadable or stalled.

Because GitHub loads `workflow_run` workflows from the default branch, this cannot prove itself on the PR that introduces it. Therefore:

1. Land the merge-queue workflow support through the independent/manual trusted-policy path.
2. Confirm the new `gates-ran` publisher is live from `develop`.
3. On a fresh PR, verify a `gates-ran` check appears on that PR's actual head SHA.
4. Only then add `gates-ran` to the live required-check set and the checked-in branch-protection contract.

Requiring `gates-ran` before step 3 would deadlock every PR at `Expected`.

## Rollout sequence

1. Merge the branch-protection contract that this work is stacked on.
2. Merge this queue-readiness change independently/manual because it changes trusted CI and merge policy.
3. Verify the normal PR suite remains green on a fresh canary PR.
4. Verify the new `gates-ran` publisher creates its check on the canary PR head.
5. Apply the live `develop` queue parameters from `.github/merge-queue.json` with merge method `SQUASH`.
6. Add `gates-ran` as required only after step 4 is proven.
7. Enqueue the canary and capture its synthetic merge-group SHA.
8. Prove every required context, including `autonomous-merge-admissibility` and `gates-ran`, reports on that SHA.
9. Let the canary land and verify `develop` receives exactly one squash commit.
10. Queue a deliberately failing canary and prove it is rejected/removed rather than merged.
11. After the queue is proven, consider changing `develop` from strict pre-queue freshness to queue-owned freshness so authors no longer have to rebase merely because another PR landed. That is a separate reviewed protection change, not part of the bootstrap.

## Not yet covered

This rollout intentionally enables a queue only on `develop`. `main` has additional base-coupled required checks, especially the CodeQL matrix. Before `main` gets a queue, those checks must also be proven on `merge_group`; do not infer `develop` readiness means the release tier is ready.
