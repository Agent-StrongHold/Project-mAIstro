---
inventory-delta:
  tests/: +13
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

## Test delta (+13, all in `tests/test_check_api_route_contracts.py`)

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
- `test_registered_valid_temporary_disposition_excuses_logging_only_handler`
  (+1, repair round): a registry entry with a tracking issue and a future
  expiry suppresses the canned finding for the logging-only identity and the
  gate passes — the documented escape hatch must reach this handler class.
- `test_expired_temporary_disposition_does_not_excuse_logging_only_handler`
  (+1, repair round): a stale review date leaves the identity unexempt, so the
  registry failure and the canned finding both fire.

## Fail-before proof (recorded before the detector change; re-executed in the repair round)

`uv run pytest tests/test_check_api_route_contracts.py -q` against the
unmodified detector (develop base `94781cf6b708`), on the committed 49-case
file: **9 failed, 40 passed** — the five parametrized observability cases, the
drift guard, `test_logging_only_constant_handler_is_flagged`,
`test_gate_rejects_logging_only_handler_without_disposition` (the gate printed
`check-api-route-contracts: OK (1 handlers scanned, 0 audited routes
registered, 0 canned)` for the logging-only route), and
`test_expired_temporary_disposition_does_not_excuse_logging_only_handler`,
whose base-detector run reported only the registry finding
(`1 finding(s): - /reload: temporary disposition expired ...`) because the
base detector does not classify a logging-only body as canned — the asserted
`canned route handler` line never appeared, and only after the fix do both
signals fire in one run. The two conservative cases and the domain-acknowledgement case passed
before and after, as intended. The remaining repair-round case,
`test_registered_valid_temporary_disposition_excuses_logging_only_handler`,
passed before and after — but for different reasons: on the base detector the
logging-only handler was never canned (the observability call suppressed the
finding, the original escape), so the registry check alone decided the exit;
after the fix the handler is a real canned finding and the entry's valid
temporary disposition is what suppresses it. Only the after-behavior exercises
the escape hatch, which is the state this test pins.

Reconciliation: an earlier draft of this note recorded "8 failed, 34 passed"
/ "42 passed"; those runs predate the parametrization of
`test_observability_call_alone_is_not_real_work` (+5 collected cases), so they
undercounted the same suite by exactly those five cases. A second drift
(round of 2026-10-05, CI `test` job) was the delta itself: this note recorded
`tests/: +11` while the repair commit added two more cases, so collection
(4554) outran baseline + deltas (4552) by exactly those two. The front-matter
delta is now +13, matching `pytest --collect-only -q` on the merge base
(`94781cf6b708`: 4541) against this tree (4554). The numbers above are
re-executed against the committed 49-case file: the develop-base
(`94781cf6b708`) `scripts/check-api-route-contracts.py` (which contains no
`_LOG_LIKE_CALL_NAMES` and does not filter exempt identities out of the canned
findings) was run under a synthetic root holding the committed
test file plus the shipped `routes/`, `quality/api-route-contracts.json`, and
`docs/api/route-contract-inventory.md`; the failure set is exactly the nine
regressions named above, and `test_registry_happy_path_on_the_shipped_inventory`
/ `test_main_passes_on_this_tree` pass on the base detector too — independently
confirming "0 handlers newly flagged" on the shipped tree.

## Validation (this tree)

After the change: `uv run pytest tests/test_check_api_route_contracts.py -q` →
49 passed. `uv run pytest packages/hive-conductor/backend/tests/test_noop_route_contracts.py -q`
→ 15 passed (the shipped-behavior proof runs the gate as a subprocess against
the real tree). `uv run python scripts/check-api-route-contracts.py` → `OK
(279 handlers scanned, 15 audited routes registered, 0 canned)`, exit 0.
`scripts/check-shipped-surface-truth.py` → exit 0 (the mirrored vocabulary
leaves #1144's gate green on the same tree). `uv run ruff check` /
`ruff format --check` clean on the changed files. `scripts/check-suite-inventory.py`
clean after recording this note's delta (`tests/: 4554` = baseline +13), and
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` → exit 0 (1338 reviewed identities = 1338 findings; the
change touches only `scripts/` and `tests/`).
