---
inventory-delta:
  packages/maistro-core/tests: +1
---
# Issue #1199 CI repair — cross-process peer port-file race

The merge-queue evaluation of this branch (coverage (no services) at
`49e60c36282ed35d4b8d9dcde8fea1c17cb97b92`, job 117695232419) failed on
`packages/maistro-core/tests/a2a/test_guest_peers.py::test_cross_process_peer_injection_refused_by_canonical_warden`
with `ValueError: invalid literal for int() with base 10: ''`; 15389 other
tests passed. `gates-ran` went red downstream of it ("Coverage gate (publish-set
floor + diff coverage): present but did not execute to a verdict").

## Root cause (from the CI log, not inferred)

The embedded `_PEER_SERVER` child created the port file with
`open(path, "w")` — which makes the path visible while still empty — and only
then wrote and flushed the port. The parent's `_base_url()` polled
`exists()` and immediately `read_text()`, so a poll landing inside that window
read `''` and raised `ValueError` instead of waiting. The failure is a load
dependent interleaving, inherited from `origin/develop` (this branch's diff vs
develop is docs-only); it surfaced on the loaded coverage runner (after the
docker pre-pull retries).

## Fix

Both sides, in `packages/maistro-core/tests/a2a/test_guest_peers.py`:

- child: write the port to a sibling `.tmp` file and `os.replace` it over the
  final path, so the announced name only ever exists with complete content;
- parent: treat an empty/unparseable read as not-ready and keep polling to the
  deadline (defense in depth for non-atomic filesystems).

## Regression proof

`test_base_url_tolerates_a_transiently_empty_port_file` freezes the losing
interleaving deterministically: the port file exists and is empty when the
first poll lands, and the port arrives 0.2s later. Run against the unfixed
helper it failed with the CI's exact error and line
(`ValueError: invalid literal for int() with base 10: ''`,
`test_guest_peers.py:114`); with the fix it passes across repeated runs, and
the full a2a directory passes (281 passed, including the real cross-process
peer tests that exercise the atomic child publish).
