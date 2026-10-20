---
inventory-delta:
  tests/: +8
---
# gates-ran-cli-scope-envelope

Eight regression tests exercise the CLI's changed-file scope envelope: measured
out-of-scope skips, in-scope failures, missing or unmeasured envelopes, invalid
file lists, unreadable envelopes, an unloadable scope classifier, and the
end-to-end green-head verdict. These tests were added after the path-scoped
producer contract and are recorded separately so the merged root-suite delta
matches the collected node population.
