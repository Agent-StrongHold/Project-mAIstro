# M8-L research plan — optimization, search, program synthesis, and learned improvement

Epic: #911. Initiative: #879.

## Hypothesis

Search and learning methods — evolutionary search, Bayesian/black-box
optimization, program/prompt synthesis, preference optimization from Run
outcomes, multi-objective optimization, search over tool/delegation policies,
archive/novelty methods, and cross-family transfer — can improve bounded
MAIstro artifacts (Graphs, prompts, Skills, routing policies, genomes, code
patches) beyond manual iteration while preserving independent evaluation and
governed promotion.

## Canonical seams (verified against the shipped tree)

The repo already has a governed improvement substrate; every candidate family
below must either reuse it or state explicitly why it cannot.

| Improvable family | Candidacy → activation seam | Optimizer that exists today |
|---|---|---|
| Pipeline genomes | challenger spawn → `promote_audited` with `approved_for_promotion` | `maistro-evolve` (experimental per ADR-088): `EloTournament`, population, crossover, `mutate`/hyper-mutation, curriculum |
| Graph/Node templates | `lifecycle="candidate"` → `promote_audited` (ADR-082926-65bf) | in-graph optimization signals (`maistro.graph.optimizer`: `NodePerformanceMetrics` / `OptimizationSignal` feedback) |
| Prompts | unlabeled version → `production` label move (`maistro.prompts.store`) | none beyond manual iteration |
| Skills | unvetted trust-tier floor → authenticated promotion, canary rollback (`maistro.skills`) | none |
| Code (RSI patches) | patch branch → Warden + RLPHD `promotion_review` (`maistro_rsi.promotion_review`) | LLM fixer loops under the containment surface (`maistro_rsi.sensitive_paths`) |
| Learnings | `status='candidate'` → gauntlet hit-count promotion (`maistro.memory.learnings`) | retrieval gauntlet, not search |

