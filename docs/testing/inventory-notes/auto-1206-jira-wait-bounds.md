---
inventory-delta:
  packages/maistro-core/tests: 17
---
# auto-1206 jira wait poll bounds

**+17** collected node IDs in `packages/maistro-core/tests`, all in the new
`graph/nodes/test_jira_wait_poll_bounds.py` (#1206). A rename inside
`graph/nodes/test_sync_kinds_branch_coverage.py`
(`..._bad_first_seen_falls_back_to_now` → `..._bad_first_seen_repairs_with_evidence`)
moves zero counts: the old test asserted the silent `now` substitution #1206
removes, so its body changed with its name.

The +17 break down as: 3 parametrized rejections of a zero/negative/too-small
`poll_interval_seconds`, 2 parametrized rejections of a non-positive
`timeout_seconds`, and one each for: interval exactly at the host floor,
timeout below poll interval rejected, timeout equal to poll interval accepted,
defaults valid, corrupt-first-seen repair is one-shot (elapsed time after the
repair expires the deadline instead of restarting), legacy-sidecar repair
converges the fallback key, tz-naive first seen treated as corrupt,
non-string first seen repaired with repr evidence, normal timeout firing,
anchor preserved across a pause/resume restart, and the two exact-boundary
timings (elapsed == timeout fires; elapsed == timeout − 1s still pauses).
All timing cases run against a fake `now_utc`, so the boundaries are exact
rather than wall-clock races.
