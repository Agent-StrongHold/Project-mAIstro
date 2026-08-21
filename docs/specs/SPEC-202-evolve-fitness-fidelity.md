---
id: SPEC-202
title: "Evolve fitness fidelity — proxy/real benchmark honesty, signal provenance, adapter contract"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-09
substrate:
  - maistro-engine#ADR-039
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Evolve
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-09
---

# SPEC-202: Evolve Fitness Fidelity

## Problem

`maistro-evolve` selects, mutates, and promotes pipeline genomes using a fitness
function whose dominant term (`eval_score`, weight 0.65) is produced by benchmark
runners named after industry-standard evals — `swebench`, `gaia`, `tau_bench`,
`osworld`, `ifeval`, `bfcl`, `ragas`, `terminalbench`. These runners do **not**
execute the named benchmarks against their official datasets/harnesses. They score
model output against small handcrafted sample sets.

The optimizer is only as trustworthy as its fitness signal. This spec makes the
signal honest.

## Design

### 1. Signal taxonomy — no stub tier

There is deliberately no `stub` tier: a benchmark either evaluates a real model
response against real criteria, or it does not run at all. An earlier draft of
this spec proposed a `stub` tier (`random.uniform()`, gated but tolerated) — that
tier was removed outright, not gated, because a fitness signal that can silently
become noise is worse than no signal.

| Tier | Meaning | Trust for promotion |
|------|---------|---------------------|
| `proxy` | A lite-weight version of the real methodology — small handcrafted/lite sample sets, but genuine scoring (rule verification, exact-match, tool-call matching, real sandboxed execution + assertion/state checks). Exists to save time/money and produce Pareto (cost vs. quality) signal, not to fake the official eval. | Development only; this is the default and what every benchmark below ships today. |
| `real` | The official published benchmark harness against the official dataset | Implemented for **`ifeval`** and **`bfcl`** (see §3a). `EvalHarness(benchmark_fidelity="real")` registers the *available* real adapters and nothing else; it raises only if none can run in this environment. It never silently downgrades a benchmark to proxy. |

### 2. Rename to remove false claims

- `use_real_benchmarks` → `benchmark_fidelity: Literal["proxy", "real"]` (no `"stub"`)
- Default: `"proxy"` (honest about what ships today)
- `REAL_BENCHMARKS` → `PROXY_BENCHMARKS` for the current runners

### 3. Per-benchmark methodology (proxy tier)

| Benchmark | Type | Proxy methodology | Execution |
|-----------|------|-----------------|----------------|
| `ifeval` | Rule-checking | Handcrafted instructions, real per-rule verifier functions | No |
| `bfcl` | Function-calling | Handcrafted calls, real tool-call/param matching | No |
| `ragas` | RAG quality | Handcrafted samples, real scoring functions | No |
| `gaia` | QA accuracy | Handcrafted questions, exact-match + LLM-judge | No |
| `tau_bench` | Tool-use | Handcrafted scenarios, real tool-call verification | No |
| `swebench` | Code patch | Handcrafted buggy/fixed function pairs, **real sandboxed subprocess execution** (`benchmarks/sandbox_exec.py`): candidate code runs in a fresh tempdir subprocess, asserted against the real expected value | Yes — process-level sandbox |
| `terminalbench` | CLI task | Delegates to `executable_terminal.py`'s real filesystem-state verification (restricted JSON action language, tempdir-based) | Yes — tempdir-scoped |
| `osworld` | Desktop task | **Not implemented.** `run_osworld` raises `NotImplementedError` and is not registered in `PROXY_BENCHMARKS` — no desktop-VM/GUI-automation infra exists in this repo. Reference task definitions remain in `datasets.py` for when that infra lands. | N/A |

### 3a. Implemented `real` adapters

Two benchmarks now run the official grader against the official dataset. Both
qualified for the same reason: a deterministic official grader over response
text, needing no container, reference solution, or judge model — so the entire
cost of making each real was the LLM calls.

| Benchmark | Adapter | Corpus | Grader | Headline `score` |
|-----------|---------|--------|--------|------------------|
| `ifeval` | `benchmarks/ifeval_real.py` | official 541 prompts, 25 instruction types | Google Research's own verifier, vendored | prompt-level strict (all four official metrics in `metadata`) |
| `bfcl` | `benchmarks/bfcl_real.py` | official BFCL v4 **Python-AST track** only — 1,000 instances across `simple_python`/`multiple`/`parallel`/`parallel_multiple` | the leaderboard's own `ast_checker`, vendored | instance-weighted aggregate; per-category accuracies (the leaderboard-comparable numbers) in `metadata` |

