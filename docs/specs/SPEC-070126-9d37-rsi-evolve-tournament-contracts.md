---
id: SPEC-070126-9d37
title: "RSI code-improvement tournament contracts"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-01
substrate:
  - maistro-engine#ADR-070126-6386
related:
  - maistro-engine#ADR-088
  - maistro-engine#ADR-093
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-rsi/tests/test_variant_merge.py
  - packages/maistro-rsi/tests/test_competitors.py
  - packages/maistro-rsi/tests/test_scout.py
  - packages/maistro-rsi/tests/test_tournament_cycle.py
  - packages/maistro-evolve/tests/test_code_rsi_benchmark.py
  - packages/maistro-bootstrap/tests/test_temperature_threading.py
  - packages/maistro-rsi/tests/test_live_evolution.py
  - packages/maistro-rsi/tests/test_spec_tracker.py
  - packages/maistro-rsi/tests/test_checkpoint_report.py
  - packages/maistro-evolve/tests/test_improvement.py
layer: Evolve
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070126-9d37: RSI Code-Improvement Tournament Contracts

Implements ADR-070126-6386. Defines the testable contracts for turning an RSI
cycle into a scout→compete→select tournament driven by evolve genomes.

## Design

1. **Competitor config.** A `Competitor(model: str, temperature: float | None,
   label: str)` names one fixer configuration (a projection of an evolve
   `NodeGenome`). `parse_competitors("devstral-medium@0.2,codestral@0.7")`
   yields the list; a bare `"codestral"` means `temperature=None` (provider
   default). Whitespace-tolerant; empty string → empty list.
2. **Temperature threading.** `LiteLLMCallable(model, temperature=None)` includes
   `"temperature"` in the request body **iff** it is not `None`; a `None`
   temperature never adds the key (provider default). `make_builders_apply_patch`
   accepts and forwards `temperature`.
3. **Scout.** `scout_objective(source: str, llm_call) -> str` sends the file
   contents to one model and returns a single concrete improvement objective
   (stripped, non-empty). If the model returns empty/whitespace, fall back to the
   generic targeted objective. All competitors in a cycle receive the identical
   scout objective.
4. **Variant merge (competitive + complementary).** `greedy_merge(candidates,
   apply)` takes candidates already sorted by composite descending and an
   `apply(patch) -> bool` that returns whether a patch applied cleanly onto the
   accumulating result. It keeps a candidate when `apply` succeeds
   (complementary — different region) and skips it when `apply` fails
   (competitive — a higher-scored candidate already occupies that region).
   Returns the kept candidates in application order.
5. **Tournament cycle.** Per target file: run every competitor on the shared
   scout objective, score each with the existing `Scorecard`, keep only
   gate-passing candidates, rank by composite, `greedy_merge`, validate the
   combined result (re-score only when ≥2 kept), promote. A merge that regresses
   any gate falls back to the single top candidate.
6. **`code_rsi` benchmark.** `evaluate_code_rsi(genome, target, apply_and_score)
   -> EvalResult` returns `EvalResult(benchmark="code_rsi",
   score=scorecard.composite)`, with `score=0.0` when any gate is vetoed
   (evolve hard-gate parity). It never scores against a stub/absent suite
   (returns score 0 with `metadata["stub"]=True`).

## Acceptance criteria

- [ ] **AC-1** `parse_competitors` parses `"m@0.2, n , p@0.9"` into
  `[(m,0.2),(n,None),(p,0.9)]`, trims whitespace, and returns `[]` for `""`.
- [ ] **AC-2** `LiteLLMCallable` includes `temperature` in the POST body when set
  and omits the key entirely when `None`; `make_builders_apply_patch` forwards it.
- [ ] **AC-3** `greedy_merge` keeps all candidates when every `apply` succeeds
  (complementary changes to different regions are all kept).
- [ ] **AC-4** `greedy_merge` keeps only the first (highest-scored) of a set whose
  later `apply` calls fail (same-region competitors — best wins, rest dropped).
- [ ] **AC-5** `greedy_merge` keeps a mix: a high-scored change plus a later
  disjoint change that applies, while dropping a middle change that conflicts.
- [ ] **AC-6** The tournament cycle promotes the highest-composite gate-passing
  candidate when all competitors touch the same region.
- [ ] **AC-7** The tournament cycle keeps two complementary candidates (disjoint
  regions of the same file) and the promoted result contains both edits.
- [ ] **AC-8** When a ≥2-way merged result regresses a gate, the cycle falls back
  to and promotes the single top candidate (known-good), never the bad merge.
- [ ] **AC-9** `scout_objective` returns the model's objective stripped; on empty
  model output it falls back to the generic targeted objective.
- [ ] **AC-10** `evaluate_code_rsi` returns `score == scorecard.composite` on a
  passing candidate and `score == 0.0` when a gate is vetoed.
- [ ] **AC-11** `evaluate_code_rsi` returns `score == 0.0` and
  `metadata["stub"] is True` when the target suite is stubbed/absent (honesty).
- [ ] **AC-12** No tournament, scout, merge, or benchmark test depends on a real
  LLM provider, network, or wall-clock sleep (deterministic fakes only).

Amendment (2026-07-04, ADR-070126-6386 unified-evolution + maturity-ladder
amendment): the unified live loop, model bench/reliability, and the spec-
completion/backlog ladder.

- [ ] **AC-13** In `run --genome-db` mode, a real cycle's `Scorecard.composite`
  folds into the authoring genome via EMA (not overwrite): two consecutive
  real scores leave `eval_scores["code_rsi"]` between them, not equal to the
  latest one alone.
- [ ] **AC-14** A transient provider error (429/quota/billing/overload) benches
  the model instead of scoring its genome — no `eval_scores` entry is added
  for that cycle, and the model is excluded from the roster until its bench
  deadline. The deadline honors a provider-stated retry-after when the error
  names one (Groq body seconds, Gemini `retryDelay`, `retry-after` headers);
  otherwise it defaults to `bench_cycles` worth of estimated time and doubles
  on each consecutive bench of the same model, resetting when that model next
  scores real work.
- [ ] **AC-15** Per-model reliability is a run-local EMA (starts at 1.0, decays
  on transient failure, recovers on success) that multiplies into a genome's
  fitness during cull/breed selection — identical slot settings score lower on
  a less-reliable model than on a more-reliable one.
- [ ] **AC-16** `spec_completion` fires only when a candidate's changed tests
  add a **net-new** `@pytest.mark.ac("SPEC-x/AC-n")` marker (absent on
  baseline) for an AC enumerated in `docs/specs/*.md`, AND the candidate's
  tests pass; re-tagging an already-claimed AC earns nothing.
  `spec_proposed` fires only for a **new**, well-formed spec contract among
  the changed files (parseable `id:` frontmatter plus at least two enumerated
  acceptance criteria) — a stray markdown file earns nothing.
- [ ] **AC-17** In live mode, every checkpoint report (`build_checkpoint_report`
  with a population summary) includes an `## Evolution` section reporting
  population size, the generation histogram, the fittest genomes (name,
  generation, model, fitness, `tdd_rigor`, `test_style`), the per-model
  reliability table, and any currently-benched models; the section is absent
  entirely when no population summary is given (non-live runs).
