# M8-H research note — autonomous software-engineering orchestration and multi-agent repository execution

Epic: #907. Initiative: #879. Milestone: M8. Status at this head: **no comparative
experiment has been run**; this note maps the epic's hypothesis space onto the real
canonical seams, records what is and is not evidenced today, and sets a terminal
disposition per candidate direction. It adds no product code, no flag, no orchestrator,
and no second runtime.

## Research question

Which orchestration strategy maximizes completed, mergeable repository work per unit of
model compute while minimizing lane collision, duplicate work, stale assumptions, and
reviewer burden?

## Canonical seams (verified at this head)

The seams live in one repository, but not all of them already execute under the
canonical model, `Workspace/Project → Graph → Run → NodeRun → Attempt`; work has
exactly one execution identity only where it enters that model, checked fail-closed
against the node registry at admission
(`packages/maistro-core/src/maistro/runs/admission.py`). `CONVERGENCE-MATRIX.md`
records planning/wave orchestration (`orchestrator.waves`) and RSI autorun as
**MIGRATE** rows: wave state and RSI cycles are coordinator/result records with their
own run bookkeeping (the Hive RSI service keeps an in-memory `RunState`), not yet
Graph nodes with per-branch NodeRuns. Experiments built on those seams do not inherit
canonical admission, recovery, or identity guarantees until that migration lands.

