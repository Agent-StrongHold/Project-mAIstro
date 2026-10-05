---
inventory-delta:
  tests/: +11
---
# #1857 Reject logging-only success handlers in the API route-contract gate

`_performs_real_work` in `scripts/check-api-route-contracts.py` treated any
`Call` except `HTTPException(...)` as real work, so a handler whose body was
`logger.info("requested")` followed by `return {"status": "ok"}` evaded
`_canned_handlers` entirely: the observability call suppressed the finding and
the gate answered `OK ... 0 canned` for a route that acknowledged success for
an operation that only logged (#1857, found reviewing #1716's checker).

## Detector change (bounded)

A call is now exempt from the real-work evidence only when its target is
rooted in a plain name whose lowercased form is in
`_LOG_LIKE_CALL_NAMES = {"log", "logger", "logging", "metrics", "print"}` —
the same vocabulary and root-extraction semantics the shipped-surface gate
applies to the same judgment (#1144, `shipped_surface_truth._LOG_LIKE_CALL_NAMES`
/ `_call_root_name`). The constant is mirrored, not imported, because the two
gates are standalone scripts rather than a package (a hard sibling import
would make `check-api-route-contracts.py` unloadable outside
`python3 scripts/...` invocation); the reconciliation is enforced instead by
`test_observability_vocabulary_matches_shipped_surface_truth`, which fails if
either side's vocabulary moves without the other. Deliberately **not** adopted
from #1144's detector: `await`/`try`/`with`, attribute/subscript writes, and
the inert `object()` builtin — each of those only *widens* what counts as real
work here (fewer findings), which is out of this leaf's scope; the shipped
tree was scanned with the candidate detector first: 0 handlers newly flagged,
so no route or disposition changes are needed or made.

The module docstring gains an "observability vocabulary and its limits"
section (name-matching is syntactic evidence, not semantic verification of
arbitrary calls; `self.log.info(...)` and any non-plain-name root is never
exempted), and `docs/api/route-contract-inventory.md`'s CI-enforcement
paragraph is updated to match.

## Test delta (+11, all in `tests/test_check_api_route_contracts.py`)

- `test_observability_call_alone_is_not_real_work` (+5, parametrized over
  `logger`/`LOGGER`/`log`/`metrics`/`print` roots): a logging/metrics
  statement plus a constant return is not real-work evidence.
- `test_call_without_a_name_root_is_not_observability_evidence` (+1):
  `self.log.info(...)` stays real-work evidence.
- `test_non_observability_call_is_real_work` (+1): a name that merely
  resembles a log root is still real-work evidence.
- `test_observability_vocabulary_matches_shipped_surface_truth` (+1): the
  drift guard described above.
- `test_logging_only_constant_handler_is_flagged` (+1): the synthetic
  `logger.info(...); return {"status": "ok"}` route from the issue is flagged
  by `_canned_handlers`.
- `test_domain_call_with_constant_acknowledgement_is_not_canned` (+1): a real
  operation followed by a constant acknowledgement stays valid.
- `test_gate_rejects_logging_only_handler_without_disposition` (+1): the full
  `main()` gate fails the logging-only handler registered with no disposition.

## Fail-before proof (recorded before the detector change)

`uv run pytest tests/test_check_api_route_contracts.py -q` against the
unmodified detector: **8 failed, 34 passed** — the five parametrized
observability cases, the drift guard, `test_logging_only_constant_handler_is_flagged`,
and `test_gate_rejects_logging_only_handler_without_disposition` (the gate
printed `check-api-route-contracts: OK (1 handlers scanned, 0 audited routes
registered, 0 canned)` for the logging-only route). The two conservative
cases and the domain-acknowledgement case passed before and after, as
intended.

## Validation (this tree)

After the change: `uv run pytest tests/test_check_api_route_contracts.py -q` →
42 passed. `uv run pytest packages/hive-conductor/backend/tests/test_noop_route_contracts.py -q`
→ 15 passed (the shipped-behavior proof runs the gate as a subprocess against
the real tree). `uv run python scripts/check-api-route-contracts.py` → `OK
(279 handlers scanned, 15 audited routes registered, 0 canned)`, exit 0.
`uv run ruff check` / `ruff format --check` clean on the changed files.
`scripts/check-suite-inventory.py` clean after recording this note's delta.
