---
inventory-delta:
  tests/: +31
---

# 330-ci-repair-diff-coverage-and-contract

Thirty-one additions across five mutation-gate suites; nothing removed. This
round repairs the #330 CI red at head `9f73003f8384`: the diff-coverage gate
scored the new gate scripts below the 90%/80% floor, and the branch-protection
contract did not know the new check name.

**`tests/test_mutation_pr_gate.py` (+11).** The untested halves of the runner:
`measure_baseline` (green run returns wall seconds and propagates PYTHONPATH; a
red baseline aborts — a mutant measured against red proves nothing);
`read_baseline`'s unparseable-JSON and non-object-`entries` refusals;
`gate_source` measurement mode (whole-file group, no diff restriction), the
no-coverage refusal, and the zero-selected-tests refusal; and `main`'s CLI
plumbing (telemetry + checkpoint artifacts, measurement scope needing no
selection input, a run against nothing returning 1, and changed scope with
neither selection nor diff returning 1).

**`tests/test_mutation_critical.py` (+8).** The structural rejections between
parse and walk (non-object payload, missing `domains`, non-object entry), the
CLI surface (unreadable list exits 2, `--validate` reports the shape, no mode
is a usage error, `--changed-from -` reads stdin), and `_emit_targets`
bootstrapping `scripts/` onto `sys.path` when invoked cold.

**`tests/test_mutation_select_tests.py` (+9).** `select`'s red-baseline abort
and the executed-but-unattributable context warning (a line that ran under a
context collection cannot name stays uncovered, never silently grouped);
`_read_lines` (array, object, and the explicit empty-set refusal); and
`main`'s exit matrix — a clean selection writes the workflow artifact,
no-coverage lines fail the PR gate but pass `--allow-uncovered` measurement
runs, and zero groups refuse an empty mutation run even when allowed.

**`tests/test_mutation_baseline.py` (+1).** SKIPPED rows (annotation-filtered
mutants, via either `test_outcome` or `worker_outcome`) never enter the
denominator — counting them flattered the kill rate exactly the way
`mutation_viability.py`'s adjustment exists to prevent.

**`tests/test_mutation_packet_safety.py` (+2).** `--uploader none` uploads
nothing (no `node` invocation) but still checkpoints; and `main`'s continuation
contract: targets partition into pending/reused from prior checkpoints,
telemetry surfaces reset, and each executed source appends one telemetry row,
one session, and its rows file.

**`tests/test_check_ac_state.py` (stand-in repointed, count unchanged).**
`TestToolingReachesTheTopRung.DEAD_TOOL` moves from `@tool/mutation_ratchet` —
which #330's workflow restoration made genuinely reachable, so the committed
baseline banks it no more — to `@tool/mutation_filter_annotations`, still
invisible to the static graph. Both directions of the rung pin now read the
real ledger again.

All 31 fail or mis-direct against the pre-repair tree: the runner halves they
exercise did not exist, and the old stand-in contradicted the committed
reachability ledger.
