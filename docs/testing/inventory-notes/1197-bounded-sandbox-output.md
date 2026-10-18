---
inventory-delta:
  packages/maistro-core/tests: +19
  tests/: +1
---
# #1197 — bounded sandbox output capture

The `tests/: +1` line records a drift this branch did not create. Collection
node IDs for the root suite are byte-identical to the branch base
`2f56be40ad24`: the +1 arrived with the develop tip itself, when PR #1993
(commit `edb669149`) added
`test_hive_preset_tracks_the_executable_registry` to
`tests/security/test_sentinel_permission_table_armed.py` without recording a
delta. CI on develop fails the same gate step for the same reason (run
39112583663, job `test`), so this note carries the missing +1 — the ledger
sum then matches collection on the merged tree, which is the reconciliation
mechanism the gate's failure message prescribes. Nothing was removed or
renamed to make the numbers meet.

The sandbox protocol now treats stdout and stderr as host-owned resources. Fake
backend coverage drives concurrent unbounded writers and proves retained bytes
stay within the configured per-stream policy, overflow terminates execution,
and the result reports truncation. The real bubblewrap test runs the same
exhaustion case when the production backend is available; otherwise the test's
capability skip is explicit.

The sixth test covers the cancellation arm of the issue's "must not wedge the
executor" clause: cancelling `exec` while a silent workload is live must
propagate `CancelledError` promptly and leave no orphaned child behind. The
leak check is a bounded `/proc` scan for this process's live children carrying
a script marker (zombies have an empty cmdline and do not match), which is
Linux-only — matching the substrate's POSIX assumptions elsewhere. The
timeout arm is covered by the pre-existing timeout tests on both backends.

The seventh test closes the issue's #80-conformance criterion: the
output-exhaustion case (both streams flooded simultaneously) now runs in
`test_escape_conformance.py` against the production bubblewrap backend,
not only in the sibling #76 backend file. On a host where the probe refuses
bubblewrap under the conformance budgets (e.g. a uid whose live task count
exceeds the `max_processes` rlimit, as on the WSL dev box), the suite skips
with the probe's reason — the substrate's fail-closed evidence contract, not
a silent pass.

The eighth through tenth tests arrived with the two follow-up commits. The
setsid probe (`test_escape_conformance.py`) proves a PID-namespace grandchild
cannot outlive the timeout. The runner tests (`test_sandbox_runner.py`) pin
the `ExtensionSandboxOutcome` propagation: an output-limit kill lands as a
`RESOURCE_LIMIT_EXCEEDED` violation in the `SandboxViolationLog`, and
repeated output-limit violations escalate through the same quarantine path
as any other repeated violation.

The setsid probe's argv shape was repaired in this round: the original
`exec setsid --fork ...` made setsid's parent — bwrap's direct child — exit
immediately, so the kernel tore the PID namespace down and the workload
"completed" in ~30 ms instead of reaching the timeout (observed as a red
test on the merge queue, `timed_out is True` failed with `exit_code=0`).
The fixed shape keeps the direct child alive with a foreground `sleep` so
the clock timeout is what fires; verified against the kernel on a host
where bubblewrap runs (relaxed process budget): exit 124, `timed_out=True`,
zero marker-bearing survivors after destroy.

`test_capture.py` (nine tests) pins the bounded-capture arcs a passing
workload cannot reach: exact-boundary retention (one-read overshoot and
exact-fill-then-overflow), the pipe-less caller guard, transport-less and
pid-less process handling, the bounded reap of an unkillable child, the
bounded collection when a detached descendant holds a pipe open, and the
refusal of negative capture bounds.

Scope reconciliation: `maistro/sandbox/detect.py` still uses
`capture_output=True`, but only around the host capability probe — a fixed,
host-chosen coreutils binary with no workload data, bounded by
`PROBE_TIMEOUT_S`. The issue's stop condition is about bounding capture of
*untrusted workload* output, so that path is out of scope. The docker-based
executor under `maistro/tools/sandbox/` is a separate pre-SPEC-190 subsystem,
not one of the substrate backends named by this issue (bubblewrap + fake).
