---
id: ADR-092726-1cfa
title: "Closed-loop design process on the canonical Run"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-09-27
history:
  - status: Proposed
    date: 2026-09-27
substrate:
  - maistro-engine#ADR-036
  - maistro-engine#ADR-061
  - maistro-engine#ADR-062
  - maistro-engine#ADR-081226-6b46
implements: []
related:
  - maistro-engine#ADR-060
  - maistro-engine#ADR-095
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/ontology/test_no_competing_design_kinds.py::test_product_modules_do_not_register_a_competing_design_kind
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-092726-1cfa: Closed-loop design process on the canonical Run

- **Status:** Proposed
- **Date:** 2026-09-27
- **Deciders:** MAIstro maintainers

## Context

M7 ([#788](https://github.com/Agent-StrongHold/Project-mAIstro/issues/788), epic [#789](https://github.com/Agent-StrongHold/Project-mAIstro/issues/789)) is the design-process vertical of Agent-StrongHold/Project-mAIstro. It is not a new project, not a Canvas product, and not an app.

Nothing on `develop` names the loop as one object graph. Goal is still the interoperability intent [#458](https://github.com/Agent-StrongHold/Project-mAIstro/issues/458) owns. CreativeBrief is still the creative projection [#774](https://github.com/Agent-StrongHold/Project-mAIstro/issues/774) owns. Persona scoring is still `RubricEval` in `packages/maistro-core/src/maistro/personas/rubric.py` ([ADR-060](ADR-060-persona-as-seed-and-eval-protocol.md)). `DesignEngine` still assembles a prompt stack and does not call an LLM ([ADR-061](ADR-061-maistro-design-package.md)). Execution is still a Graph ([ADR-062](ADR-062-graph-execution-protocol.md)) whose tool calls are `Capability → Provider → Binding → Invocation` ([ADR-081226-6b46](ADR-081226-6b46-capability-provider-binding-invocation.md)). The host people already open is Design Studio (`packages/hive-conductor/frontend/src/pages/DesignStudio.tsx`, [#286](https://github.com/Agent-StrongHold/Project-mAIstro/issues/286)).

A disposable prototype demonstrated the failure this decision exists to forbid: a client store named `DesignRun`, `localStorage` as system of record, pack routes as product identity, and a private model call as director ([#990](https://github.com/Agent-StrongHold/Project-mAIstro/issues/990)). This record freezes the object graph before any runtime PR grows that second product. It does not implement the loop.

## Decision

Design is one Graph on the canonical Run:

`Goal → Rubric → Explore → Execute → Evaluate → Refine`

That sequence is not a Canvas product and not a client pipeline. There is no `DesignRun`. There is no second app. Canvas is an execute backend. Book, game, and product are packs.

### Kind table

| Kind | What it is | What it is not |
| --- | --- | --- |
| Goal | Canonical Project-scoped intent. [#458](https://github.com/Agent-StrongHold/Project-mAIstro/issues/458) owns it. | Not owned by Rubric. Not owned by CreativeBrief. |
| Rubric | First-class versioned scored-acceptance object bound to one Goal revision. | Not persona `RubricEval` ([ADR-060](ADR-060-persona-as-seed-and-eval-protocol.md)). Not CreativeBrief success-criteria prose ([#774](https://github.com/Agent-StrongHold/Project-mAIstro/issues/774)). Not the M4 promotion evaluator ([#21](https://github.com/Agent-StrongHold/Project-mAIstro/issues/21)). |
| CreativeBrief | Creative projection of a Goal revision ([#774](https://github.com/Agent-StrongHold/Project-mAIstro/issues/774)). | Not the Goal. Not the scored Rubric. |
| Pack | A Graph/skill/template bundle that specializes this loop for a domain (product, game, book, later others). | Not a product. Canvas is not a pack. Routes `/book`, `/game`, and `/product` are not product identity. Packages `maistro-book` and `maistro-game` are not products. |
| FenceDecision | Park, redirect, or accept: a HITL decision on a waiting NodeRun ([#48](https://github.com/Agent-StrongHold/Project-mAIstro/issues/48)). | Not a new pause universe. |
| EvalRecord | Scores, dimension results, and evidence attached to the producing Run, NodeRun, or Attempt. | Not a sidecar eval identity. Not an `EvalRun`. |
| Run / NodeRun / Attempt | The one execution lifecycle ([ADR-062](ADR-062-graph-execution-protocol.md)). | Not a `DesignRun`. Not a Canvas product. |
| Canvas | An execute backend: a tool on `Capability → Provider → Binding → Invocation` ([ADR-081226-6b46](ADR-081226-6b46-capability-provider-binding-invocation.md)). Deck, Builders, and media providers are the same kind of backend. | Not the loop. Not the product. Not a pack. |
| Design Studio | The parent host UI ([#286](https://github.com/Agent-StrongHold/Project-mAIstro/issues/286)). | Not Atelier. `/cli/canvas` is not the product identity ([#95](https://github.com/Agent-StrongHold/Project-mAIstro/issues/95)). |

Goal and Rubric, when they are registered, are ontology kinds ([ADR-036](ADR-036-ontology-semantic-object-layer.md)) in `maistro.ontology`. `EvalRun` and `DesignRun` are not kinds anywhere, including that registry.

### Redirects do not rewrite history

Park, redirect, and accept are HITL decisions on waiting NodeRuns ([#48](https://github.com/Agent-StrongHold/Project-mAIstro/issues/48)). A redirect names a new revision. It does not silently rewrite the revision it leaves:

- Redirect of the desired outcome is a **Goal** revision.
- Redirect of scoring is a **Rubric** revision.
- Redirect of creative guidance is a **CreativeBrief** revision.

### Persona RubricEval is not Goal Rubric

`RubricEval` (`maistro.personas.rubric`, [ADR-060](ADR-060-persona-as-seed-and-eval-protocol.md)) scores persona and department templates. The Goal-level Rubric is a different kind. One must not be stored, queried, or promoted as the other.

### M4 promotion eval is not in-Run Rubric eval

The M4 promotion loop ([#21](https://github.com/Agent-StrongHold/Project-mAIstro/issues/21)) may later consume M7 eval evidence. It is not the critic inside the design Run, and it is not a second promotion path for design artifacts. M5 RSI ([#552](https://github.com/Agent-StrongHold/Project-mAIstro/issues/552)) is the same kind of later consumer and stays disabled until M5 containment. Neither replaces in-Run Evaluate.

### Execute backends and packs

Explore, Execute, Evaluate, and Refine are phases of the one Graph. Execute calls tools. Canvas, Deck, Builders, and media providers are those tools, reached only through Capability, Provider, Binding, and Invocation. `DesignEngine.generate()` remains prompt-stack assembly ([ADR-061](ADR-061-maistro-design-package.md)). Loop execution is the Graph, not `DesignEngine` calling an LLM, and not a fetch from Design Studio or `packages/maistro-design` to a model host.

A pack changes the Graph, skills, and templates the loop runs. It does not change Run identity. Two packs share Run, NodeRun, and Attempt and differ only by pack contract.

### Forbidden product shapes

These are competing products, not projections of the kinds above ([#990](https://github.com/Agent-StrongHold/Project-mAIstro/issues/990)):

1. Package or app identity: `packages/maistro-atelier`, `packages/atelier`, a Hive route `/atelier`, a page `Atelier.tsx`, or product copy that names Atelier as a shipped surface. The catalog slug `atelier-zero` under `maistro-design` is a design system, not that app.
2. Execution identity: a `DesignRun`, `EvalRun`, or `VariantStore` lifecycle outside `maistro.ontology` and `maistro.runs`. `DesignRun` and `EvalRun` are not lifecycles at all.
3. Persistence: `zustand/persist`, `localStorage`, or IndexedDB as the system of record for Goal, Rubric, waves, evals, or fence. UI may cache. Design Studio's existing fixed-page `localStorage` is editor chrome, not Goal, Rubric, eval, or fence truth.
4. Director or judge egress: a provider SDK or raw chat-completions client inside Design Studio or `maistro_design`. No provider key is a private loop.
5. Pack-as-product: `/book`, `/game`, or `/product` as product identity, or packages `maistro-book` / `maistro-game`.
6. Simulated execution: `setTimeout` or a client stage animation presented as pipeline progress ([#286](https://github.com/Agent-StrongHold/Project-mAIstro/issues/286)).
7. Importing a sandbox prototype tree as the implementation. A prototype outside this repo is reference-only and has zero runtime authority.

### Host and branch

Design Studio is the host. Feature work branches `feat/*` off `develop` only ([ADR-095](ADR-095-four-tier-branch-model.md)).

## Merge gate

This record is Proposed. That status is merge-blocking for implementation. Rubric persistence, ontology registration, eval wiring, packs, the fence, and the Design Studio proof are issues [#791](https://github.com/Agent-StrongHold/Project-mAIstro/issues/791) through [#796](https://github.com/Agent-StrongHold/Project-mAIstro/issues/796). They must not merge as if this decision were taken.

`scripts/check_ac_state_impl.py` owes a spec or acceptance criteria only to a taken ADR (`Accepted`, `Fully Specced`, `Implemented`). A Proposed ADR does not incur that debt. Accepting this record without a spec and without criteria would fail that chain mandate. This PR does not accept it.

## Out of scope

- Rubric persistence, pack registries, fence handlers, eval writers, and Design Studio behavior.
- Changes under `packages/maistro-canvas/**`.
- Making `DesignEngine` call an LLM.
- Replacing [#458](https://github.com/Agent-StrongHold/Project-mAIstro/issues/458), [#773](https://github.com/Agent-StrongHold/Project-mAIstro/issues/773), [#774](https://github.com/Agent-StrongHold/Project-mAIstro/issues/774), or [#48](https://github.com/Agent-StrongHold/Project-mAIstro/issues/48). Those stay the owners named above. This decision depends on [#458](https://github.com/Agent-StrongHold/Project-mAIstro/issues/458) and is related to the others; it does not parent or supersede them.
- The broader [#990](https://github.com/Agent-StrongHold/Project-mAIstro/issues/990) guards (client persist, route identity, private director egress). This PR states them and enforces the kind and package slice a source scan can assert without forbidding Design Studio's existing editor cache or the `atelier-zero` catalog slug.

## Test plan

| Test | Type | Covers |
| --- | --- | --- |
| `packages/maistro-core/tests/ontology/test_no_competing_design_kinds.py::test_product_modules_do_not_register_a_competing_design_kind` | behavioral | Production modules do not declare `Goal` or `Rubric` outside `maistro.ontology`, do not declare `EvalRun` or `DesignRun` anywhere, and do not add an Atelier package or `Atelier.tsx`. |

## Links

- Issue: [#790](https://github.com/Agent-StrongHold/Project-mAIstro/issues/790)
- Initiative: [#788](https://github.com/Agent-StrongHold/Project-mAIstro/issues/788)
- Depends on: [#458](https://github.com/Agent-StrongHold/Project-mAIstro/issues/458)
- Related: [#773](https://github.com/Agent-StrongHold/Project-mAIstro/issues/773), [#774](https://github.com/Agent-StrongHold/Project-mAIstro/issues/774), [#48](https://github.com/Agent-StrongHold/Project-mAIstro/issues/48), [#990](https://github.com/Agent-StrongHold/Project-mAIstro/issues/990)
