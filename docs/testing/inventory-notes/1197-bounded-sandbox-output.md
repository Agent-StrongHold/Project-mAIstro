---
inventory-delta:
  packages/maistro-core/tests: +7
---
# #1197 — bounded sandbox output capture

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

Scope reconciliation: `maistro/sandbox/detect.py` still uses
`capture_output=True`, but only around the host capability probe — a fixed,
host-chosen coreutils binary with no workload data, bounded by
`PROBE_TIMEOUT_S`. The issue's stop condition is about bounding capture of
*untrusted workload* output, so that path is out of scope. The docker-based
executor under `maistro/tools/sandbox/` is a separate pre-SPEC-190 subsystem,
not one of the substrate backends named by this issue (bubblewrap + fake).
