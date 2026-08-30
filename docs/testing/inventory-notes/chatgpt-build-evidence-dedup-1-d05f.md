---
inventory-delta:
  tests/: +13
---
# chatgpt-build-evidence-dedup-1-d05f

All thirteen node IDs are `tests/test_build_evidence.py`, added alongside
`scripts/build-evidence.py`: the fail-closed content-addressed build-evidence
identity primitive for the build-efficiency program (#654). No existing test
moved or was removed.

The first nine cover input-order independence, content/command sensitivity,
stable directory hashing, deduplication of overlapping inputs, and the three
fail-closed cases (missing input, empty directory, input outside the
repository root) plus an empty command.

Four more close the diff-coverage gap the merged branch exposed against the
script itself: a symlink input is hashed by what it points at rather than
its own bytes, and the CLI entrypoint (`main()`) writes a manifest to stdout
by default, writes it to `--out` when given, and reports an `EvidenceError`
on stderr with exit code 2 rather than a traceback.
