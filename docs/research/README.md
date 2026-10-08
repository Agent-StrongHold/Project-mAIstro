# M8 research program — exploratory research and evidence-driven technology bets

Canonical tracker: [#878](https://github.com/Agent-StrongHold/Project-mAIstro/issues/878) ·
Steering initiative: [#879](https://github.com/Agent-StrongHold/Project-mAIstro/issues/879) ·
Parent program: [#453](https://github.com/Agent-StrongHold/Project-mAIstro/issues/453).

M8 is Project-mAIstro's **exploratory research horizon**. It investigates promising
techniques, algorithms, tools, architectures, model capabilities, verification methods,
infrastructure approaches, UX concepts, and other technology bets **before** they become
committed product architecture or implementation roadmap work.

M8 is intentionally broader than verification. Advanced software verification
([#880](https://github.com/Agent-StrongHold/Project-mAIstro/issues/880), evidenced in-repo by
the [`formal/`](../../formal/) Hypothesis suite) is the first research program filed under it,
not the milestone's identity.

This folder is the in-repo home of M8 research notes. Per the [docs map](../README.md) these
are **research notes, not governance**: nothing here redefines canonical Workspace, Project,
Goal, Agent, Persona, Graph/Run/NodeRun/Attempt, Event, memory, capability, Invocation,
security, or product authorities, and nothing here supersedes an
[ADR](../adr/ADR-INDEX.md) or [SPEC](../specs/README.md).

## What M8 answers

Every M8 experiment is filed to answer questions like:

- Is this technique materially useful for MAIstro?
- What concrete failure class or product capability does it address?
- Can we demonstrate value against the real repository rather than a toy example?
- What are the operational, complexity, maintenance, licensing, latency, and cost trade-offs?
- Does it belong in canonical architecture, CI/evidence infrastructure, an optional subsystem,
  or nowhere?
- If it graduates, which earlier implementation milestone/initiative should own the
  production change?

## Dispositions

Every M8 research leaf finishes with **exactly one** terminal disposition:

| Disposition | Meaning |
|---|---|
| **GRADUATE** | Evidence supports adoption; production work is routed to the earliest milestone whose semantics own it. |
| **INCUBATE** | Promising, but evidence or prerequisites are insufficient; the next required evidence is recorded. |
| **REJECT** | Poor fit, redundant, unsafe, too costly, or insufficient value; the reason is recorded. |
| **WATCH** | An external technology is not ready; the trigger for reassessment is recorded. |

A GRADUATE result **does not authorize production adoption inside M8**. It creates or routes
production implementation to the earliest owning milestone/initiative, and adoption passes the
normal architecture and evidence gates.

## Research contract

Every child research epic/leaf defines:

1. the concrete hypothesis being tested;
2. the real MAIstro seam/workload used for the experiment;
3. a comparison baseline;
4. success/failure metrics;
5. an implementation/operational cost estimate — including CI/runtime overhead, maintenance
   burden, developer ergonomics, false positives, and conceptual complexity;
6. trust-boundary implications;
7. reproducible artifacts or a benchmark procedure;
8. one terminal disposition (above).

## Guardrails

1. Prototypes may not become new canonical authorities by accident; a research prototype is
   evidence, not production truth.
2. Research code stays clearly separated from shipped product code unless an existing
   test/research seam is deliberately reused (the harnesses under
   `packages/maistro-rsi/tests/test_m8*_research.py` are test-suite-only artifacts).
3. Negative findings are first-class results; record them.
4. M8 does not hide defects that invalidate M0–M7 acceptance. If research exposes such a
   defect, file or reopen it under the earliest owning milestone.
5. No benchmark-only adoption: demonstrate value on representative MAIstro code/workloads,
   preferring real seams over toy demos or benchmark theater.
6. Prefer techniques that compose with existing quality infrastructure rather than replacing
   working controls without evidence; never weaken existing gates to make experiments easier.
7. Research dependencies are not hierarchy.
8. Production adoption requires an explicit graduation decision and normal
   architecture/evidence gates.

## Research note index

| Note | Family | Epic / leaf | Disposition at this head |
|---|---|---|---|
| [894 — critical-zone mutation strategy](894-critical-zone-mutation-strategy.md) | M8-A14 | leaf [#894](https://github.com/Agent-StrongHold/Project-mAIstro/issues/894), epic #880 | INCUBATE |
| [896 — coverage-guided fuzzing of parser surfaces](896-coverage-guided-fuzzing-parser-surfaces.md) | M8-A15 | leaf [#896](https://github.com/Agent-StrongHold/Project-mAIstro/issues/896), epic #880 | INCUBATE |
| [904 — uncertainty, calibration, abstention](904-uncertainty-calibration-abstention.md) | M8-E | [#904](https://github.com/Agent-StrongHold/Project-mAIstro/issues/904) (leaves #930–#933) | WATCH (per leaf) |
| [931 — historical Run-outcome calibration](931-historical-outcome-calibration.md) | M8-E2 | leaf [#931](https://github.com/Agent-StrongHold/Project-mAIstro/issues/931), epic #904 | WATCH |
| [905 — inference systems, open-model fleets, caching, batching, specialization](905-inference-systems-open-model-fleets-caching-batching-specialization.md) | M8-F | [#905](https://github.com/Agent-StrongHold/Project-mAIstro/issues/905) | WATCH (epic) |
| [906 — information-flow, provenance, agent security](906-information-flow-provenance-agent-security.md) | M8-G | [#906](https://github.com/Agent-StrongHold/Project-mAIstro/issues/906) | WATCH (per candidate) |
| [907 — autonomous SWE orchestration, multi-agent repo execution](907-autonomous-swe-orchestration-multi-agent-repo-execution.md) | M8-H | [#907](https://github.com/Agent-StrongHold/Project-mAIstro/issues/907) | WATCH (per direction) |
| [908 — persistent Agent self-models, capability awareness](908-persistent-agent-self-models-and-learned-capability-awareness.md) | M8-I | [#908](https://github.com/Agent-StrongHold/Project-mAIstro/issues/908) | WATCH (epic) |
| [909 — human-agent interaction, generative UI, mixed initiative](909-human-agent-interaction-generative-ui-mixed-initiative.md) | M8-J | [#909](https://github.com/Agent-StrongHold/Project-mAIstro/issues/909) | WATCH (epic) |
| [910 — autonomous knowledge acquisition, evidence graphs](910-autonomous-knowledge-acquisition.md) | M8-K | [#910](https://github.com/Agent-StrongHold/Project-mAIstro/issues/910) | WATCH |
| [911 — optimization, search, synthesis, learned improvement](911-optimization-search-synthesis-learned-improvement.md) | M8-L | [#911](https://github.com/Agent-StrongHold/Project-mAIstro/issues/911) | WATCH (epic) |
| [912 — multi-agent organization, delegation topology](912-multi-agent-organization-delegation-topology.md) | M8-M | [#912](https://github.com/Agent-StrongHold/Project-mAIstro/issues/912) | WATCH (per direction) |
| [914 — task-conditioned model routing](914-task-conditioned-model-routing.md) | M8-B1 | leaf [#914](https://github.com/Agent-StrongHold/Project-mAIstro/issues/914), epic #900 | INCUBATE |
| [915 — cheap-model-first cascades](915-cheap-model-first-cascades.md) | M8-B2 | leaf [#915](https://github.com/Agent-StrongHold/Project-mAIstro/issues/915), epic #900 | WATCH |
| [916 — contextual-bandit model routing](916-contextual-bandit-model-routing.md) | M8-B3 | leaf [#916](https://github.com/Agent-StrongHold/Project-mAIstro/issues/916), epic #900 | INCUBATE |
| [917 — speculative parallel model calls](917-speculative-parallel-model-calls.md) | M8-B4 | leaf [#917](https://github.com/Agent-StrongHold/Project-mAIstro/issues/917), epic #900 | WATCH |
| [919 — prompt-model co-routing](919-prompt-model-co-routing.md) | M8-B5 | leaf [#919](https://github.com/Agent-StrongHold/Project-mAIstro/issues/919), epic #900 | WATCH |
| [920 — hybrid vector + graph retrieval](920-hybrid-vector-graph-retrieval.md) | M8-C1 | leaf [#920](https://github.com/Agent-StrongHold/Project-mAIstro/issues/920), epic #901 | WATCH |
| [921 — learned reranking and query rewriting](921-reranking-query-rewriting.md) | M8-C2 | leaf [#921](https://github.com/Agent-StrongHold/Project-mAIstro/issues/921), epic #901 | WATCH |
| [922 — adaptive context budgeting, hierarchical compression, selective omission](922-adaptive-context-budgeting.md) | M8-C3 | leaf [#922](https://github.com/Agent-StrongHold/Project-mAIstro/issues/922), epic #901 | WATCH |
| [935 — cross-Agent batching, prefix/KV reuse, semantic caching](935-cross-agent-batching-kv-reuse.md) | M8-F2 | leaf [#935](https://github.com/Agent-StrongHold/Project-mAIstro/issues/935), epic #905 | WATCH |

No leaf currently holds a GRADUATE or REJECT disposition; four are INCUBATE (critical-zone
mutation #894, fuzzing leaf #896, and model-routing leaves #914, #916) and the rest are
WATCH. Dispositions are owned by the individual notes — update the note first, then this
table.

The initial research family, M8-A advanced software verification and assurance
([#880](https://github.com/Agent-StrongHold/Project-mAIstro/issues/880), leaves #881–#897), is
tracked on GitHub with its in-repo evidence infrastructure in [`formal/`](../../formal/)
([INVARIANTS](../../formal/INVARIANTS.md), [README](../../formal/README.md)); its first
notes in this folder are the critical-zone mutation prototype (#894) and the M8-A15 fuzzing
prototype (#896) above.

## Milestone object note

The GitHub milestone object for M8 did not exist when tracker #878 was created, and this
repository's automation cannot create milestone objects. Tracker #878 and its hierarchy
(#879, epics, leaves) establish M8 semantically; once the GitHub milestone object exists, the
hierarchy should be assigned to it. That assignment is a GitHub-side action, out of scope for
in-repo changes.
