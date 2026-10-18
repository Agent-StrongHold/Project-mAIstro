---
inventory-delta:
  tests/: +2
---
# auto-57 model-egress seam — governed backend delegation

The repair round after the production-wiring commit (`6abcbb367`) found a
real CI gate failure the round's report missed:
`scripts/check-model-egress.py` (quality.yml `check-model-egress` step)
exited 1 because `services.governed_tools` had become a NEW direct
model-egress module — `_hive_tool_backend` re-listed the raw hive tool
implementations with direct `tool_executor.web_search`/`browse_url`/
`clarify` calls, and the curated census triple
`services.tool_executor.clarify -> MODEL_EFFECT:hive.clarify` counted the
module. New model-egress callers are frozen against the trusted base and
need a separately landed authorization (the two-merge rule), which no code
change on this branch can carry.

The fix keeps the governance and restores the census population: the
governed seam's provider backend now delegates to the one shipped
dispatcher, `services.tool_executor.dispatch_tool` (the exact arrangement
the trusted base's boot path used beneath `admitted_tool_executor`), so
admission — contracts, allowlist, tier, Binding, Invocation — stays in
`services.governed_tools` above the dispatcher while no new module gains
model-egress capability. The three `governed_tools.py` call-site rows left
`quality/direct-effect-call-sites.json` (the sites no longer exist;
`--update` pruned exactly those three, 54 -> 51 sites), and
`check-model-egress.py` reports the trusted population again (20 physical
model callers, no candidate-approved expansion).

Tests (`tests/test_check_model_egress.py`, +2):

- `test_a_new_module_calling_the_model_backed_clarify_wrapper_counts` pins
  the census triple itself: a synthetic module calling
  `tool_executor.clarify(...)` is one `MODEL_EFFECT` / `hive.clarify`
  finding, so any future wiring that re-lists the model-backed wrapper
  becomes a frozen new model-egress caller — the census, not a reviewer,
  flags it.
- `test_the_shipped_governed_tool_seam_performs_no_census_model_egress`
  pins the shipped invariant this delegation restored:
  `services/governed_tools.py` performs no census model egress. Verified
  to fail against the pre-fix file (head `6abcbb367` had the
  `MODEL_EFFECT`/`hive.clarify` site at line 216) and pass after.
