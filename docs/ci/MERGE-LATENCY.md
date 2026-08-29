# Merge-queue latency

**Status:** measured (before #654/#655). Regenerate with

```bash
python3 scripts/measure-merge-latency.py            # public API; token optional
```

or by dispatching the `Merge-queue latency` workflow, which runs the same
script with the job's own token.

## Why this record exists

The build-efficiency program
([#654](https://github.com/Agent-StrongHold/Project-mAIstro/issues/654)) and
its merge-group slice
([#655](https://github.com/Agent-StrongHold/Project-mAIstro/issues/655))
both promise throughput, and #655's acceptance names the metric explicitly:
*track ready-to-merge → merge-group completion time and queue CI retry/dequeue
rate before and after this slice.* The "before" side is only measurable while
the queue still runs every leg unconditionally, so it is banked here rather
than reconstructed later. `measure-ci-cost.py` answers what one head costs in
job-minutes; this answers what an approved, green PR *waits*, and how often the
queue re-spends the whole gate set on one merge.

## Definitions

- **Queue residency** — first merge-group run start for the PR → `merged_at`.
  What a contributor waits after the PR is ready, including every requeue.
- **Candidate wall-clock** — one synthetic queue candidate, earliest run start
  → latest run update, counted only when every observed run concluded.
- **Requeue rate** — merged PRs that needed more than one candidate. The queue
  branch embeds the candidate SHA, so a requeue is a new SHA under the same
  `pr-N`; each one is a full re-execution of the required set.

## Measurement — 2026-08-29, before #654/#655

Window: 2026-08-29 15:27 → 20:49 UTC (the API's newest page of merge-group
runs at measurement time), base `develop`, over `ci.yml` + `quality.yml` runs —
the two workflows that dominate candidate wall-clock. Wall-clock over the full
workflow set is at most minutes longer per candidate; residency and requeue
figures are exact for the window regardless.

| PR | attempts | merged | residency (min) |
|---:|---:|:---|---:|
| 495 | 1 | yes | 13.7 |
| 496 | 4 | yes | 58.1 |
| 589 | 4 | yes | 62.3 |
| 623 | 3 | yes | 65.0 |
| 627 | 4 | yes | 61.2 |
| 628 | 1 | yes | 14.0 |
| 632 | 2 | yes | 58.6 |
| 634 | 2 | yes | 18.1 |
| 635 | 1 | yes | 12.1 |
| 639 | 2 | no | — |
| 648 | 1 | yes | 13.5 |
| 649 | 1 | no | — |
| 650 | 1 | yes | 13.8 |
| 652 | 1 | yes | 14.4 |

| | value |
|---|---:|
| PRs seen in queue | 14 (12 merged) |
| queue candidates run | 28 |
| requeued merged PRs | 6 (**50% requeue rate**) |
| residency, median / p90 | **18.1 / 62.3 min** |
| candidate wall-clock, median / p90 | 13.2 / 15.7 min |

## What the numbers say

A clean pass through the queue costs ~14 minutes. A requeued PR waits ~60 —
four to five candidate-widths — and half of the merged PRs in the window were
requeued. The queue ran the full gate set 28 times to land 12 merges: **2.3
gate-set executions per merge**, on top of the PR-head and protected-push runs
of the same content. That multiplier, not the 14-minute clean pass, is the
"before" that #654's evidence reuse and #655's scoped merge-group legs are
meant to collapse; re-run this measurement after each slice lands and append
the row here.

Not attributed here: *why* candidates were ejected (flake, conflict, or a real
failure) — the Actions API records the re-run, not the reason. The requeue
rate therefore bounds flake-plus-conflict cost without splitting it.
