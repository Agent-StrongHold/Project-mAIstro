---
name: delivery-plan
description: Reconcile repository delivery work against live acceptance evidence and existing PR ownership, then select bounded non-conflicting work. Not the product Agent planner.
---

# Repository delivery planning

Read `docs/planning/DELIVERY-PLAN-2026-09-27.md` and the target issue's latest
owner decisions. #453 and the existing issue acceptance remain authoritative.
Use this procedure within the existing orchestrator. Do not add a second
scheduler, runtime, backlog database or autonomous closer.

1. Fetch current `develop` and target issues. Read all comments and linked
   successor PRs, not only issue/PR summaries. Preserve newer decisions over
   stale prose. Scope the issue inventory explicitly; include closed issues
   whose acceptance is contradicted by current evidence.
2. Read all open PR pages, changed-file pages and relevant remote branches.
   Fetch each candidate's exact head, review threads, checks and workflow runs.
   Reconcile closed-unmerged versus merged versus superseded PRs. Record every
   overlapping branch as a reservation. Unknown activity is conservatively
   active; age never automatically relinquishes ownership.
3. Build/update a local reviewed snapshot using the seed's structure. Retain
   the original issue criteria; decompose into non-overlapping slices without
   making an epic an extra work item. Record build and verification effort
   separately. Add shared-interface resources as well as file paths. Missing
   external prerequisites belong in `external_blockers`, not a fabricated
   completed dependency. Include all named dependency slices.
4. Evidence must identify each slice criterion, actual tested source SHA,
   command, immutable result reference, result, author and independent reviewer.
   Source inspection goes in `sources`, not a passing behavioral proof. Treat
   evidence fields as reviewed bookkeeping; validate the underlying artifacts
   through existing trusted checks. The planner cannot authenticate assertions.
5. Set census flags true only after all pages and required comments were read.
   Set `observed_at` only after refresh completes. A failed/partial fetch remains
   incomplete. Never merely retimestamp the seed or replace its SHA to make it
   appear current. Remove/reconcile reservations only on explicit evidence.
6. Run `python scripts/plan_delivery.py SNAPSHOT.json --current-sha FRESH_SHA`.
   Exit 1 means malformed/contradictory input. Exit 2 means refresh or coverage
   is incomplete: inspect the advisory report but dispatch nothing from it.
   Exit 0 permits considering the selected frontier; it is not merge authority.
7. Re-fetch before a mutation, preserve existing owners, and continue their PR
   where authorized. Verify source/blob identity before editing. A changed
   head/base requires relevant new evidence. Use the existing PR review and
   exact-tree CI path. Close only the full issue contract, never a partial slice.
8. On each existing wake-up, select among: unblock/review, finish the current
   slice, reconcile evidence, or start an unowned ready slice within WIP. A poke
   is not an instruction to open another PR. Leave one durable handoff naming
   the actual blocker and next action when work cannot progress.

The dated seed is not a live task queue. The command never executes supplied
commands, launches agents, closes issues or merges. Connecting an external poke
process requires access to its actual configuration and a separate integration
verification; do not claim that reading this skill changed that process.
