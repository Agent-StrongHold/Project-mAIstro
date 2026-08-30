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

- **Queue residency** — the PR's earliest `added_to_merge_queue` timeline
  event → `merged_at`, including every requeue and the wait for one of the
  queue's build slots. Where a PR's timeline cannot be read (or its admission
  event lies beyond the fetched pages) the figure falls back to the first
  observed merge-group run start — a **lower bound**, since workflow start
  trails admission by scheduling delay and slot wait — and the report
  discloses how many rows fell back. The 2026-08-29 baseline below predates
  the admission upgrade: all of its residencies are the run-start lower
  bound.
- **Clean candidate wall-clock** — one synthetic queue candidate, earliest run
  start → latest run update, counted only when every observed run concluded
  `success`. An ejected candidate is cancelled mid-run, so its short
  wall-clock is excluded rather than allowed to flatter this figure.
- **Requeue rate** — merged PRs that needed more than one candidate: how often
  a PR that *did* land paid for the gate set more than once.
- **Dequeue rate** — candidates that landed no merge, over all candidates run.
  Unlike the requeue rate this does not condition on merging: the candidates
  of a PR ejected and never requeued count, so a queue that fails PRs outright
  gets a worse number, not a better one.
- **Boundary cohort** — the API pages individual workflow runs, so the oldest
  fetched runs can belong to a candidate cut by the page boundary. When the
  listing is truncated, every PR with a candidate near the old edge is
  excluded rather than scored from partial history.

## Measurement — 2026-08-29, before #654/#655

Collected via the GitHub API's merge-group run listing for **`ci.yml` and
`quality.yml` only** — the two workflows that dominate candidate wall-clock —
at the newest **30 runs each** (the listing page available at measurement
time), then folded through this script's `candidates → drop_boundary_cohort →
summarize → figures` pipeline. That is narrower than the script's default
sweep (`--pages 3`, all merge-group workflows), so a rerun today reproduces
the arithmetic but not this exact window; the residency, requeue, and dequeue
figures are insensitive to the workflow subset (any one workflow's runs name
every candidate), while a full-workflow sweep can read candidate wall-clock
minutes higher if a smaller workflow finishes last. Window: 2026-08-29
15:27 → 20:49 UTC, base `develop`. PR #632 was excluded as the boundary
cohort — its first candidate starts at the window's old edge.

| PR | attempts | merged | residency (min) |
|---:|---:|:---|---:|
| 495 | 1 | yes | 13.7 |
| 496 | 4 | yes | 58.1 |
| 589 | 4 | yes | 62.3 |
| 623 | 3 | yes | 65.0 |
| 627 | 4 | yes | 61.2 |
| 628 | 1 | yes | 14.0 |
| 634 | 2 | yes | 18.1 |
| 635 | 1 | yes | 12.1 |
| 639 | 2 | no | — |
| 648 | 1 | yes | 13.5 |
| 649 | 1 | no | — |
| 650 | 1 | yes | 13.8 |
| 652 | 1 | yes | 14.4 |

| | value |
|---|---:|
| PRs seen in queue | 13 (11 merged) |
| queue candidates run | 26 |
| requeued merged PRs | 5 (**45% requeue rate**) |
| dequeued candidates | 15 of 26 (**58% landed no merge**) |
| residency, median / p90 (lower bound) | **14.4 / 62.3 min** |
| clean candidate wall-clock, median / p90 | 13.5 / 15.5 min |

## What the numbers say

A clean pass through the queue costs ~14 minutes. A requeued PR waits ~60 —
four candidate-widths — and 5 of the 11 merged PRs in the window were
requeued. The queue ran the full gate set 26 times to land 11 merges: **2.4
gate-set executions per merge** (58% of candidates landed nothing), on top of
the PR-head and protected-push runs of the same content. That multiplier, not
the 14-minute clean pass, is the "before" that #654's evidence reuse and
#655's scoped merge-group legs are meant to collapse; re-run this measurement
after each slice lands and append the row here.

The residency figures understate true ready-to-merge latency by the pre-run
queue wait, which grows exactly when the queue is busiest.

## Where the window's dequeues actually came from

The script does not attribute ejections, but the window's failed runs were
read job-by-job once, and the attribution is worth banking with the numbers:

- **Nine candidates** (PRs 496, 589, 623, 627, 632; 15:27–16:49) failed in
  `CI / test` at one step — `pytest tests/`, the root tree that carries the
  AC-state merge-guard suites. That is the "develop is red inside the merge
  queue, and only there" defect (#635, finished by #650/#652): the queue was
  green again from 17:07, the moment the fix candidate went through.
- **Three candidates** (PRs 639, 649; 20:36–20:49) failed in
  `quality / Quality gate` at the **contract marker ledger** step — a gate PR
  #639 itself introduces, failing in merge-group context only.

No flake, no service failure, and no real code regression ejected a candidate
in this window. Every dequeue traces to a ratchet or gate resolving its
baseline differently inside the merge queue than on the PR head — the exact
class of defect #647's centralized base resolution exists to close. For this
window, the retry half of the multiplier was not noise to be amortized by
evidence reuse; it was one fixable defect class, twice.
