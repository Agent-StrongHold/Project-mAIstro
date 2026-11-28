# Lane surface declarations: cap + priority-weighted overlap deconfliction

Governing policy for issue [#2250](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2250).
Implemented in the box-local fleet supervisor (`/home/dev/fleet-ops/supervisor.py`,
commits `a3761e9` and `50a2d72` on its `main`); this page records the policy
contract so lanes and planners can rely on it. Parameters are supervisor
config keys, tunable without code changes.

## Why this exists

On 2026-10-21 22:44Z a P2 lane (#795) dispatched with **421 declared
surfaces** — effectively the whole repo. The supervisor's surface-overlap
deconfliction gate correctly refused co-scheduling, so 19 lanes parked
behind one job while 17/18 worker slots sat idle (`live_jobs=1`,
`waits={"surface overlap with active lane": 19}`) for the lane's full
90-minute timeout bound. The gate worked as designed; the *declaration*
was the bug. Three failures: no cap on declared surfaces, priority-blind
overlap deconfliction, and no observability of starvation.

## Policy

### 1. Surface cap (default 40: `surface_cap`)

A lane plan claiming more than `surface_cap` (default **40**) non-ledger
surfaces may not launch as declared. Oversized declarations are resolved
autonomously — **trust the diff, not the plan**:

- The lane's actual branch diff (`base...head`) is measured. A small real
  footprint narrows the declaration to the diff and the lane launches
  normally (planners pad; the diff is the truth).
- A genuinely wide diff self-declares `wide_surface: true` with the diff
  stats as justification and launches; the starvation alarm (below) keeps
  it visible.
- If git evidence is unavailable, the lane **stays parked fail-closed**
  with a named reason (`wide surface declaration (N > cap) … (#2250)`) —
  it never silently starves the pool.

### 2. Ledger surfaces are not claimable

`LEDGER_SURFACES` (currently `quality/vulture-baseline.json`) is excluded
from the overlap set on both sides: shared ledger files (per-identity
debt baselines) never constitute a collision between lanes.

### 3. Priority-weighted soak override (default 1800s: `overlap_override_s`)

A **P0 or P1** lane that has soaked `overlap_override_s` (**30 min**)
behind **strictly lower-priority** holders proceeds past the overlap park —
worktrees isolate writes and the holder's checkpoint flow re-syncs on
develop. Everything else parks with wait reason `surface overlap with
active lane`. A P2 lane cannot override, even against P3. Lane priorities
come from the backlog plan (`backlog-plan.json`, 5-min TTL rank cache);
issues missing from it rank lowest.

### 4. Starvation alarm (default: `starve_alarm_waits`=10, `starve_alarm_live_max`=2)

When overlap-parked lanes ≥ `starve_alarm_waits` coexist with live jobs ≤
`starve_alarm_live_max` for two consecutive supervisor ticks, the
supervisor raises a `surface-starvation` ATTENTION **once per incident**,
naming the widest active holders with their surface counts (e.g. the
2026-10-24T16:25Z firing: `16 lanes overlap-parked with 2 live; widest
holders: L880 (581 surfaces), L1690 (17 surfaces), L5 (11 surfaces)`). A
non-qualifying tick resets the strike counter, so each incident alarms
anew.

### Deltas from the issue proposal

The issue proposed owner sign-off for oversized plans, a wait reason carrying
the blocking lane's priority, and an alarm after "> 2 ticks". The shipped
policy (live 2026-10-22) resolves oversized plans autonomously from
branch-diff evidence instead, parks with the fixed reason `surface overlap
with active lane` (no priority annotation), and arms the alarm after two
consecutive qualifying ticks — one alarm per incident.

## Operational evidence (2026-10-22 → 2026-11-28)

- 60 `[surface-cap]` resolution log lines: e.g. lane 1836 narrowed to its
  40-file diff, then self-declared WIDE at 41; lane 46 self-declared WIDE
  at a 589-file diff.
- 6 `ATTENTION surface-starvation` firings, each naming the widest
  holders — the L795 starvation shape is now visible within two ticks.

## Related

- PR [#2251](https://github.com/Agent-StrongHold/Project-mAIstro/pull/2251)
  (closed unmerged) proposed the adjacent ops governance page (lane repro
  isolation, `docker-compose.repro.yml`); that page is not in this tree.
- Incident context: #795 (the 421-surface lane), board snapshot 2026-10-21
  22:47Z.
