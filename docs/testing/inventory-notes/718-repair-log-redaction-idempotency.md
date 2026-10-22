---
inventory-delta:
  packages/maistro-core/tests: 0
---

# Issue #718 repair lane — log-redaction idempotency test under pytest 9

While validating the #718 quota branch at head `0d502988d` plus the
`1dea30dfe` develop integration, `packages/maistro-core/tests/security/
test_log_redaction.py::test_install_is_idempotent` failed in the full
`packages/maistro-core/tests` run. The failure is pre-existing at the
starting head (pytest pinned at 9.1.1, identical test file, identical
`log_redaction.py` source, identical conftests — verified by
`git diff 0d502988d HEAD` on all four inputs), and is not quota-related.

## Root cause (observed, not inferred)

pytest 9's `_pytest.logging.catching_logs` attaches its `LogCaptureHandler`
to **every non-propagating logger** (new behaviour: "Attach to all
non-propagating loggers (won't reach root)"). The `captured` fixture sets
`propagate = False`, so between the fixture's `install_log_redaction` call
(fixture/setup phase) and the test body (call phase), pytest appends two of
its own unwrapped handlers to the very logger under test. The old assertion
`install_log_redaction(...) == 0` then counted pytest's handlers as
"newly wrapped" and failed with `assert 2 == 0`. Instrumentation (an
out-of-tree plugin logging `logger.handlers` at each install call) confirmed
the two `LogCaptureHandler` entries.

The product behaviour is correct and matches the documented contract in
`log_redaction.py`: "Handlers added *after* this call are not covered."
Wrapping pytest's mid-test handlers is the specified boundary, not a bug.

## Repair

The test now asserts the actual idempotency contract:

- the fixture's handler is wrapped exactly once (`inner` is not a
  `RedactingFormatter`), before and after a second install;
- the second install's return value equals exactly the number of handlers
  that were unwrapped immediately before the call (pytest's capture
  handlers), i.e. no already-wrapped handler is touched.

## inventory-delta rationale

No test added or removed; one assertion block rewritten to encode the
documented contract under pytest 9. Suite count for
`packages/maistro-core/tests` is unchanged at the recorded inventory, so
`scripts/check-suite-inventory.py` stays consistent.
