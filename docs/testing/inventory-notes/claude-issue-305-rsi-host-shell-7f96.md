---
inventory-delta:
  packages/hive-conductor/backend/tests: +49
  packages/maistro-rsi/tests: +14
  tests/: +20
---
# claude-issue-305-rsi-host-shell-7f96

All new, in three modules. Nothing removed or renamed, and no production
behaviour is asserted differently — the existing conductor and RSI suites pass
unchanged.

`test_rsi_execution_containment.py` (+49) is the boundary. The retained exploit
comes first (an arbitrary host path, a shell command, six metacharacter
payloads), then containment (`..`, a symlink planted inside an authorized root,
a non-repository directory, no root configured at all), then the test-command
policy, the profile overlay's refusals, isolation attestation, and finally the
success path — every other test in the file asserts a refusal, and a route that
refused *everything* would satisfy all of them.

`test_no_host_shell_execution.py` (+14) covers the loop: the argv runs without a
shell and wins over the string, a metacharacter in a token stays one argument,
the CLI's shell path is unchanged, the sandbox handed to the apply function
refuses `exec` under container isolation while still reading and writing the
worktree, and `evaluate_candidate` threads the argv through to the fitness gate.

`test_check_shell_execution.py` (+20) is the new gate's own suite: what it finds
in a source file, and that the ledger is exact in both directions.

## The conductor number is 49, not 50

Collecting this branch shows +50 against the recorded expectation. One of those
is not this change: `e8a9ad9` (#485) added a test and shipped no note, so
`develop` has been one node ID over since. That +1 is recorded in its own note
on the #497 branch, attributed to #485. Recording it here instead would double
it once both land, and would file someone else's delta under this change.
