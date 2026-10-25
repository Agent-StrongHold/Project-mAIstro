# Workspace cutover — finish plan

**Status:** working plan for closing the open M3 cutover lane after [#2326](https://github.com/Agent-StrongHold/Project-mAIstro/pull/2326)  
**Parents:** [#1046](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1046), [#804](https://github.com/Agent-StrongHold/Project-mAIstro/issues/804), [#7](https://github.com/Agent-StrongHold/Project-mAIstro/issues/7)  
**Contract:** [`WORKSPACE-CUTOVER-PLAN.md`](WORKSPACE-CUTOVER-PLAN.md) (Phase 1–2 + retirement ledger)  
**Rule:** ship bounded PRs; do not close an epic until every child AC is checked with evidence; never invent a second lifecycle store.

---

## Current position

| Item | State |
|---|---|
| #1048 Home | Closed |
| #776 / #1047 user-model prerequisites | Closed |
| #2326 Fixem slices | Open + squash automerge; CI must finish |
| #65 / #1036 / #1049 / #1050 / #1822 | Still **open** — #2326 only landed slices, not full issue close |
| #2273 / #2274 / #2275 / #2278 / #1051 / #82 / #804 | Open |

#2326 already covers: Attention answer + defer/dismiss; Home Goals via inspection; nonterminal Run writers + cancel; restore aggressiveness + learned-landing proposal; chat continuity e2e + abort→interrupted + `turn_id`.

---

## Sequencing principles

1. **Land #2326 before branching more Fixem work** — restack children onto the merged develop tip.
2. **Contract before delete** — a retirement ledger DELETE only lands in the same PR that proves the replacement AC (cutover plan Phase 2).
3. **One owner per lifecycle** — Attention/Home/Chat project canonical Goal/Run/HITL/Approval; they never terminalize those objects themselves.
4. **PR shape** — one concern per PR; `@pytest.mark.ac` (or Playwright surface-truth) for every AC claimed; CHANGELOG `(#NNNN)`; inventory note when pytest count moves.
5. **No calendar estimates** — difficulty is named by subsystems and invasiveness below.

---

## Wave 0 — Clear the merge queue

| PR / action | Why |
|---|---|
| [#2326](https://github.com/Agent-StrongHold/Project-mAIstro/pull/2326) CI → squash merge | Unblocks every branch below |
| Sync local `develop`; close Fixem leftovers only after evidence is on `develop` | Avoid double-fixes on a moving tip |

**Exit:** `develop` contains #2326; no open Fixem CI debt.

---

## Wave 1 — Cheap v1.0 hide / ledger hygiene

Low invasiveness; unblocks retirement framing.

| Order | Issue | PR slice | Touches | Done when |
|---|---|---|---|---|
| 1.1 | [#2275](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2275) Hide Evolution | Remove nav/route; ledger HIDE + restore owner v1.2; no stub claiming available | `AppShell`, routes, `workspace-retirement` / route-inventory | AC-1…4 checked; e2e nav does not reach Evolution |
| 1.2 | [#2274](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2274) ledger pass (partial) | Owner + disposition for every v1.0 DELETE row that already has a shipped replacement (Home/Attention/settings slices) | `quality/workspace-retirement.json`, docs | AC-1 progressed; no premature file deletes |

**Exit:** Evolution unreachable in default build; ledger owners named for ready rows.

---

## Wave 2 — Finish the #2326 issue closures (remaining ACs)

Each row is one or more focused PRs; close the GitHub issue only when its AC list is fully checked.

### 2.A — [#1822](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1822) chat isolation

| Slice | ACs | Work |
|---|---|---|
| Stream isolation | AC-3 | Workspace switch mid-stream: abort/ignore foreign frames; UI shows only active Workspace transcript |
| Authz matrix | AC-5 | Two users × two Workspaces: list/get/append/complete/stream refuse foreign session ids (same status for missing vs foreign) |
| Migration | AC-6 | Explicit disposition for legacy unscoped sessions (migrate-or-refuse); no broad admin bypass |
| Honest empty states | AC-7 | Loading / empty / unavailable UI; no mock transcripts |
| Closeout | AC-1,2,4 | Confirm already-shipped evidence; mark ACs; close #1822 |

**Subsystems:** `conversation_sessions`, chat routes, `Chat.tsx`, Playwright continuity suite.  
**Risk:** stream race + authz oracle; keep fail-closed tests first.

### 2.B — [#1050](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1050) landing / settings completion

| Slice | ACs | Work |
|---|---|---|
| Agent/API/UI parity for prefs | “hold onto sessions longer”, aggressiveness + default surface via UI **and** Agent tool | Wire Workspace Agent tools to same profile/settings service as Settings UI |
| Silent apply (optional product call) | Learned default | Either ship silent redirect behind explicit accept-once policy **or** document deferral in issue + cutover plan |
| Closeout | Remaining checkbox ACs | Evidence matrix; close #1050 |

**Depends on:** #2326 learned-landing + restore already on develop.

### 2.C — [#1049](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1049) Attention completion (largest Wave-2 item)

| Slice | ACs | Work |
|---|---|---|
| **MERGE** MessageBoard + OptimizationInbox | Cutover ledger MERGE | Route sources into Attention projection; delete pages/nav when parity proven; redirect old URLs without reviving modules |
| Priority classes | severity → … → proactive | Extend projection summary + ordering; tests for lexicographic order |
| Escalation | aging/context promote; no time-only escalate | Durable escalation reasons; inspectable evidence refs |
| Waiting quality | ranking metadata | Backend fields for rising/valuable; shell indicator consumes them |
| Agent parity | answer/defer via same contract | Already partial (HITL answer + dismiss); extend for all eligible classes |
| Closeout | All 12 ACs | Multi-Workspace bleed tests; close #1049 |

**Subsystems:** `services/attention.py`, routes, `Attention.tsx`, MessageBoard/OptimizationInbox delete, retirement ledger.  
**Invasiveness:** medium–high (UI MERGE + projection model).

### 2.D — [#1036](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1036) + [#65](https://github.com/Agent-StrongHold/Project-mAIstro/issues/65) inspection authority

| Slice | Issue | Work |
|---|---|---|
| Projection purity closeout | #1036 AC-1…6 | Audit remaining `dag_runs` JsonStore / finished_at coercion paths; delete product-private terminal overrides |
| Cross-product inspection | #1036 AC-4 | Builders / schedule / Evolve / Workspace Runs on same seam |
| Goal UI fidelity | #65 | Exact revision, multi-Run history, no silent Goal completion from Run terminal; retry/HITL provenance |
| Live survival | both | Restart/reconnect e2e already partial — extend Goal deep-links |
| Closeout | both | Close #1036 then #65 (UI consumes #1036) |

**Depends on:** #2326 nonterminal writers.  
**Invasiveness:** high on store retirement; keep projection tests fail-closed.

### 2.E — [#2278](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2278) Approvals UI parity

| Work | Done when |
|---|---|
| List/approve/deny/cancel = API/CLI canonical set; foreign ids fail closed; e2e resume visible via #65/#1036 | AC-1…5; no parallel store |

**Depends on:** Wave 2.D seam stable; can parallelize UI against existing HITL/approvals APIs.

---

## Wave 3 — Capabilities surface + burn-down

| Order | Issue | PR slice | Notes |
|---|---|---|---|
| 3.1 | [#2273](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2273) | New Capabilities page over public registry/MCP/skills APIs | One nav entry; trust from host-owned data |
| 3.2 | #2273 | Delete Agents/MCP/Skills/Topology pages + nav; URL must not revive modules | Same PR or immediate follow-up once AC-5/6 green |
| 3.3 | [#2274](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2274) | Delete ledger rows whose replacements are proven (Dashboard, MessageBoard, …) | CI refuses new imports of retired modules; route-inventory matches |

**Exit:** Capabilities is the only user-facing surface for those four; retirement ledger shrinks without growing.

---

## Wave 4 — Persistent Workspace Agent (#804 lane)

Do **not** start until P0.5 / P0.7–P0.10 prerequisites named in #804 are green (issue body).

| Order | Issue | Focus |
|---|---|---|
| 4.1 | [#805](https://github.com/Agent-StrongHold/Project-mAIstro/issues/805) | Goal reconciliation through persistent Agent |
| 4.2 | [#806](https://github.com/Agent-StrongHold/Project-mAIstro/issues/806) | Durable, event-driven, fenced, restart-safe reconciliation |
| 4.3 | [#2276](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2276) | `tool_bindings` applied at Agent/Graph dispatch |
| 4.4 | [#2277](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2277) | Persona swap on API/UI/Agent same path |
| 4.5 | #804 closeout | Check epic ACs; close epic |

**Invasiveness:** high — runtime, fencing, restart. Prefer engine-first PRs with Conductor thin adapters.

---

## Wave 5 — Proactive curation + backlog epic

| Order | Issue | Depends on | Work |
|---|---|---|---|
| 5.1 | [#1051](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1051) | #1049 Waiting classes + #1047 user-model | Bounded discovery Runs; scout/curator tiers; budgets; Home/Waiting surfaces; no interrupt-by-default |
| 5.2 | [#82](https://github.com/Agent-StrongHold/Project-mAIstro/issues/82) (+ children #98–#103 as still open) | Goal inspection (#65) | Backlog DB + UI authority cutover; MERGE Missions/WorkItems |
| 5.3 | [#1046](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1046) closeout | #1049–#1051 done | Epic AC checklist; close |

---

## Wave 6 — Cutover exit (Phase 2)

From the cutover plan exit criteria:

- [ ] Retirement ledger empty of due DELETE rows (or ratified deferrals with owners)
- [ ] `stores.py` holds no Workspace-relevant `JsonStore` still consumed by shipped surfaces
- [ ] Raw-fetch / hand-typed frontend ledgers empty or only waived pre-v1.0 with owners
- [ ] `KNOWN-GAPS.md` no longer lists Conductor in-memory Workspace state as accepted
- [ ] Milestone [#7](https://github.com/Agent-StrongHold/Project-mAIstro/issues/7) / initiative [#449](https://github.com/Agent-StrongHold/Project-mAIstro/issues/449) can close or re-scope leftovers to v1.1 explicitly

---

## Parallelism map

```
Wave0 #2326 merge
    │
    ├─► Wave1 #2275 / ledger owners          (parallel)
    │
    ├─► Wave2.A #1822  ──┐
    ├─► Wave2.B #1050  ──┼─► Wave2.C #1049 MERGE+escalation
    ├─► Wave2.D #1036→#65 ┘        │
    │         │                    │
    │         └─► Wave2.E #2278    │
    │                              ▼
    └─► Wave3 #2273 → #2274 ◄──────┘
              │
              ▼
         Wave4 #805/#806/#2276/#2277 → #804
              │
              ▼
         Wave5 #1051 → #82 → #1046
              │
              ▼
         Wave6 cutover exit
```

Safe parallel pairs after Wave 0: **(2.A ∥ 2.B ∥ 2.D)** and **(1.1 ∥ early 2.A)**.  
Serialize: **#1049 MERGE before deleting MessageBoard**, **#2273 before four-page delete**, **#1036 before claiming #65 done**, **#805 before #806**.

---

## Per-PR checklist (every slice)

1. Branch `cursor/<slice>-8aa9` from current `develop`.
2. Implement + tests (pytest and/or Playwright surface-truth).
3. `uv run ruff` / scoped pytest; frontend eslint budget if UI.
4. CHANGELOG `(#NNNN)`; inventory note if suite count changes; retirement ledger row if deleting.
5. PR → `develop`; squash; only then check parent issue AC boxes with links to PR evidence.
6. Do not close epics from a partial child.

---

## Explicit non-goals (keep out of this finish plan)

- Stronghold hard tenancy (downstream)
- Evolution restore (v1.2 / #2275 restore owner)
- RSI containment epic (#50 / M5) except where #1036 needs Evolve Runs on the inspection seam
- Silent learned landing redirect unless product explicitly accepts it in Wave 2.B

---

## Immediate next action

1. Wait for [#2326](https://github.com/Agent-StrongHold/Project-mAIstro/pull/2326) automerge.  
2. Open Wave 1.1 (`#2275` hide Evolution) and Wave 2.A (`#1822` AC-3/5) as two PRs in parallel.  
3. Queue Wave 2.C `#1049` MERGE as the first large product PR after those land.
