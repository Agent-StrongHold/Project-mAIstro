---
inventory-delta:
  tests/: +5
---
# 106-m4i-bench-script-covers-itself

Epic #106 (M4-I) landed `scripts/bench_m4i_adaptive_vs_fixed.py`, the renderer
for the adaptive-vs-fixed-routing comparison record
(`docs/benchmarks/m4i-adaptive-vs-fixed-baseline.json`), but no root-suite
test exercised it. Every sibling `bench_*.py` carries a `tests/test_bench_*.py`
for the same reason: the root suite is the coverage producer for `scripts/`,
so an untested script scores 0% changed lines and reds the diff-coverage gate.

`tests/test_bench_m4i_adaptive_vs_fixed.py` adds 5 node IDs:

- every compared arm is present with per-task rows covering the whole
  workload, and `tasks_succeeded` agrees with the per-task rows;
- the record cites its provenance (issue, epic, seam: what is production,
  what is stubbed);
- request-less tasks must be loud pre-egress refusals (failed, zero cost,
  named failure) — the no-vision-alias refusal path;
- the checked-in record regenerates byte-identically;
- `main` writes the record and prints the arm table.

Offline and stubbed at the httpx wire (~1.6s), inside the producer's 30s
per-test budget. `packages/maistro-core/tests` is untouched.
