---
inventory-delta:
  packages/maistro-core/tests: +19
---
# #1197 — bounded sandbox output capture

A previous revision of this note carried a second line, `tests/: +1`, as a
stopgap for a drift this branch did not create: the develop tip then had
`test_hive_preset_tracks_the_executable_registry` (PR #1993, commit
`edb669149`) without any recorded delta, so the PR merge tree collected one
more root node than the ledger expected. That stopgap is now **withdrawn**:
merging the develop tip (`1a2e12656`) landed the canonical record for the
same node, `1993-hive-permission-preset-inventory.md` (`tests/: +1`). With
both notes unfolded the ledger counted that node twice — CI's
"Suite inventory matches collected node IDs" step failed with
`DRIFT tests/: expected 5505, collected 5504` — and the stopgap line is the
side that must yield. The canonical note stays; nothing was removed from
collection to make the numbers meet.

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
