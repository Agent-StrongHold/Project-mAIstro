---
inventory-delta:
  packages/hive-conductor/backend/tests: +13
---
# claude-issue-698-honest-node-metrics-d933

All 13 are added. **Two existing tests changed sides without changing the
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
