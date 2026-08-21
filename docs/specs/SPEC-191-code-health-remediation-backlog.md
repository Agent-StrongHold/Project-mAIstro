---
id: SPEC-191
title: "Code-health remediation backlog — cyclomatic complexity, god objects, dead code, security, and duplication debt across the monorepo"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-05-31
substrate:
  - maistro-engine#ADR-019
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-31
---

# SPEC-191: Code-Health Remediation Backlog

## Context

A full-tree `/code-health` scan (the deep "better-than-a-linter" analyzers — radon, xenon,
vulture, lizard, pylint R0801, bandit — that are intentionally **not** part of the per-commit CI
loop) was run across **607 source files / ~79k LOC** (tests excluded) on 2026-05-31.

The codebase is broadly healthy: **96% of functions are grade A** (CC ≤ 5), maintainability index
is all-A on changed code, and there are no duplication blocks within most subsystems. The debt is
**concentrated** — a small number of mega-functions and god files carry most of the maintenance
risk. This doc is the tracked inventory so the debt is visible and can be burned down deliberately
rather than rediscovered ad hoc.

Reproduce at any time: **`/code-health <path>`** (defaults to the branch diff; pass a path/package
for a wider scan). Tools live in the `quality` extra: `uv sync --extra quality`.

### Complexity distribution (radon CC, whole tree)

| Grade | CC range | Count |
|-------|----------|------:|
| A | 1–5    | 3412 |
| B | 6–10   | 413 |
| C | 11–20  | 124 |
| D | 21–30  | 16 |
| E | 31–40  | 10 |
| F | 41+    | 4 |

**154 functions are grade C or worse** (CC > 10) — the remediation scope below.

## Goals

- Make the complexity / god-object / security / duplication debt **visible and tracked**.
- Prioritize so the highest-risk items (core hot paths, F-grade functions) are burned down first.
- Establish thresholds and a re-scan cadence so the debt does not silently regrow.

## Non-goals

- Rewriting healthy grade-A/B code for its own sake.
- Refactoring vendored/generated code (e.g. Alembic migrations) or test fixtures.
- Adding these analyzers as **blocking** CI gates (a separate decision — see Open questions).

## Decision

Burn the backlog down in priority tiers. Each item links to a `file:line` and its metric so it can
become a focused PR. Re-run `/code-health` after each tier to confirm the grade moved.

### P0 — Quick, safe wins (do first; low risk, high signal)

- [ ] `maistro-evolve/.../diversity.py:38` — weak MD5 flagged by bandit (B324). Fix: `hashlib.md5(..., usedforsecurity=False)` (it is non-security hashing).
- [ ] `hive-conductor/backend/routes/dags.py:292` — unreachable code after `return` (vulture 100%). Remove.
- [ ] `hive-conductor/run_hill_climb.py:89` — unreachable code after `return` (vulture 100%). Remove.
- [ ] `maistro-core/.../security/oauth.py:68,90` — `redirect_uri` / `refresh_token` assigned but unused. **Likely a real correctness gap** (OAuth params silently dropped) — verify, then wire or remove.
- [ ] `hive-conductor/backend/adapters/maistro_core.py:59 complete()` — `stream` and `metadata` params accepted but silently ignored (`payload` hardcodes `"stream": False`, never forwards `metadata`). Honor them or annotate intentional.
- [ ] `hive-conductor/backend/main.py:28` — unused `daily_report` (v1) import; only `daily_report_v2` is registered. Remove (ruff F401 misses it inside the multi-line `from routes import (...)` tuple).

### P1 — F/E-grade functions (CC > 30) — highest-risk refactors

The two **core hot paths** dominated overall risk. Both are **already refactored on `develop`** —
this backlog was first measured against the `feat/host-health-real-signals` stack, which forked before
those commits landed and still carries the stale monolithic copies. The feat stack has made **no**
changes to either file since the merge-base, so when feat → develop merges these files resolve cleanly
to `develop`'s refactored version — do **not** re-refactor them on the feat stack (it would only create
a conflict where none exists).