The one promotion authority is `maistro.governance.promotion`
(ADR-100126-a9c4, M4-A9 #116). Its fences are the boundary every M8-L
experiment stays inside:

- **evidence** — a candidate carries at least one evaluation Run id from the
  canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` ontology;
- **own-constitution** — an optimizer cannot retune its own evaluators or
  fitness function as a side effect (evolve's `EvaluationObjective` is already
  frozen and driver-owned for exactly this reason, `pop-owned-v2`);
- **self-approval** — the search path is an `author` provenance
  (`"evolve"`, `"rsi"`, `"learning"`), never the deciding authority;
- **staleness / no-op** — candidates are rebased or refused, never silently
  promoted over a moved base.

Evaluation environments are recorded with lineage (`maistro.eval_workspace`
carries nullable `run_id`/`node_run_id`/`attempt_id` on every snapshot), which
is what makes an optimization experiment's evidence auditable after the fact.

## Candidate research families

Status against the shipped tree: **exists** (experimental), **partial**, or
**absent**. Each family becomes a leaf that ends GRADUATE / INCUBATE /
REJECT / WATCH.

- **A. Evolutionary Graph/prompt search — exists (genomes), absent
  (templates/prompts).** `maistro-evolve` evolves pipeline genomes under a
  frozen weighted objective (`FitnessTermWeights`: eval 0.65, cost 0.15,
  latency 0.10, diversity 0.05, Elo 0.05) over the proxy benchmark suite
  (ifeval/bfcl/swebench/terminalbench/tau_bench/gaia). Evolving graph
  templates or prompts directly has no implementation. Leaf question: does
  evolutionary search beat manual iteration at equal evaluation budget
  without tripping the archive retention gate's historical-regression block?
  Baseline: the current champion plus manually iterated candidates.
- **B. Bayesian / black-box optimization — absent.** No optuna/skopt/botorch
  dependency exists in any package. Motivation: benchmark evaluation is the
  expensive black-box fitness (swebench/terminalbench-class runs), so sample
  efficiency is the failure mode of naive mutation loops. Candidate seam:
  evolve's fitness evaluation loop. Baseline: random/mutation search at equal
  evaluation budget. Metric: quality at matched evaluation count.
- **C. Program/prompt synthesis — partial.** RSI writes code patches via LLM
  fixer loops (not systematic synthesis) under the containment surface;
  prompt synthesis does not exist. Candidate seam: prompts family via
  `CandidateChange`. Risk: synthesized prompts gaming their own proxy judges.
- **D. RL / preference optimization from Run outcomes — partial.** RLPHD
  (`maistro.security.sentinel.rlphd.RlphdModel`) is a shipped point-estimate
  online logistic predictor — glass-box feature weights nudged toward
  realized approve/deny decisions — that *predicts human approval*; it is
  not an improvement optimizer, and ADR-100126-a9c4 deliberately keeps it a
  predictor feeding `PromotionApproval`. The uncertainty band that would let
  it express "I don't know" exists only as simulation
  (`scripts/rlphd_band_sim.py`, `rlphd_cold_start_sim.py`,
  `rlphd_two_tier_sim.py`), not in the shipped model. Learnings record Run
  outcomes but promote on retrieval gauntlet, not optimization. A
  preference-optimization leaf must consume canonical Run outcomes and stay
  under the self-approval fence.
- **E. Multi-objective optimization (quality/cost/latency) — partial.** The
  objective scalarizes cost and latency into fixed weights; `CostAwareRouter`
  and `maistro.router` (scarcity/speed/strength scoring) do multi-factor
  *selection* at inference, not multi-objective *search*. No Pareto-front
  machinery exists. Leaf question: does Pareto-based selection dominate the
  scalarized weights on the quality/cost/latency front at equal budget?
- **F. Search over tool/delegation policies — absent.** The policy surfaces
  are concrete (`maistro.policy` engine/gate/rules, router filter→score→rank,
  skills catalog) but nothing searches over them. Gaming susceptibility is
  the headline risk: a delegation policy optimized against a proxy benchmark
  can learn to route around evaluation rather than through it.
- **G. Archive / novelty methods — exists (experimental).**
  `maistro_evolve.archive` is an immutable append-only candidate archive with
  a historical-retention gate (a prior-scenario regression blocks promotion
  unless a `GovernanceDecision` changes the objective), explicitly
  DGM-style: archived stepping stones remain branchable. `diversity.py`
  carries a diversity bonus term. Novelty/complementarity objectives beyond
  the bonus are unexplored. Missing-evidence credit is already pessimistic
  (0.0, per #853).
- **H. Transfer of improvements across task families — partial.** Learnings
  retrieve across orgs by embedding similarity with gauntlet promotion;
  nothing transfers an optimized genome or prompt across task families.
  Generalization-beyond-the-optimization-set is the deciding metric.

## Comparison dimensions

Every leaf reports all six, per the epic contract: improvement yield, sample
efficiency, gaming susceptibility, reproducibility, compute cost, and
generalization beyond the optimization set. Negative findings are first-class
results (initiative guardrail 3).

## Reproducible artifacts

- evolve: the objective's version string (`pop-owned-v2`) and archive
  snapshots persist the exact weights and lineage of every campaign;
  benchmark harnesses live in `maistro_evolve.benchmarks` (proxy and real
  variants).
- RLPHD: `REPORT_DIR/rlphd_state.json` plus the three simulation scripts
  under `scripts/`.
- promotion: `PromotionRecord`/`PromotionLedger` rows carry scope, subject,
  both content hashes, evidence Run ids, evaluator versions and approval
  policy, so any graduated result traces to the measurements that judged it.

## Record

This note reports no experiment. No optimization, search, synthesis, or
learned-improvement method has been evidenced against a canonical MAIstro
seam under the epic's comparison dimensions. What exists today — the evolve
package, RLPHD, the learnings gauntlet, the archive retention gate — is prior
substrate, not an M8-L result; ADR-088 marks `maistro-evolve` experimental
with no stability contract. This change adds no product code, no flag, and no
optimizer.

## Disposition

WATCH at epic level. Leaves for families A–H end individually in GRADUATE /
INCUBATE / REJECT / WATCH; any GRADUATE result routes production adoption to
the M4 governed-improvement owners through `maistro.governance.promotion`
(ADR-100126-a9c4) — it can never authorize its own activation. The epic is
done when every leaf carries a documented disposition.
