---
inventory-delta:
  tests/: +2
---
# #1857 develop sync: composition tests for the merged route-contract gate

The `auto-1857` branch (#1857: reject logging-only success handlers in
`scripts/check-api-route-contracts.py`) and `develop` (#1858: judge canned
routes by executed scope, not nested bodies) had both rewritten the same two
files, `scripts/check-api-route-contracts.py` and
`tests/test_check_api_route_contracts.py`. The sync merge resolves the
conflict by keeping both semantics: `_performs_real_work` walks the handler's
executed scope (`_walk_executed_scope`, #1858) *and* exempts log-like call
roots (`_LOG_LIKE_CALL_NAMES`, #1857); `_canned_handlers` collects returns via
`_own_scope_returns` (#1858) and still honors valid `temporary` dispositions
(#1857). The two pre-existing notes' deltas (`+13`, `+10`) remain true of the
merged file because the two branches' added tests are disjoint; this note
records only the merge round's own additions.

## Test delta (+2, all in `tests/test_check_api_route_contracts.py`)

Composition cases neither branch could state alone — both pass only with the
merged detector, and each fails if either side's semantics is dropped:

- `test_logging_inside_uncalled_nested_helper_neither_work_nor_evidence` (+1):
  a `logger.info(...)` call inside an uncalled nested definition is invisible
  to the executed scope (#1858), so it needs no observability exemption — and
  supplies no real-work evidence (#1857). Under the pre-merge #1857 detector
  (plain `ast.walk` over the body) the exemption fires inside the nested body;
  under #1858 without #1857 a `store.write()`-style call there would count.
- `test_logging_only_handler_with_uncalled_helper_is_still_canned` (+1): the
  route-level composition — `def audit(): store.write()` never invoked plus
  `logger.info(...)` plus a constant return is still a canned route. The
  uncalled helper neither rescues nor excuses the logging-only handler.

Both notes' fail-before claims are unchanged and were re-proven on their own
rounds; the merged gate's shipped-tree classification is unchanged (`0
canned`, all audited routes live), re-verified on the merge commit.
