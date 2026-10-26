# Workspace cutover — finish plan (v2)

> **For agentic workers:** implement **one PR at a time** from the ordered task
> lists below. Prefer `subagent-driven-development` / `executing-plans`. Do not
> start a later track until its **Entry gate** is green. Close GitHub issues only
> via the **Issue close protocol**.

**Goal:** Finish every remaining open M3 Workspace cutover issue that this
lane owns, without inventing second lifecycle stores, and without closing
epics from partial slices.

**Architecture:** Workspaces surfaces are **projections** over canonical
Goal/Run/HITL/Approval/capability/session services. When a replacement AC is
proven, the same PR deletes the asset and marks the ledger row
`deleted: true` — **retain the row**. Do not drop a tracked path (or flip it
to KEEP) unless an `untrack::<path>` grant has already landed at the trusted
base (`scripts/check-workspace-retirement.py`). Replacement AC evidence does
not authorize untracking. Contract:
[`WORKSPACE-CUTOVER-PLAN.md`](WORKSPACE-CUTOVER-PLAN.md),
[`WORKSPACE-RETIREMENT-DELETE-MAP.md`](WORKSPACE-RETIREMENT-DELETE-MAP.md).

**Tech stack:** hive-conductor FastAPI + React (generated OpenAPI client),
`maistro.goals` / Run inspection seams, Playwright surface-truth, pytest +
`@pytest.mark.ac`, `scripts/check-workspace-retirement.py`.

