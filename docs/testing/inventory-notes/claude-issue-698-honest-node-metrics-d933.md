---
inventory-delta:
  packages/hive-conductor/backend/tests: +38
---
# claude-issue-698-honest-node-metrics-d933

All 38 are added (13 in the first round, 20 answering the review below, 5 more for the branches the diff-coverage gate named). **Two existing tests changed sides without changing the
count**, and they are the more interesting half: `test_aggregate_empty_returns_zeros`
and the `record_run_completion` ingest case both asserted `tokens_in == 0`.
They were pinning the defect — a zero where nothing had been measured — so they
now assert absence, and their names and comments say why.

`test_node_metrics_are_measured.py`, four classes:

**`TestAnUnmeasuredMetricIsAbsent` (5)** — the four fields default to absent; a
window of unmeasured observations reports no cost measured rather than a zero
cost; a measured cost is still reported (the control, or absence would swallow
the values that exist); a mean divides by what was measured, so one node at
100ms beside one untimed is a 100ms mean and not 50ms; and an untimed node does
not enter the latency percentiles, where a zero made it the fastest in the
window.

**`TestTheIngestHasAProductionCaller` (3)** — the canonical path calls
`record_run_completion`, asserted by parsing `dag_agents` because reaching that
line needs a live container; the ingest leaves tokens and cost absent while
recording the latency it does have; and `_latency_ms` returns `None` for a
NodeRun with no timestamps.

**`TestTheReadersUseThePublicSurface` (3)** — parsed, per module: neither
`optimizer` nor `topology_compare` reaches a private helper of the metrics
store, checked both as attribute access and as a private import, since
`topology_compare` did the latter (`_aggregate as _ms_aggregate`). The third
shows the public surface answers the same question.

**`TestTheProcessStoreIsInstalledPerStart` (2)** — `reset_store` installs a
fresh buffer and is what `get_store` then returns; the engine performs that
reset at start, so `set_store` has a production caller.

**Mutation-checked**, four mutations, each killed by the case that should catch
it:

| mutation | kills |
|---|---|
| default `cost_usd` back to `0.0` and treat `None` as zero | 3, including the ingest case |
| divide the latency mean by the observation count again | `test_a_mean_divides_by_what_was_measured` |
| return `0` for a NodeRun with no timestamps | `test_a_node_run_with_no_timestamps_has_no_latency` |
| remove the ingest's production caller | `test_the_canonical_path_records_the_run` |


## The Codex review, +20 more

Three findings, all real, and two of them were my change making things worse
in the very dimension it exists to improve.

- **AC-2, +5** — `_percentile` returning `0` for an empty list, and
  `topology_compare` normalizing p95 with `invert=True`: a variant nobody timed
  scored 1.0 on speed and outranked every variant with real numbers. So
  stopping the fabrication at the writer, without fixing its readers, made the
  comparison *worse* than the zeroes had. A percentile over nothing is `None`;
  an unmeasured bucket takes the midpoint of the normalized scale and the row
  says `latency_measured: false`.
- **AC-1, +4** — `model_used`, which went out with the fabrications and should
  not have. The old code took the *first* node's model and stamped it on every
  node; `graph_runner` resolves each node's own model and passes it to the
  call, so that value is measured. Without it the default grouping collapses
  every observation into one `(unset)` bucket. Asserted on the runner's own
  result shape and the route reading it, rather than on a re-resolution in the
  route, because a second copy of the fallback chain is two places to drift.
- **AC-3, +11** — only terminal records ingested. `run_durable_graph` returns
  as soon as the graph stops advancing, so a wait or HITL node returns a record
  in `waiting` or `paused` whose paused NodeRun would land in the aggregate's
  denominator while every node after it is missing. Parametrized over all nine
  `RunStatus` values plus an unknown one and an enum-versus-string case.

**Three existing tests changed sides**, so they do not move the count:
`test_aggregate_empty_reports_nothing_measured` and
`test_percentile_returns_zero_for_empty_list` in `test_node_metrics.py`, and
`test_variant_bucket_success_rate_zero_when_empty` in
`test_topology_compare.py`. All three asserted the zero the review identified
as the defect.

**Eight more mutations, all killed**: `_percentile` back to zero (4 fail); an
unmeasured bucket normalized as zero rather than skipped; the bucket's p95 back
to zero; the LLM node not reporting its model; the subprocess node not
reporting its model; the route not recording it; the ingest unconditional again
(6 fail); and an unknown status read as suspended (3 fail).


## +5 after the first CI round

The diff-coverage gate measures against the PR's **recorded base sha**, not
current `develop`, so CI's diff is larger than a local `--base origin/develop`
produces — and it named three branches my local check had not:
`dag_agents.py` 82.4% (the ingest's `except`, and the deferral's `logger.info`)
and `graph_runner.py` 75.0% (the subprocess node's failure return).

All three are covered by *running* the code rather than reading it:
`run_registered_dag` driven through the real canonical path against a synth
DAG, once with a failing `record_run_completion` and once with a record forced
to `paused`; and `_run_node_subprocess` with the executor refusing and with it
raising. The last two matter for AC-1 as well as coverage — the source
assertion counts three `"model": model` returns, and these two prove the
failure ones actually carry it.

The lesson generalises: verify with `--base <the PR's base sha>`, not
`origin/develop`, or the local check is measuring a smaller diff than the gate.
