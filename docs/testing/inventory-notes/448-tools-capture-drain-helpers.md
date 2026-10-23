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

Local measurement note (corrected 2026-10-19): an earlier version of this
paragraph claimed this WSL host undercollects `maistro-core/tests` by 31
capability-parametrized nodes because `detect_host_capabilities` cannot
evidence bubblewrap here. That claim is wrong, and re-measuring on this host
at the develop tip (e708451b) disproves it: `pytest
packages/maistro-core/tests --collect-only -q` collects **16503**, exactly
develop's own recorded expectation, with `detect_host_capabilities()`
refusing bubblewrap (`Creating new namespace failed: Resource temporarily
unavailable`). Collection is capability-independent — no test file
parametrizes over live host tiers — so the −31 the suite-inventory gate
reported on the branch was never a host gap. It was a ledger overcount: two
sibling lane notes (`auto-448-a9e4`, `auto-448-c63b`) still carried deltas
for tests the develop sync had consolidated away (develop's 9-test
`tests/sandbox/test_capture.py` replaced the branch's 18-test version
verbatim, and its +10 of docker/microvm/import-layering additions are the
+10 counted above). Both notes' core deltas are withdrawn in their own
amendments; with that, this note's +28 is the suite's entire true increment
over develop (sandbox+tools subtree: 673 → 701 collected), and the gate
reads expected 16531 == collected 16531 on this host and on CI's runner
alike.
