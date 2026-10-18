---
inventory-delta:
  tests/: +5
---
# 1860 — verify the declared handler identity in the API route registry

`scripts/check-api-route-contracts.py` required a nonempty `handler` field but
resolved each registry entry solely by `(file, method, path)` — a stale or
wrong nonempty name was never compared with the discovered function's name, so
the declaration could rot while the gate stayed green. `_check_registry` now
compares `entry["handler"]` with the resolved function's `name` and fails with
`handler identity drift: <METHOD> <route> (<file> @<path>) declares handler
'<declared>' but the live function is '<discovered>'; reconcile the inventory
entry`.

## Fail-before record (required by the issue)

Ran against the unfixed script at head `d7aa2714519a` via an in-process probe
(synthetic live identity `("synthetic.py", "get", "/things") ->
things_handler`, registry entry for that identity with
`handler="different_handler"`):

```
count: 1
failures: []
FAIL-BEFORE CONFIRMED: handler-identity drift produced NO finding
```

Exactly as the issue's source inspection predicted: no registry finding. After
the fix, the same fixture yields one `handler identity drift` failure naming
both handlers, and the full `main()` gate exits 1 on the drift alone with an
otherwise clean real-work route (`REAL_WORK` fixture) and a present inventory
document — asserted by `test_main_fails_on_handler_identity_drift_alone`.

## Root-suite delta (+5, all in `tests/test_check_api_route_contracts.py`)

- `test_registry_handler_drift_is_refused` — the required fail-before fixture
  (live `things_handler`, declared `different_handler`); asserts exactly one
  finding naming both the declared and discovered handler.
- `test_renamed_handler_fails_until_reconciled` — inverse rename: live
  function renamed to `renamed_things_handler`, inventory still declares
  `things_handler`; fails naming both.
- `test_correct_handler_identity_passes` — matching name passes cleanly.
- `test_unrelated_route_handler_cannot_satisfy_identity` — the declared name
  exists as a live handler on a *different* (file, method, path); the entry
  still fails, because identity resolution and the name comparison are both
  bound to the same identity.
- `test_main_fails_on_handler_identity_drift_alone` — end-to-end `main()`
  proof: exit 1, drift named with both handlers, no rot/canned findings.

The 31 pre-existing tests (missing-field, unknown-disposition, rot, temporary
issue/expiry, missing-registry, canned-handler, and clean-run regressions) are
unchanged and passing.