- **Worker loops over a work pool (partially built).** ADR-092326-7ed7 (Accepted)
  establishes one stable Workspace Agent identity per workspace — identity only: no
  Goal ownership or reconciliation loop ships. `maistro.goals` does not exist at this
  head (`packages/maistro-core/src/maistro/projects/rubric_store.py` depends on a
  `GoalRevisionCatalog` Protocol precisely because "that module does not exist yet";
  canonical Goal persistence is #458, and the Hive brief flow reports "no Goal store
  yet"), so an issue-pool worker loop over Goals has no canonical substrate today.
  Campaigns (ADR-092626-c1e7, Proposed;
  SPEC-092626-1831, open questions Q1–Q5) would let an operator *narrow* which
  BacklogItems an authorized actor may choose — selection policy, never a second
  scheduler or Goal owner. The RSI HTR coordinator (`maistro_rsi/coordinator.py`) is a
  long-lived strategist driving short-lived executors through a hypothesis tree, with
  distilled lineage insights and branch pruning. Peer delegation ships behind one
  protocol (`maistro/a2a/`, ADR-058, Proposed: broker, budgets, `DelegationRefused`,
  guest peers; federation is Phase 3).
- **Decomposition and planning.** SuperPlanner (`orchestrator/planner.py`, ADR-071,
  Proposed) turns a plan into DAG waves with topological ordering and an output-security
  gate; `orchestrator/waves/ensemble.py` runs parallel isolated-context waves with a
  deterministic Run-level fold (`runs/aggregation.py`, `RUN_TERMINAL_PRECEDENCE`);
  ADR-052 (Deprecated) is the lineage. Cross-harness spawning is ADR-101 (Proposed).
- **Collision surfaces.** `quality/branch-independence.json` (enforced by
  `scripts/check-branch-independence.py`) freezes classified `quality/*.json` state —
  the registry's `quality_roots` today lists only `quality` — and it may only shrink:
  the repo's own recorded answer to lane collision on shared ledger state. It does not
  inventory bookkeeping aggregates outside those roots (e.g.
  `docs/testing/inventory/baseline.json`), so repository-wide collision surfaces are
  undercounted. The RSI merge kernel (`maistro_rsi/merge.py`, SPEC-070126-9d37) is
  conflict-based patch composition, not region ownership: `greedy_merge` applies
  candidates best-first onto an accumulating worktree through a caller-supplied
  `apply` (in the loop, a whole-diff `git apply`) and keeps one only if that apply is
  clean, so a clean apply can still touch the same conceptual region as a kept
  candidate, and context drift can reject independent work; `select_with_fallback`
  re-runs the gates on a combined result or falls back to the top candidate.
  `collaboration/session_collab.py` provides graded co-ownership inside one session.
- **Recovery.** ADR-056 (Accepted) is durable resume with wave verification;
  `Container.recover_abandoned_attempts` sweeps abandoned attempts on tick
  (`runs/chat_execution.py`); the stale-completion fences in `runs/reconciliation.py`
  and `runs/execution.py` stop a superseded worker from committing into a newer
  Attempt; #1942 keeps recovery from invalidating a live walker's checkpoint. RSI adds
  intervention policy with `ObjectiveParked` and quarantine
  (`maistro_rsi/intervention.py`, `maistro_rsi/quarantine.py`).
- **Dependency-aware selection (partially instrumented).** `BACKLOG.md` declares
  `blocked-by:` dependencies in its status legend, but nothing enforces them:
  `scripts/check-backlog-consistency.py` validates status vocabulary and item/decision
  references only — it parses no dependency edges and detects no cycles — so the
  backlog is not a checked DAG, and a selection experiment could admit blocked or
  cyclic work as eligible. SuperPlanner topologically sorts plan items; campaign
  eligibility narrowing is still Proposed.
- **Review.** Two Elo implementations exist and must not be conflated:
  `maistro.agents.tournament.Tournament` is a dormant in-memory rater of
  caller-supplied scores (no non-test caller; `_PROMOTION_THRESHOLD = 50`), while the
  shipped adversarial implementation is `maistro_evolve.tournament.EloTournament` (with
  `GenomeBattle`), which RSI imports for genome tournaments (autorun, runner,
  local_loop) per ADR-070126-6386 (Proposed). The RSI regression judge
  (`maistro_rsi/regression_judge.py`) is a fail-closed second-opinion LLM review
  (#307): enabled, an unavailable verdict fails the gate instead of masquerading as a
  pass. `security/dag_shape/` judges synthesized width proportionally (advisory);
  `security/delegability/evaluator.py` translates authorization into a planning-shaped
  answer.
- **Merge readiness.** The blocking gate battery (`docs/quality-gates.md`: identity
  ratchets, diff coverage, suite inventory, execution lifecycles, model egress) is the
  deterministic half. The judgmental half is base-owned: `scripts/check-autonomous-merge.py`
  classifies candidate admissibility from the protected base, never imports candidate
  code, refuses candidate changes to `scripts/check-*.py`, workflows, or CODEOWNERS, and
  requires humans for high-blast-radius surfaces; `scripts/check-enqueue-merge-queue.py`
  enqueues only policy-green candidates whose exact head completed `gates-ran`
  (ADR-091226-1341). RLPHD predictive approval (`maistro_rsi/promotion_review.py`,
  SPEC-248 / ADR-068 §E) learns which feature shapes predict human approval and reverts
  below-threshold promotions while flagging them for a human.
- **Rebase/revalidation.** Nothing ships an automatic rebase strategy. The merge queue
  re-verifies policy freshness against the fetched base before enqueueing; the
  `ac-state-notes` folded-notes representation lets concurrent branches write
  independent notes instead of rewriting one aggregate; the contributor rule that a
  floor raise takes two merges (`ratchet-authorizations.json` read from the merge base)
  is recorded human policy, not automation. Shadow-git rollback (ADR-049) is Deprecated.
- **Assignment from repository evidence (absent; raw material only).** Agent
  selection today is heuristic, not evidence-based: the pulse/roster split assigns a
  capability to the first roster-order agent that declares it, with no hardcoded names
  (#221, `agents/hyperagent.py`), and `VariantSelector` Thompson-samples prompt
  variants per capability (ADR-007, Accepted) behind the single spawn funnel (ADR-009,
  Accepted). The closest evidence reader is the RSI scout (`maistro_rsi/scout.py`),
  which reads a module's source, tests, and uncovered lines and returns a ranked, typed
  improvement shortlist — evidence about where work could go, not which agent does it;
  nothing joins scout output to agent selection.
- **Parallelism levels.** Lane-aware admission (`maistro/tasks/lanes.py`, ADR-010,
  Accepted) reserves capacity for LIVE vs BACKGROUND with tier-ordered shared pools —
  measured for latency (chat p50 2.03 s reserved vs 24.14 s global-cap under a
  300-node DAG contending with 20 interactive requests), not for work quality.
  `maistro_evolve/lane_comparison.py` demonstrates the measured two-lane harness shape
  this epic needs — budgeted lanes, external evaluation, no-improvement reported — for
  curriculum lanes.

## Contract for any experiment under this epic

Project-mAIstro itself (or a controlled replica) is the workload; measured dimensions:
accepted/merged changes, defect escape, collisions, duplicated work, wall-clock and
compute cost, human interventions, rollback/rework. Canonical repository authority and
branch protection are not bypassable from inside the experiment: protection rulesets
govern `develop`→`main` (ADR-095, Accepted), required checks are pinned to real jobs by
`scripts/check-branch-protection.py` (#162) against `docs/ci/REQUIRED-CHECKS.md`, and
the autonomous path can only ever enqueue what the base-owned policy classifies green —
a research orchestrator is just another actor whose output must land by the same PR
contract. Baseline for every comparison: the same issue set through a single serial
worker on the canonical execution model, same model tier. A GRADUATE result does not
authorize adoption inside M8; it routes to the orchestrator/agent/CI owners as normal
implementation work under the earliest owning milestone.

## Record

No experiment has been run. What exists today is *machinery with safety, liveness, and
recovery properties under test* — admission fail-closure, budgets, stale-worker fences,
branch-independence freezes, fail-closed review — not evidence that any orchestration
strategy completes more mergeable work per unit of compute than another. Two honest
qualitative signals point the same way: this repository's own contributor guidance
documents multi-writer friction (ratchet ledgers that merge cleanly while losing rows,
floor raises needing two merges, suite-inventory deltas per change), which is evidence
that lane collision is *real and costly* here, and the RSI package demonstrates a full
autonomous patch-propose-judge loop in isolation — but neither is a measured comparison
of orchestration strategies, which is what this epic's research question requires.
Initiative guardrail 3 ("negative findings are first-class") resolves the gap the same
way at this head: nothing is evidenced, nothing graduates. Per-direction hypothesis/
baseline/metrics framing is inherited from the Contract section; a future leaf only
needs to name its seam, its issue sample, and its numbers.

## Dispositions

| Direction (candidate from #907) | Seam | Disposition |
|---|---|---|
| Symphony-style issue/worker orchestration | Workspace Agent identity (no Goal store yet) + campaigns (Proposed); RSI HTR coordinator; A2A broker | **WATCH** — coordinator/executor and delegation machinery shipped; no Goal store, so no issue-pool worker loop exists to measure against a serial baseline |
| Dynamic issue decomposition into non-overlapping lanes | campaign narrowing (Proposed, Q1–Q5 open); declared (unchecked) backlog dependencies; SuperPlanner waves | **WATCH** — topological/planning machinery exists; nothing partitions an issue set into disjoint executable lanes |
| Active-owner/collision detection | branch-independence registry (`quality/*.json` only); RSI conflict-based merge; session co-ownership | **WATCH** — collision control exists for *ledger state* and *patch applicability*; no cross-branch owner/lease primitive for issues |
| Abandoned-lane recovery | ADR-056 resume, `recover_abandoned_attempts`, stale fences, quarantine | **WATCH** — the most developed direction: Run/Attempt-level recovery shipped and tested; "lane" is a level above and unmeasured |
| Dependency-aware issue selection | declared `blocked-by:` legend (unenforced); planner topological sort | **WATCH** — dependency truth is declared but unchecked, and no selection strategy over it is measured |
| Reviewer specialization and adversarial review | `EloTournament` (evolve/RSI; core tournament dormant); fail-closed regression judge; dag_shape; delegability | **WATCH** — review machinery shipped; no evidence specialization beats a single competent reviewer here |
| Merge-readiness prediction | `check-autonomous-merge.py` policy; RLPHD `promotion_review.py`; gate battery | **WATCH** — classification and learning-to-predict both ship (RSI-scope); no repo-level precision/recall measurement exists |
| Automatic rebase/revalidation strategy | merge-queue freshness re-check; folded notes; two-merge floor rule (human) | **WATCH** — revalidation primitives exist; automatic rebase is absent, and nothing measures rebase churn |
| Agent assignment from repository evidence | roster-first matching (#221, heuristic); VariantSelector (ADR-007); RSI scout (evidence source) | **WATCH** — assignment is a roster-order heuristic or variant sampling; the scout reads evidence but proposes work, not agents — evidence-based assignment is unbuilt, not merely unmeasured |
| Throughput vs quality under parallelism levels | LaneGate reservation (latency-measured); ensemble waves; `lane_comparison.py` harness shape | **WATCH** — latency-vs-parallelism measured; quality-vs-parallelism on repo work is not |

WATCH, not REJECT: the recorded machinery is real and tested, and the repository's own
multi-writer workflow already exercises it, so the directions can be studied without a
second runtime (where a seam is only partially built, the WATCH names exactly what is
missing); WATCH, not INCUBATE: nothing outperformed anything yet, and no prototype is
kept. The
likely first leaves are merge-readiness prediction and collision detection, because
their instrumentation (base-owned admissibility classifications, the
branch-independence registry, the gate battery) already ships and only the measurement
over an issue sample is missing.

## Exit

Every candidate direction is dispositioned. Any future GRADUATE routes to the
orchestrator/agent/CI capability owners as canonical implementation under the earliest
owning milestone — never as a parallel execution authority beside `Goal → Graph → Run →
NodeRun → Attempt`, and never by weakening branch protection or the base-owned merge
policy.
