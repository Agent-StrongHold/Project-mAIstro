---
inventory-delta:
  packages/maistro-core/tests: +28
---
# #448 — direct contracts for the tools-layer bounded drain helpers

`packages/maistro-core/tests/tools/sandbox/test_capture_helpers.py` is new: 18
tests driving `maistro.tools.sandbox._capture` directly — the policy clamp
(`clamped_output_limit` including the non-positive `ValueError` arm and the
ceiling clamp), `truncation_notice`'s exact notice text, `read_stream_bounded`'s
verbatim / exact-boundary / drain-past-limit arms, `communicate_bounded`'s
merged-stream (`stderr=STDOUT`) `_empty` arm plus simultaneous two-stream
overflow with the child's real exit status preserved, `capture_fd_sync` on a
real pipe, and `run_bounded`'s verbatim, simultaneous-overflow, non-positive
limit rejection, timeout-kill, and lingering-descendant (join-deadline)
behaviors.

The remaining +10 of the delta are this branch's earlier test additions now
measured against the develop tip the branch merged:
`tests/tools/sandbox/test_docker.py` +4, `tests/tools/test_microvm_sandbox.py`
+3 (both pre-existing on the branch, counted file-by-file here), and
`tests/sandbox/test_import_layering.py` +3 (the import-matrix proof).

Two mutations verified the new tests bite: making `read_stream_bounded` /
`capture_fd_sync` retain whole chunks unbounded fails the drain-past-limit
tests, and swallowing `run_bounded`'s `timed_out` flag fails the timeout test.

Local measurement caveat (why `check-suite-inventory.py` still reports
`maistro-core/tests` at -3 on this host): this WSL host's `dev` user exceeds
the `max_processes=128` budget the bubblewrap probe self-enforces (#1235), so
`detect_host_capabilities` cannot evidence tiers here that CI's runner class
can, and 31 capability-parametrized nodes that CI collects do not collect here
(`16517 = 16520 - 31 + 28`). The gap is pre-existing — plain arithmetic gives
develop's own local collection as 16489 against the same ledger — and this
branch changes none of it: its four touched test files are plain additions,
verified stable at 16517 under bwrap-patched and DOCKER_HOST-perturbed
re-collection. The authoritative arithmetic runs where the ledger was recorded,
in CI.
