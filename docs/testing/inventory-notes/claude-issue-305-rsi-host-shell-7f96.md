---
inventory-delta:
  packages/hive-conductor/backend/tests: +58
  packages/maistro-bootstrap/tests: +4
  packages/maistro-rsi/tests: +33
  tests/: +25
---
# claude-issue-305-rsi-host-shell-7f96

All new, in three modules. Nothing removed or renamed, and no production
behaviour is asserted differently — the existing conductor and RSI suites pass
unchanged.

`test_rsi_execution_containment.py` (+55) is the boundary. The retained exploit
comes first (an arbitrary host path, a shell command, six metacharacter
payloads), then containment (`..`, a symlink planted inside an authorized root,
a non-repository directory, no root configured at all), then the test-command
policy, the profile overlay's refusals, isolation attestation, the three output
directories a caller may no longer aim, and finally the success path — every other test in the file asserts a refusal, and a route that
refused *everything* would satisfy all of them.

`test_no_host_shell_execution.py` (+20) covers the loop: the argv runs without a
shell and wins over the string, a metacharacter in a token stays one argument,
the CLI's shell path is unchanged, the sandbox handed to the apply function
refuses `exec` under container isolation while still reading and writing the
worktree, and `evaluate_candidate` threads the argv through to the fitness gate.

Six of those arrived after review (Codex, #305), for the finding that an
argument vector is not an isolation boundary: `shell=False` decides how the
first command is parsed, not whose code runs afterwards, and `python -m pytest`
imports the candidate's test modules, `conftest.py` and declared plugins. Three
cover the routing — a contained run never reaches the host, it carries the
vector/image/timeout the config names, and a *local* run still uses the host so
a loop that contained everything could not pass by containing too much. Three
cover the fitness refusal.

`test_contained_validation.py` (+13, new) is the seam's own suite: the verdict
comes from the container's exit status, a non-zero exit stays an ordinary
failure rather than an error, the container is seeded from the candidate
directory and torn down, and every way containment can fail — empty vector,
unimportable backend, a sandbox that raises — refuses instead of returning a
verdict.

`test_check_shell_execution.py` (+25) is the new gate's own suite: what it finds
in a source file, and that the ledger is exact in both directions -- including
five cases for `shell=` expressions the gate cannot read as `False`, which a
literal-only match let through undeclared.

The conductor suite gains three more after review:
`test_the_builders_factory_is_told_which_sandbox_to_build` (the factory
defaults to `isolation="local"`, and an injected apply function wins over the
one the loop would have built, so omitting the argument handed an
HTTP-initiated run an agent that executes on the host) and two in
`test_rsi_review_decisions.py` for the review route's unvalidated `repo_path`,
which reached `git am` and `gh pr create` while the run route next door
resolved its own through policy.

## The conductor number is 55, not 56

Collecting this branch shows +56 against the recorded expectation. One of those
is not this change: `e8a9ad9` (#485) added a test and shipped no note, so
`develop` has been one node ID over since. That +1 is recorded in its own note
on the #497 branch, attributed to #485. Recording it here instead would double
it once both land, and would file someone else's delta under this change.

`test_container_sandbox_argv_status.py` (+4, new) covers the two entry points
this change added to `ContainerBuilderSandbox`. The existing container suite is
docker-gated in full, so `run_argv_status` and the `run_argv` that now delegates
to it ran nowhere CI could measure — and what they decide does not need a
container. `_exec` is stubbed at the seam where the container's result arrives:
a failing command reports its status rather than only its noise, a passing one
reports zero (or a seam that always answered "failed" would satisfy the first),
`run_argv` still returns output alone because for the agent tool the output *is*
the answer, and the caller's timeout reaches the container rather than being
silently replaced by the default — a validation run is long, and substituting
120 seconds would fail a candidate for taking the time it was given.