- [x] **`maistro-core/.../agents/base.py Agent.handle()` — was CC 70 / 319 lines.** Decomposed on
  `develop` (`3f67b30`, `2f2f9af`) into `_run_warden` / `_build_context` / `_run_strategy` /
  `_extract_rca` / `_extract_learnings` / `_record_outcome` / `_finalize_trace` / `_inject_session_history`;
  `handle()` body ~318 → ~118 lines. Coverage via `tests/agents/test_delegation.py`.
- [x] **`hive-conductor/.../services/chat_completion.py _execute_tool()` — was CC 72 / 278 lines.**
  Decomposed on `develop` into a `_TOOL_HANDLERS` dispatch dict + per-tool handlers
  (`_tool_poll_jira`, `_tool_search_jira`, …); `_execute_tool()` reduced to a handler lookup + call.

Then the rest of F/E (still outstanding on `develop`):

| CC | Grade | Location |
|---:|:--:|---|
| 62 | F | `hive-conductor/.../services/optimizer.py:506 _apply_topology_mutation()` (129 lines) |
| 46 | F | `maistro-canvas/frontend/.../mcp/feature_extractor.py:48 _classify_hair_color()` |
| 39 | E | `maistro-canvas/frontend/.../mcp/bg_removal.py:42 remove_background()` |
| 38 | E | `maistro-canvas/.../canvas/tool.py:306 execute_canvas()` (291 lines) |
| 38 | E | `hive-conductor/.../services/graph_runner.py:21 execute_dag()` (213 lines) |
| 37 | E | `maistro-core/.../agents/base.py:149 Agent` (class) |
| 37 | E | `hive-conductor/dags/author_selector.py:30 select_authors()` |
| 33 | E | `maistro-core/.../skills/fixer.py:13 fix_content()` (152 lines) |
| 33 | E | `maistro-core/.../agents/artificer/strategy.py:50 ArtificerStrategy.reason()` (223 lines) |
| 31 | E | `maistro-evolve/.../benchmarks/bfcl.py:41 _score_tool_call()` |
| 31 | E | `maistro-core/.../config/loader.py:50 load_yaml_config()` |
| 31 | E | `maistro-core/.../agents/context_builder.py:31 ContextBuilder` (class) |

### P2 — D-grade functions (CC 21–30)

| CC | Location |
|---:|---|
| 30 | `maistro-core/.../agents/context_builder.py:34 ContextBuilder.build()` (123 lines) |
| 30 | `maistro-canvas/frontend/.../mcp/feature_extractor.py:114 _classify_eye_color()` |
| 29 | `maistro-core/.../agents/strategies/react.py:46 ReactStrategy.reason()` (180 lines) |
| 28 | `maistro-evolve/.../benchmarks/terminalbench.py:14 _score_command()` |
| 28 | `maistro-evolve/.../benchmarks/ifeval.py:22 _evaluate_rule()` |
| 28 | `maistro-core/.../resilience/classifier.py:154 classify_error()` (158 lines) |
| 26 | `maistro-evolve/.../benchmarks/swebench.py:14 _score_code_fix()` |
| 25 | `maistro-evolve/.../benchmarks/osworld.py:14 _parse_actions()` |
| 25 | `hive-conductor/.../services/chat_completion.py:529 run_chat_completion()` |
| 24 | `hive-conductor/.../routes/daily_report_v2.py:29 daily_report()` |
| 22 | `maistro-evolve/.../benchmarks/scoring.py:73 function_call_match()` |
| 21 | `maistro-core/.../tools/atlassian/client.py:267 AtlassianMCPClient._parse_jira_issue()` |
| 21 | `maistro-core/.../security/guardrail.py:129 ToolGuardrail._evaluate()` |
| 21 | `maistro-core/.../agents/pm_runner.py:453 run_pm_task()` (152 lines) |
| 21 | `maistro-canvas/frontend/.../mcp/canvas_templates.py:737 generate_scene_plan()` |
| 21 | `hive-conductor/.../services/validation_gate.py:67 _apply_mutation_to_dag()` |