Contract points that bind consumers:

- **Vendored, pinned, and byte-verified.** Corpora and graders live under
  `benchmarks/third_party/`, reproduced by `scripts/vendor_{ifeval,bfcl}.py` and
  pinned by sha256 of both the upstream bytes and the *rendered* vendored bytes.
  `--check` runs in `quality.yml`. Pinning the rendered bytes is what makes the
  guarantee real: an earlier version verified only the provenance header, so
  grading logic could be edited freely and CI still passed.
- **Optional includes.** Each adapter exposes `available() -> (ok, reason)`. A
  real harness registers only what passes and records the rest on
  `EvalHarness.unavailable_real` with an install hint. Unavailable ≠ proxy: an
  unavailable adapter is skipped when unnamed and *raises* when explicitly
  requested. `bfcl`'s checker is stdlib-only, so a real harness is never empty;
  `ifeval` needs the `ifeval` extra plus nltk `punkt` **and** `punkt_tab`.
- **Tier separation is enforced, not conventional.** `register_benchmark`
  refuses a proxy runner on a real harness; requested benchmarks are validated
  as a whole set *before* any runner spends money.
- **`official_comparable`** is `True` only for a full, unsampled, unsplit,
  error-free run. Sampling and splitting both cover a subset and set it `False`.
- **Enforced train/holdout splits**, hashed by instance key so every instruction
  type / category appears on both sides. These detect harness-level overfitting;
  they cannot address pretraining contamination of a public corpus.

Official-dataset/official-harness `real` adapters for the remaining benchmarks
(SWE-bench, Terminal-Bench, τ-bench) remain future work. `gaia` and `ragas` are
slated for removal/renaming rather than promotion.

### 4. Fitness gate enforces fidelity

- A benchmark runner with no `llm_call` raises `ValueError` rather than falling
  back to a heuristic or fabricated score
- `compute_fitness(min_fidelity="real")` fails proxy-scored genomes
- `PipelineGenome.fitness_score` annotated with lowest gated-benchmark fidelity

### 5. Adapter contract

```python
class BenchmarkAdapter(Protocol):
    name: str
    fidelity: Literal["real"]

    async def evaluate(self, candidate_output: str, instance: BenchmarkInstance) -> EvalResult:
        """Score against official dataset instance. Returns EvalResult with metadata.fidelity='real'."""
        ...

    async def self_conformance(self) -> bool:
        """Reproduce a known reference score on a held-out instance. Must pass to register."""
        ...
```

### 6. Registration rules

- `REAL_BENCHMARKS` contains only adapters that passed `self_conformance()`
- Requesting `fidelity="real"` with no real adapter → hard error (no silent downgrade)
- CI runs `self_conformance()` for all registered adapters on every PR

## Acceptance criteria

- [x] Every `EvalResult` carries `metadata.fidelity ∈ {proxy, real}` — no `stub`
- [x] `benchmark_fidelity` replaces `use_real_benchmarks`; default is `"proxy"`;
      `EvalHarness(benchmark_fidelity="stub")` (or any other value) raises `ValueError`
- [x] Handcrafted runners registered under `PROXY_BENCHMARKS` (7 entries — `osworld`
      is intentionally absent)
- [x] `fidelity="real"` with no adapter raises hard error (tested)
- [x] No runner ever produces a fabricated/random score — every proxy runner
      either scores a real model response against real criteria or raises
      `ValueError` when given no `llm_call`
- [x] `swebench` executes candidate code in a real sandboxed subprocess and
      asserts against the real expected value (`sandbox_exec.py`), rather than
      keyword/line-change heuristics
- [x] `terminalbench` is wired onto `executable_terminal.py`'s real
      filesystem-state verification, rather than keyword heuristics
- [x] `osworld` raises `NotImplementedError` and is unregistered rather than
      returning a fabricated or heuristic score
- [x] `reflective_improve`/`hyper_mutate` refuse to accept a candidate verified
      only by a result carrying `metadata["stub"] = True` (defensive — no
      shipped runner sets this today, but a custom-registered runner can)
- [ ] `compute_fitness(min_fidelity="real")` fails proxy-scored genomes (tested)
- [x] `run_cycle` logs WARNING banner naming run's fidelity
- [ ] Official-dataset/official-harness `real` adapters for any benchmark
      (loading the actual SWE-bench/BFCL/GAIA/etc. datasets and running their
      published evaluators) — future work, out of scope for this round
- [ ] `PipelineGenome.fitness_score` annotation reflects lowest fidelity
- [ ] All adapters run in CI; failing self-conformance blocks merge