**Parents:** [#1046](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1046),
[#804](https://github.com/Agent-StrongHold/Project-mAIstro/issues/804),
[#7](https://github.com/Agent-StrongHold/Project-mAIstro/issues/7),
[#449](https://github.com/Agent-StrongHold/Project-mAIstro/issues/449).

---

## Why v1 of this plan was wrong

| Mistake | Correction |
|---|---|
| Treated #2275 / #2273 / #2278 as greenfield | Shells already ship on `develop` (Evolution unregistered, Capabilities + Approvals routes, e2e present). Remaining work is **closeout + deletes**, not rebuilds. |
| “Waves” without file-level PR bites | Each open issue → ordered **PRs** with exact files, tests, and exit checks. |
| Implied #2326 closes #1049/#1050/#1822/#65/#1036 | #2326 is **slice evidence only**. Issues stay open until every AC has a linked PR and a checked box. |
| Bundled #804 / #1051 / #82 into the same finish lane | #804 is its own gated track. **#82 is v1.0** (after #65). **#1051 is deferred v1.1** per [`WORKSPACE-CUTOVER-PLAN.md`](WORKSPACE-CUTOVER-PLAN.md) §9 — not on the cutover critical path. |
| Calendar sequencing | Difficulty named by **subsystem + invasiveness + gate**, not days. |

---

## Global constraints

- Branch: `cursor/<slice>-8aa9` from current `origin/develop` (after #2326 merges).
- Base every PR on `develop`. Squash merge. Restack before claiming green.
- Never terminalize Goal/Run/HITL from Home/Attention/Chat UI code — delegate to canonical owners.
- Same PR that deletes a ledger page also: removes `App.tsx` route + nav, updates `route-inventory.md`, sets the ledger row `deleted: true` (**retain the row**; do not untrack without a base-landed `untrack::<path>` grant), adds e2e that old URL does not revive the module.
- CHANGELOG `(#NNNN)`; inventory note if pytest count moves; OpenAPI regen if routes change (`dump-hive-openapi.py` → `gen:api`).
- No day/week estimates in PRs or issue comments.

---

## Issue close protocol

For each issue:

1. Comment a table: `AC | evidence PR | test path`.
2. Check every AC box on the issue body.
3. Close only when every AC has evidence on **merged** `develop`.
4. Epics (#1046, #804, #82): close only after **all** required children are closed and epic ACs are checked.

---

## Ground truth — already on `develop` (do not rebuild)

| Surface | Evidence | Remaining for its owner issue |
|---|---|---|
| Home shell (#1048) | `pages/Home.tsx`, home projection routes | Closed |
| Attention shell (#1049 partial) | `pages/Attention.tsx`, `services/attention.py`, `/attention` | MERGE MessageBoard/Optimizer; escalation; full AC evidence |
| Settings/landing (#1050 partial) | Profile restore aggressiveness, `lib/landing.ts`, Agent tool keys in chat_completion | Agent-tool e2e parity; recency policy; proposal nag policy; audit/revert |
| Chat foundation (#1037 closed; #1822 partial) | Workspace chat + continuity work in flight on #2326 | AC-3 stream isolation; AC-5 matrix; AC-6 migration; honest empty |
| Goal inspection seam (#65/#1036 partial) | `services/goal_inspection.py`, `pages/Goals.tsx`, DagRuns | Home goals wire (#2326); purge `dag_runs` JsonStore truth; provenance UI; cross-product Runs |
| Capabilities shell (#2273 partial) | `pages/Capabilities.tsx` primary nav; legacy pages still routed | Delete Agents/MCP/Skills/Topology; AC-5/6 e2e |
| Approvals shell (#2278 partial) | `pages/Approvals.tsx`, `workspace-approvals-shell.spec.ts` | Prove list/approve == CLI; foreign fail-closed; resume e2e via #1036 |
| Evolution hide (#2275 nearly done) | Route unregistered; nav absent; `navigation-coverage.spec.ts`; inventory HIDE | Confirm ledger restore owner; close issue |
| #2326 Fixem (not yet on develop) | PR open + automerge | Must merge before Track A branches |

**#2326 (must land first) adds:** Attention HITL answer + defer/dismiss; Home `_goal_items` via `goal_inspection` (not `missions`); nonterminal Run projection writers + cancel; learned-landing proposal; chat continuity/abort/`turn_id`.

---

## Track map (do these in order; parallel only where marked)

```
Track 0  Land #2326
   │
   ├─ Track A  Close Fixem issues (#1822, #1050, #1049, #1036→#65, #2278)   ◄── active finish lane
   │     A1∥A2∥A4 first; A3 (#1049 MERGE) after A1/A2 stable; A5 after A4
   │
   ├─ Track B  Delete / hide leftovers (#2275 close, #2273 delete, #2274 burn)  ◄── can ∥ Track A after A0
   │
   ├─ Track C  Honesty leftovers (#2309 CONNECT, #2323 park)                   ◄── can ∥ A/B
   │
   ├─ Track D  Persistent Agent (#2276, #2277, #805, #806 → #804)              ◄── HARD GATE: P0.5/7–10
   │
   ├─ Track E  Backlog epic (#100/#102 → #82 MERGE)                            ◄── GATE: #65; v1.0 blocker
   │
   ├─ Track F  Epic + cutover exit (#1046, overdue DELETE clear, KNOWN-GAPS)
   │
   └─ Deferred v1.1  Proactive curation (#1051)                               ◄── NOT v1.0; §9 deferral
```

---

# Track 0 — Land #2326

**Entry:** none. **Exit:** squash-merged to `develop`; local `git fetch origin develop`.

- [ ] Confirm CI green + automerge completes on [#2326](https://github.com/Agent-StrongHold/Project-mAIstro/pull/2326)
- [ ] `git fetch origin develop && git checkout -B develop origin/develop`
- [ ] Spot-check on develop: `goal_inspection` used from `home_projections._goal_items`; Attention dismiss route + OpenAPI types present

---

# Track A — Finish Fixem-owned issues

**Entry:** Track 0 done.  
**Exit:** #1822, #1050, #1049, #1036, #65, #2278 **closed** with evidence comments.

## PR A1 — #1822 remaining isolation ACs

**Closes toward:** [#1822](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1822) AC-3, AC-5, AC-6, AC-7 (confirm AC-1/2/4 from #2326).

**Files:**
- Modify: `packages/hive-conductor/frontend/src/pages/Chat.tsx` (abort/ignore foreign Workspace stream frames on switch)
- Modify: `packages/hive-conductor/backend/routes/` conversation/session handlers (authz matrix; migration disposition)
- Test: `packages/hive-conductor/tests/e2e/workspace-chat-continuity.spec.ts` (or sibling)
- Test: backend pytest for foreign session id → same status as missing; migration path

**Steps:**
- [ ] Write failing e2e: Workspace A streaming → switch to B → only B transcript; A frames discarded
- [ ] Write failing authz tests: user1 cannot list/get/stream user2 session (guessed UUID)
- [ ] Implement stream cancellation + session-scoped checks
- [ ] Document/migrate unscoped legacy sessions (refuse or attach; no admin widen)
- [ ] Honest loading/empty/unavailable UI states (no mock rows)
- [ ] Evidence comment on #1822; check ACs; close if complete

**Invasiveness:** medium (stream race + authz).

---

## PR A2 — #1050 Agent/UI/API preference parity + policy holes

**Closes toward:** [#1050](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1050).

**Files:**
- Modify: `packages/hive-conductor/backend/services/workspace_preferences.py`
- Modify: `packages/hive-conductor/backend/services/chat_completion.py` (Agent tools already partially wired)
- Modify: `packages/hive-conductor/frontend/src/lib/landing.ts`, `pages/Profile.tsx`
- Test: `backend/tests/test_workspace_landing_preference.py`, landing e2e

**Steps:**
- [ ] Prove `"hold onto my sessions longer"` (Agent or UI) expands restore window via the same preference key
- [ ] Recency policy: absolute absence **and** prior-session duration (failing unit tests first)
- [ ] Learned-default proposal: reject/ignore → no nag every return (cooldown stored on profile)
- [ ] Product call in PR: silent apply of learned default = ship behind explicit accept **or** defer to issue note (do not silently decide)
- [ ] Agent settings changes: audit event + reversible; cannot grant new scopes
- [ ] Evidence comment; close #1050 when all ACs checked

**Invasiveness:** medium (policy + Agent tool).

---

## PR A3 — #1049 MERGE MessageBoard + OptimizationInbox + escalation

**Closes toward:** [#1049](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1049). **Largest Track A PR.**

**Entry:** A1/A2 merged (or at least Attention dismiss from #2326 on develop).

**Files:**
- Modify: `packages/hive-conductor/backend/services/attention.py` (priority classes, escalation reasons, waiting quality metadata)
- Modify: `packages/hive-conductor/frontend/src/pages/Attention.tsx`
- Delete: `pages/MessageBoard.tsx`, `pages/OptimizationInbox.tsx`
- Modify: `App.tsx`, `AppShell.tsx` (remove `/messages`, `/optimizer` product nav; redirect old URLs to `/attention` **without** claiming MessageBoard still exists)
- Modify: `quality/workspace-retirement.json` (MERGE rows → `deleted: true`; **retain rows**)
- Modify: `packages/hive-conductor/docs/route-inventory.md`
- Test: attention projection unit tests + e2e Attention surfaces former optimizer/message classes

**Steps:**
- [ ] Inventory MessageBoard + OptimizationInbox data sources; map each to Attention item class (`blocking`/`popup`/`queued`/`waiting`)
- [ ] Failing tests: priority order `severity > time_sensitive > blocker > queued > follow-up > proactive`
- [ ] Failing tests: escalation requires evidence ≠ elapsed time alone; reason recorded
- [ ] Implement projection + UI indicators for rising/valuable Waiting
- [ ] Multi-Workspace bleed test
- [ ] Delete pages; mark ledger rows `deleted: true` (do not drop rows); inventory + e2e old URLs
- [ ] Evidence comment; close #1049

**Invasiveness:** high (UI MERGE + projection model + ledger).

---

## PR A4 — #1036 projection purity + #65 Goal UI fidelity

**Closes toward:** [#1036](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1036) then [#65](https://github.com/Agent-StrongHold/Project-mAIstro/issues/65).

**Files:**
- Modify: `packages/hive-conductor/backend/services/dag_run_inspection.py` (and any remaining `stores.dag_runs` / `finished_at` coercion)
- Modify: `packages/hive-conductor/backend/services/goal_inspection.py`
- Modify: `packages/hive-conductor/frontend/src/pages/Goals.tsx`, `DagRuns.tsx`
- Test: nonterminal projection tests; Goal multi-Run history; provenance visibility

**Hard rule:** Home/Goals must never re-read `missions` (ledger freeze). Use `maistro.goals` / `goal_inspection` only.

**Steps:**
- [ ] Audit every writer of projection `finished_at` / status; failing tests for WAITING≠completed
- [ ] AC-4: Builders / schedule / Evolve / Workspace Runs visible on same seam
- [ ] Goal UI: revision, multi-Run history, Run terminal ≠ silent Goal terminal, HITL/retry provenance
- [ ] Distinct waiting-human / blocked / cancel-requested / terminal rendering
- [ ] Close #1036 first (seam), then #65 (UI consuming seam)

**Invasiveness:** high (store retirement + UI semantics).

---

## PR A5 — #2278 Approvals parity closeout

**Entry:** A4 seam stable enough for resume e2e.

**Files:**
- Modify: `packages/hive-conductor/frontend/src/pages/Approvals.tsx` (if gaps)
- Test: extend `workspace-approvals-shell.spec.ts` + API/CLI parity pytest

**Steps:**
- [ ] Same pending set as API/CLI for actor
- [ ] Approve/deny/cancel → identical canonical state
- [ ] Foreign ids fail closed
- [ ] E2E: pending → answer → Run resume/terminal via #1036 seam
- [ ] Close #2278

**Invasiveness:** low–medium (shell exists).

---

# Track B — Delete / hide leftovers

**Entry:** Track 0 done. **May run in parallel with A1/A2.**

## PR B1 — Close #2275 Evolution hide

**Almost done on develop.** Do not rebuild.

**Files (verify only):** `App.tsx` (no Evolution route), `AppShell.tsx`, `docs/route-inventory.md`, `quality/workspace-retirement.json` Evolution entry, `navigation-coverage.spec.ts`.

- [ ] Confirm no nav link, no route, no stub claiming available
- [ ] Ledger records HIDE + restore owner **#51 / v1.2**
- [ ] Evidence comment + close [#2275](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2275)

**Invasiveness:** trivial.

---

## PR B2 — #2273 delete four legacy capability pages

**Entry:** Capabilities e2e happy path + unauthorized refusal green (extend if missing).

**Files:**
- Delete: `pages/Agents.tsx`, `MCP.tsx`, `Skills.tsx`, `Topology.tsx`
- Modify: `App.tsx` (remove routes; deep links → `/capabilities` or 404-without-module)
- Modify: retirement ledger (`deleted: true` on those rows; retain entries) + route-inventory
- Test: e2e Capabilities enable/discover; foreign Workspace refuse; old `/agents` etc. do not load legacy modules

- [ ] AC-1…6 evidence; close [#2273](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2273)

**Invasiveness:** medium (large page deletes; watch importers).

---

## PR B3 — #2274 retirement burn-down pass

**Entry:** after A3 (MessageBoard/Optimizer deleted) and B2.

**Files:** `quality/workspace-retirement.json`, any proven DELETE rows (Docs.tsx RETIRE, Dashboard when Home fully owns, etc.), `scripts/check-workspace-retirement.py` green.

- [ ] Every due v1.0 DELETE row: owner + disposition checked or ratified deferral
- [ ] CI refuses new imports of retired modules
- [ ] route-inventory matches shipped routes
- [ ] Close [#2274](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2274) when ACs met (may need follow-up PRs for stores still imported)

**Invasiveness:** high if store importers remain — split store burns into follow-ups owned by #82/#1036/#1050 rather than force one mega-PR.

---

# Track C — Honesty leftovers under #1046

**Entry:** Track 0. **Parallel with A/B.**

| PR | Issue | Work |
|---|---|---|
| C1 | [#2309](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2309) | Each CONNECT hive-unwired module: mount on product path **or** RETIRE; prune reachability ledger |
| C2 | [#2323](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2323) | Park collaboration CONNECT until A2UI; no nav/docs claim |

---

# Track D — Persistent Workspace Agent (#804)

**HARD ENTRY GATE (from #804 / #1046 bodies):** P0.5, P0.7, P0.8, P0.9, P0.10 green through their named issues before trusting parked/RUNNING after restart or background work. Do **not** start D from Track A momentum alone.

| Order | Issue | Focus | Invasiveness |
|---|---|---|---|
| D1 | [#2276](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2276) | Apply `tool_bindings` at Agent/Graph dispatch | medium |
| D2 | [#2277](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2277) | Persona swap API/UI/Agent same path | medium |
| D3 | [#805](https://github.com/Agent-StrongHold/Project-mAIstro/issues/805) | Goal reconciliation via persistent Agent | high |
| D4 | [#806](https://github.com/Agent-StrongHold/Project-mAIstro/issues/806) | Durable/event-driven/fenced/restart-safe reconciliation | high |
| D5 | Close [#804](https://github.com/Agent-StrongHold/Project-mAIstro/issues/804) | Epic AC checklist | — |

Write a **separate** implementation plan before D3/D4 (too large for this doc’s bite size).

---

# Track E — Backlog epic (#82) — v1.0 critical path

**Entry:** #65 closed (Goal inspection). `ROADMAP.md` lists #82 as a v1.0 release
blocker. Do **not** wait on #1051.

| Order | Issue | Notes |
|---|---|---|
| E1 | [#100](https://github.com/Agent-StrongHold/Project-mAIstro/issues/100), [#102](https://github.com/Agent-StrongHold/Project-mAIstro/issues/102) | Remaining #82 children (claim/lease; BACKLOG.md authority cutover) |
| E2 | MERGE Missions/WorkItems under [#82](https://github.com/Agent-StrongHold/Project-mAIstro/issues/82) | Ledger MERGE; same delete rules as A3 (`deleted: true`, retain rows) |
| E3 | Close #82 | After children + MERGE |

Separate implementation plan required for E1/E2.

---

# Deferred v1.1 — Proactive curation (#1051)

**Not on the v1.0 cutover critical path.** Ratified in
[`WORKSPACE-CUTOVER-PLAN.md`](WORKSPACE-CUTOVER-PLAN.md) §9 (Phase 1 step 7).

| Issue | Notes |
|---|---|
| [#1051](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1051) | Bounded discovery Runs; scout/curator; budgets; Home/Waiting only; no interrupt-by-default. Soft deps: #1049 Waiting classes + #1047 user-model (already closed) — schedule after v1.0 tag, not before #82 / cutover exit. |

Do not block Track E, Track F, or #1046 release closeout on #1051.

---

# Track F — Epic + cutover exit

**Entry:** Tracks A–C done; Track E (#82) done; Track D either done or explicitly deferred with owners on milestone #7. **#1051 stays deferred v1.1** — do not hold this exit on it.

- [ ] Close [#1046](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1046) when v1.0 children (#1048–#1050, #776/#1047, honesty children kept in-scope, and #82 via Track E) are closed; **exclude #1051** (v1.1 per §9); update epic checkbox list (still lists #776/#1047/#1048 as open in body — sync with actual closed state; mark #1051 deferred)
- [ ] Retirement ledger: no overdue DELETE without deferral owner; deleted assets keep `deleted: true` rows (untrack only with base-landed grant)
- [ ] `KNOWN-GAPS.md` no longer accepts Conductor in-memory Workspace state
- [ ] Milestone [#7](https://github.com/Agent-StrongHold/Project-mAIstro/issues/7) / initiative [#449](https://github.com/Agent-StrongHold/Project-mAIstro/issues/449): close or re-scope leftovers to v1.1/v1.2 with named owners (#2275 restore → #51; **#1051 → v1.1**)

---

## Immediate queue (after Track 0)

| Priority | PR | Why first |
|---|---|---|
| 1 | **B1** close #2275 | Evidence-only; clears noise |
| 2 | **A1** #1822 isolation | Unblocks chat trust; parallelizable |
| 3 | **A2** #1050 parity | Parallel with A1 |
| 4 | **B2** #2273 deletes | Parallel once Capabilities e2e solid |
| 5 | **A3** #1049 MERGE | First large product PR |
| 6 | **A4** then **A5** | Inspection authority → approvals resume e2e |
| 7 | **B3** / **C\*** | Burn-down + CONNECT honesty |
| 8 | **E** (#82) | After #65; v1.0 blocker — before cutover exit |
| — | **D** | Only after P0 gates |
| — | **#1051** | Deferred v1.1 — off this queue |

---

## Explicit non-goals

- Stronghold hard tenancy
- Evolution restore (v1.2 / #51)
- Building A2UI (#2323)
- Closing #1049/#1050/#1822/#65/#1036 from #2326 alone
- Starting #805/#806 without their entry gates
- Pulling #1051 onto the v1.0 critical path or ahead of #82 / cutover exit
- Dropping retirement ledger rows without a base-landed `untrack::<path>` grant
- Silent learned-landing redirect without an explicit product decision in A2
