---
inventory-delta:
  tests/: +28
---

# 917 speculative parallel model-call benchmark (M8-B4 research leaf)

Implements the #917 deliverable (epic #900): a deterministic offline benchmark
comparing serial-fallback, single-strong, bounded parallel with early
stopping, and bounded parallel with verifier selection over the one governed
model seam, plus the research record and WATCH disposition in
`docs/research/917-speculative-parallel-model-calls.md` with numbers in
`docs/benchmarks/speculative-parallel-baseline.json`.

- `scripts/bench_speculative_parallel.py` — the harness. Every candidate call
  crosses the real `ModelChatEgress` (Binding pin → Invocation → approved
  gateway Provider) with a simulated provider physics transport
  (`httpx.MockTransport`, the documented no-network seam); the ledger audit
  refuses any physical call that does not resolve to exactly one Invocation,
  so duplicate speculative calls are measured, never hidden. No product path,
  flag, or canonical-semantics change.
- `tests/test_bench_speculative_parallel.py` — +28 `tests/` node IDs: the
  canonical router fallback chain as the serial baseline, deterministic and
  strategy-independent outcome schedule with provider-correlated outages,
  exact pinned-physics behavior of all four strategies including the
  nobody-acceptable degenerate paths, cancelled candidates surfacing as
  `UNKNOWN` Invocations with partial output billed to the cancel point,
  transient failures billing input only, completed Invocation usage matching
  the simulated gateway body, the ledger-audit refusals (zero or merged
  Invocations per physical call), byte-identical end-to-end runs for a fixed
  seed, and the published JSON payload shape (both `--output` branches and
  the argument-validation exits).
