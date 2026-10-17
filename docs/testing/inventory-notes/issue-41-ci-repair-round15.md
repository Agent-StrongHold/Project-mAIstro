---
inventory-delta:
  tests/: +6
---

# Issue 41 CI repair (round 15): cancelled gates-ran publisher must not smear failure

Delta note: `+6` against the `tests/` suite — six new node IDs in
`tests/test_gates_ran_publisher_contract.py`:

- `test_cancelled_publisher_publishes_nothing_and_does_not_fail`
- `test_blank_exit_code_is_pending_not_failure`
- `test_recorded_exit_codes_map_to_status_states[0-success]`
- `test_recorded_exit_codes_map_to_status_states[1-failure]`
- `test_recorded_exit_codes_map_to_status_states[2-pending]`
- `test_recorded_exit_codes_map_to_status_states[3-failure]`

## What the prior round actually caught

GitHub run 36274594751 (the `Gates Ran` workflow) failed on head
`05e46f7a7564adf459dbe5a3c21e87cbcd7c4e10` with a blank
`EVALUATION_EXIT_CODE` and published the red status "Required execution
evidence is missing or non-executed" on the candidate head. The run
annotations show the true cause: the job was cancelled by the workflow's own
concurrency group ("a higher priority waiting request for
gates-ran-pull_request-05e46f7a… exists"). The cancelled evaluate step never
wrote its exit code, and the `if: always()` publish step read that blank as
failure (`Number(process.env.EVALUATION_EXIT_CODE || '1')`), then called
`core.setFailed`. A superseded publisher thereby asserted that required
execution evidence was missing while the successor evaluation for the same
head was still the one that owned the verdict.

## The fix

`.github/workflows/gates-ran.yml` now:

1. passes `JOB_STATUS: ${{ job.status }}` into the publish step and returns
   early — no status, no failure — when the publisher was cancelled, leaving
   the verdict to the successor run that the concurrency group started for
   the exact same head; and
2. maps a blank/non-numeric exit code (evaluation never completed) to
   `pending` ("Required execution evidence is still arriving") instead of
   failure. Failure remains reserved for a recorded non-zero, non-pending
   evaluation verdict.

## The tests

The new tests execute the actual inline publish script from the workflow
artifact under `node` (skipped when `node` is unavailable), with faked
`github`/`core`/`context` bindings and a swapped `process.env`, mirroring how
`actions/github-script` runs the script inside an async function body. They
reproduce run 36274594751's exact inputs (cancelled job, blank exit code) and
assert no status is published and the job is not failed, plus the full
exit-code → status-state mapping including `gates-ran` as the status context.