> Note: the `maistro-evolve/benchmarks/*` scorers (bfcl, terminalbench, ifeval, swebench, osworld,
> scoring, tau_bench) cluster at C–E. They are inherently branchy rule-evaluators; treat as one
> coordinated refactor (shared scoring helpers) rather than piecemeal.

### P3 — C-grade functions (CC 11–20), 124 total, grouped by package

**maistro-core (≈60):** notable — `graph/run.py:264 GraphRun._execute` (20), `router/filter.py:14 filter_candidates` (20), `memory/scopes.py:27 matches_scope` (20), `classifier/multi_intent.py:13 detect_multi_intent` (20), `security/sentinel/validator.py:15 validate_and_repair` (18), `security/gate.py:48 Gate.process_input` (17), `classifier/engine.py:53 ClassifierEngine.classify` (17), `credentials/pool.py:73 CredentialPool.select` (17), `conduit.py:43 Conduit.route_request` (13), `security/warden/detector.py:59 Warden.scan` (12), `skills/marketplace.py:44 _block_ssrf` (13). Plus the `graph/nodes/*`, `memory/learnings/*`, and `agents/spawner/*` clusters.

**hive-conductor (≈30):** `services/chat_completion.py:615 run_chat_completion_streaming` (13), `services/engine.py:221 EngineService.submit_task` (14, +8 params), `services/optimizer.py:329 run_optimizer` (11), `services/hill_climber.py` (×2), `services/node_metrics_store.py` (×2), `routes/daily_report.py:363 search_jira_projects` (17), `middleware/auth.py:75 AuthMiddleware.dispatch` (11), `middleware/request_log.py` (×2), `stores.py:167 _seed_if_empty` (17).

**maistro-canvas (≈20):** `canvas/executor.py:250 _execute_action` (16), `frontend/.../mcp/feature_extractor.py:90 _classify_skin_tone` (19), `frontend/.../mcp/character.py:420 generate_character_sheet` (18), `canvas/asset_compositor.py` (×2), `frontend/.../mcp/story.py` (×3), `frontend/.../lulu/preflight.py:51` (15).

**maistro-evolve (≈12):** the benchmark scorers + `mutate.py:43 mutate_topology` (20), `crossover.py:24 crossover` (15), `cycle.py` (×2).

**maistro-registry / maistro-server / maistro-turing / maistro-bootstrap (≈4):** `registry/linker.py:141 GitHubResolver._fetch_ids` (11), `registry/cli.py:140 cmd_generate` (11), `server/api/webhooks.py:51 github_webhook` (11), `turing/runtime.py:46 load_turing_config` (13), `bootstrap/plan.py:90 build_install_plan` (14).

_(The complete 124-row list is reproducible via `radon cc -s -n C <src>`; see the scan command above.)_

### God files (> 500 lines) — 14 total

| Lines | File |
|------:|------|
| 1053 | `maistro-canvas/.../canvas/asset_store.py` |
| 903 | `maistro-canvas/.../canvas/tool.py` |
| 877 | `maistro-canvas/frontend/server/mcp/canvas_templates.py` |
| 856 | `maistro-evolve/.../benchmarks/datasets.py` |
| 835 | `maistro-canvas/.../canvas/asset_routes.py` |
| 694 | `maistro-core/.../skills/connectors.py` |
| 691 | `hive-conductor/.../services/chat_completion.py` |
| 661 | `maistro-canvas/.../canvas/store.py` |
| 652 | `hive-conductor/.../services/optimizer.py` |
| 621 | `maistro-canvas/.../canvas/routes.py` |
| 604 | `maistro-core/.../agents/pm_runner.py` |
| 586 | `maistro-canvas/frontend/server/mcp/character.py` |
| 576 | `maistro-canvas/.../canvas/asset_compositor.py` |
| 511 | `maistro-core/.../agents/base.py` |

### Notable B-grade (long but low-branching) — the "some Bs"

Long functions that are NOT in the complexity list (low CC, high line count) — split for
readability, not branch reduction. Mostly route registration / seeding:

