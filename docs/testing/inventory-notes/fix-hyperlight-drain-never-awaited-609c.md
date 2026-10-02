---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# fix-hyperlight-drain-never-awaited-609c

**+2** in `packages/hive-conductor/backend/tests/test_hyperlight_executor.py`,
both regression tests for one defect in `SandboxExecutor._run_cancellable`:
`process.communicate()` was handed to `asyncio.wait_for` as a bare, unowned
coroutine. When `wait_for` raises *before* it reaches the `await` that would
consume that argument, nothing ever does — `coroutine 'Process.communicate'
was never awaited`, and a child whose pipes are left with no reader. Nothing
else in the suite moves.

**+1** `test_a_transport_failure_leaves_no_unawaited_drain` collects under
`warnings.catch_warnings(record=True)` with an explicit `gc.collect()`, and
asserts nothing matching `never awaited` / `communicate` was recorded.

**+1** `test_a_transport_failure_settles_the_drain_and_reaps_the_child` states
the same guarantee structurally and without depending on GC timing: what
`wait_for` receives is already an `asyncio.Future`, it is `done()` by the time
the failure is reported, and the spawned child has a `returncode`.

Both were confirmed red against the unfixed source at `4e50b461` and green
after it — the first on the recorded warning, the second on `drain is
unowned: <coroutine object Process.communicate>`.

## Why these are not `-W error::RuntimeWarning` tests

The obvious framing — run the transport-failure case under `-W
error::RuntimeWarning` so a dropped coroutine fails — **does not work**, and
is worth recording here so it is not proposed again as if it would.

The "never awaited" warning is raised by `warnings._warn_unawaited_coroutine`
during the coroutine's deallocation. Under an `error` filter it therefore
becomes an *unraisable* exception rather than one that can propagate into the
test, and pytest can only re-report it as a `PytestUnraisableExceptionWarning`
in the summary. Measured on the unfixed source, all three of these report the
warning and all three still exit **green**:

    pytest ...::test_a_transport_failure_is_reported_not_raised -W error::RuntimeWarning
    pytest ...::test_a_transport_failure_is_reported_not_raised -W error::pytest.PytestUnraisableExceptionWarning
    pytest ...::test_a_transport_failure_is_reported_not_raised              # 1 passed, 1 warning

A `filterwarnings` marker, or a repo-wide `filterwarnings` entry in
`[tool.pytest.ini_options]`, inherits the same hole: it would change how the
warning is *rendered* without ever failing a run. That is worse than no gate,
because it reads like one. Collecting deliberately and asserting on what was
recorded is what actually fails, so that is what the two tests above do; the
reasoning is repeated in the first test's docstring, where the next person to
reach for the marker will be standing.

No `filterwarnings` configuration is added by this change.