| Lines | Location |
|------:|----------|
| 529 | `maistro-canvas/.../canvas/routes.py:93 make_canvas_router()` — route registration block |
| 349 | `maistro-canvas/.../canvas/asset_routes.py:436 make_router()` |
| 220 | `hive-conductor/.../stores.py:167 _seed_if_empty()` |
| 125 | `maistro-canvas/.../canvas/store.py:256 add_layer()` |

_(Excluded: `frontend/alembic/versions/001_initial_schema.py:18 upgrade()` — generated migration.)_

### Security (bandit `-ll`): 1 High, 8 Medium, 121 Low

- **High (1):** `hive-conductor/eval/benchmarks/coding.py:62` — `exec()` of model-generated code (B102). Expected for a benchmark harness; **sandbox or explicitly annotate** the trust boundary.
- **Medium (8):** `run_hill_climb.py` hardcoded `/tmp` paths (B108 ×5) + bind-all-interfaces (B104); `coding.py:65` `eval` (B307, same harness); `evolve/.../datasets.py:665` hardcoded tmp; `evolve/diversity.py:38` MD5 (see P0).
- **Low (121):** noise (asserts etc.) — not tracked.

### Dead code (vulture): mostly false positives

23 hits at ≥80% confidence, but the majority are **Protocol method params** (`protocols/memory.py`,
`protocols/tools.py`, `protocols/tracing.py`, `maistro_turing/protocols.py`) and
`__exit__`/`__aexit__` dunder args — **not** dead code; do not "fix". The genuinely actionable ones
are captured in **P0** above (2 unreachable blocks + a few unused locals).

### Duplication (pylint R0801): structural, tied to the ADR-019 split

Real duplicated blocks tracking the types re-org / backwards-compat aliases:

- `maistro.config.settings` ⇄ `maistro.types.config` (3 blocks)
- `maistro.memory.types` ⇄ `maistro.types.memory` (3 blocks)
- `agents.artificer.strategy` ⇄ `agents.strategies.react` (the two `reason()` impls)
- `container` ⇄ `testing.harness` (DI wiring copied into the test harness)

**Decision needed:** are the `types.*` duplications intentional compat shims (per ADR-019), or should
they collapse to a single source of truth + re-export? Tracked in Open questions.

## Acceptance criteria

- [ ] P0 items (6) closed — each a one-line/small PR.
- [x] The 2 core F-grade hot paths (`Agent.handle`, `_execute_tool`) refactored to ≤ grade C — done on `develop` (`3f67b30`, `2f2f9af`); see P1 note. Outstanding only on the feat stack as stale copies, which resolve on merge.
- [ ] A decision recorded (here or a follow-up ADR) on: (a) the `types.*` duplication, and (b) whether `quality` analyzers become a non-blocking CI job.
- [ ] Re-running `/code-health` shows the F-count at 0 and the D/E-count reduced.

## Testing

Each refactor is behavior-preserving: write/confirm characterization tests **before** touching the
function (the global 12-step workflow), then refactor green. The `agents/base.py` and
`chat_completion.py` paths have existing suites under `packages/*/tests/` — extend coverage on the
specific branches before decomposing.

## Open questions

1. Should the `quality` analyzers run as a **non-blocking** CI job (e.g. `quality.yml`, nightly) with
   a ratcheted threshold (xenon `--max-absolute D`), so debt cannot regrow past today's worst?
2. Is the `maistro.types.*` ⇄ original-location duplication an intentional ADR-019 compat shim, or
   collapsible to single-source + re-export?
3. Add an `[importlinter]` contract to make the CLAUDE.md boundary rules ("core must not import
   Stronghold", "logic depends on protocols not impls") executable? `/code-health` already runs
   import-linter opportunistically if present.

## References

- ADR-019 — canonical source split (maistro-core = shared runtime).
- `/code-health` skill — `.claude/skills/code-health/SKILL.md`.
- Reproduce: `radon cc -s -n C`, `bandit -ll -r`, `vulture --min-confidence 80`, `pylint --enable=duplicate-code`.
