# Acceptance-based delivery plan

Planning owner: #1629, under the existing audit/reconciliation program #412.
Roadmap and acceptance authority remain #453 and the existing issues. This file
is a dated planning projection, not a replacement backlog or a decision record.
Baseline: `develop@20e6cd4a7f8b57273fa090b5afe9f2c39a9fb923`.

## Corrections incorporated before selecting work

- #1524 is merged on the baseline. Do not dispatch the old executor retirement
  again or keep #1523 as its blocking prerequisite.
- #1047 was reopened during this pass. However, **#1581 already merged the
  UserModelFact/in-memory store/promotion/correction/tombstone core**. Reuse it.
  The residual list in #1599 predates some of that work. PostgreSQL durability,
  authenticated service integration, relevance-gated retrieval and product
  proof remain distinct work. #1588 corrects the old SQLite-twin prose.
- #1419's newest comment explicitly **keeps it in M1**, reversing the earlier
  move. Its body is stale. Keep Workspace ownership with #37/#446; do not
  downgrade an ownership defect to transparency polish based on that body.
- #1091 is closed **unmerged**. #1252 is merged, but its metadata shows a
  one-file, 73-line change. Neither status establishes full production effect
  convergence. Find successors and inspect their actual code before resuming
  #1255 or creating an effect-composition branch.
- #1099, #1110, #1204 and #374 are acceptance-closeout candidates, not automatic
  completions. The earlier source review is useful evidence, not a fresh full
  suite execution on this baseline.

Sources: existing issue/PR discussions, especially #1047, #1419, #1524, #1581,
#1588, #1599, #1091 and #1252. Review current discussions before acting.

## Planner and operating policy

Run `python scripts/plan_delivery.py SNAPSHOT.json --current-sha FRESH_DEVELOP_SHA`.
The command consumes a **reviewed snapshot**, produces JSON, and performs no
network request, repository mutation, evidence-command execution or dispatch.

Use the existing orchestrator and its current wake-up mechanism. The repository
skill `.claude/skills/delivery-plan/SKILL.md` supplies the preparation and
selection procedure. Installing these files does not modify the external
15-minute poke process. Connecting that process to the command is a separate,
explicit integration step requiring access to its real configuration.

### What a work slice means

A slice belongs to one existing issue and one bounded acceptance outcome. It
names the remaining implementation and verification points, exact write paths,
shared-interface reservations, dependencies, source references and acceptance
criteria. A parent/epic is a roll-up, not a second effort item. A related issue
is not automatically a dependency. A partial PR cannot discharge the full
parent acceptance contract.

The planner credits a slice only when all its criteria have passed, reviewed,
exact-baseline evidence and its prerequisites are credited. Source inspection,
PR merge state, closed state, test counts and skipped checks are insufficient.
Evidence records are bookkeeping supplied by the reviewer, **not authenticated
attestations**. The existing GitHub checks, independent review and acceptance
owners remain authoritative for closure and merge.

### Freshness and ownership

Before a recommendation is actionable, fetch develop, target issues and latest
comments, all relevant PR pages and changed-file pages, remote branches, review
threads and checks. Record unresolved/unknown ownership conservatively. A
closed PR must distinguish merged, superseded and abandoned. No empty search
or truncated page is proof that work is unowned. File prefixes and shared
interfaces both participate in collision checking.

Re-fetch immediately before each write. A head change invalidates exact-head
CI/review evidence. A develop change requires re-auditing affected evidence and
regenerating the snapshot. The command refuses selection from a snapshot older
than 15 minutes, future-dated, based on another SHA or marked incomplete.

### Capacity and prioritization

Start with **three actively progressing owner lanes total**, including the
verification lane. This is a WIP target, not a claim that the current fleet is
already at three. Drain/integrate existing work before adding more. A parked
branch retains ownership until explicitly handed off or retired; age alone
never frees its scope. Reuse the owner rather than create a duplicate PR.

Priority is the earliest milestone, then remaining downstream dependency-chain
work, then existing-owner reuse and a deterministic tie break. Small cosmetic
wins cannot outrank a long prerequisite chain just because they are easy.
Read-only closure review can proceed alongside a non-conflicting code lane.
Reserve scarce migration, canonical Run-admission and workflow-policy surfaces
separately; disjoint filenames do not imply independent semantics.

`build_points` and `verify_points` are rough relative effort assumptions, not
hours. Landed implementation receives no new build cost, but still carries its
remaining proof cost. The reported critical chain covers only the supplied
slices, excludes external waits and is **not a milestone finish date**.

## Execution order

### Lane A: reconcile and finish already-written work

| Issue | Next action | Exit evidence |
|---|---|---|
| #1099 | Re-run rejected-answer attribution and no-secret/unchanged-approval cases on current develop. | Distinct authenticated Alice/Bob actors; no raw secret; no settled approval; restoration of `system` fails. |
| #1110 | Re-run canonical Workspace/Project/reviewer authorization and mutation cases. | Foreign identifiers cannot inspect or settle; correct reviewer can; deleting the authorization predicate fails. |
| #1204 | Verify SQLite snapshots and supported quota-backend equivalence, not only the mutex. | Overlap, ambiguous commit/retry and restored identities produce exact totals without double count. |
| #374 | Run validator, exhaustive status/replacement tests and full real corpus. | No remaining invalid governing references; cycles and competing replacements refused; historical links retained. |
| #251 | Explain reopening against present consumer and original ACs. | Non-task admission executes, unresolvable work fails, concurrent consumers do not double-dispatch; residuals stay with their current owners. |
| #1413/#1414 | Reconfirm zero consumers; choose retirement or explicit latent-component disposition. | Do not add a product feature merely to manufacture a regression-test target. No claim of browser proof for unreachable code. |

Close one issue at a time only after its complete evidence audit. Record cleanup
closures separately from delivered runtime capability. Do not move #1419 out of
M1. Reconcile its obsolete introductory prose with the latest owner comment.

### Lane B: M1 production integration, one interface owner at a time

| Chain | Reuse first | Remaining slices and handoff |
|---|---|---|
| Goal identity -> immutable Run binding | #1575 for #1572 | Finish current PR's actual CI/review/grant conflicts; then bind exact Goal revision at canonical admission; prove historical Runs remain immutable on revision/owner change. |
| Durable effect composition -> quota -> ordinary usage | Current #1133/#1079 successors; inspect #1252; #1255 for #1196 | Establish backend-selected production Binding/Invocation/Approval/Event authority; add remaining PG quota/conformance; inject it into actual callers; retire competing trackers; prove ordinary usage through #718. |
| Canonical schedule definitions -> canonical due tick | #1603 for #1199 | Merge the definition slice safely; move real `_tick` and manual fire off the Hive dictionary; prove not-due, due, edit/delete, manual-vs-tick, restart and backend behavior. |
| Physical recovery -> reachable cadence -> integrated proof | Existing #62/#1151/#1611 work and #1618 | Inspect the exact shipped cadence and crash windows; close missing production wake/reconcile paths, then run the evidence pack against the supported backend. A harness-only merge does not close cadence gaps. |

Goal binding, quota admission and Run recovery share canonical interfaces.
Sequence their shared writes; other bounded modules may progress independently.
Do not rebase a stale historical branch wholesale over current production code.

### Lane C: M2 prerequisites and Canvas product path

| Chain | Reuse first | Remaining slices and proof |
|---|---|---|
| Scoped service reads/control | #1595 for #1152 | Migrate remaining consumers; bind authoritative actor/accounting identity; distinguish service and originating principal; test two users/Workspaces. |
| Safe retention | #1566/#1583 for #1175 | Finish continuation deletion, tombstones and remaining table dispositions/drivers; prove scope, references and failure/retry semantics. Inventory completion is not purge completion. |
| Admission containment | #1602 for #1182 | Complete refusal mapping and health; reconcile stranded capacity after crash; test supported multi-replica behavior. Do not mistake HTTP 429 mapping for crash-safe release. |
| Canonical Canvas availability | #1620 for #286/#52; existing #851/#93 | Land/adapt the root migration, then authenticated request scope, governed image Binding, route-collision-safe mount and supported worker. UI completion requires persisted output plus canonical terminal execution. |
| Tools and unattended code execution | Existing #847/#66/#76/#80 owners | Prove current allowlists, trust boundaries and actual selected sandbox backend. Keep unsupported/autonomous code execution disabled until the applicable gates pass. |

Retain one migration-chain integrator across Goal, Canvas, quota, retention and
user-model database changes. Reserve actual revision identifiers live; this
plan deliberately does not reserve numbers from old PR descriptions.

## M3 after its actual prerequisites

M3 is not one undifferentiated task and is not all greenfield work.

1. **Goal decisions (#805):** consume the canonical Goal store and exact Run
   bindings; already-satisfied, blocked, human-wait, failed-Run/replan and
   delegated-Subgoal cases. No new execution identity.
2. **Durable reconciliation (#806):** connect existing Event/recovery/lease
   authorities; forced crashes before and after admission; stale-owner fencing;
   duplicate wakeups; sleeping blocked Goals; lifetime budgets and deadlines.
3. **Backlog (#98/#100/#101/#103/#102):** reuse #1596's model/API/SQLite work;
   finish the supported durable backend before claims, history, campaigns and
   cutover. #1597 is a contract slice, not implemented campaign controls. Do not
   make a PG deployment silently use memory as the release outcome.
4. **User model (#1047):** reuse merged #1581; PostgreSQL store/conformance and
   migration -> authenticated shared service -> relevance-gated retrieval,
   composed with #1599 -> correction/forgetting/isolation/restart/backup proof.
   Memory writers must stamp the required Project provenance. The camera example
   must succeed when relevant and remain absent for unrelated tasks.
5. **Workspace Home/Attention (#1048/#1049/#1050):** consume the preceding
   services, preserve durable preferences and canonical state; no new queue,
   approval, Run or profile authority. These need finer residual decomposition
   before dispatch, not a one-PR estimate.
6. **Unified Creative Production (#773 and children):** Canvas worker/export
   and canonical Goal reconciliation -> versioned brief/shared inputs -> mixed
   artifact fan-out -> targeted consistency correction -> human edits/locks/
   branch control -> final export. Each branch must retain the same provenance.
   Decompose residual product journeys before work starts.
7. **Release (#84/#86/#87/#88/#89/#860):** exact artifact install, real-model
   execution, all authoritative-state backup/restore, supported multi-replica
   soak and byte-equivalent promotion. Record wall-clock soak separately from
   engineering effort. Changed runtime inputs require applicable new evidence.

## Dispatch packet and stop conditions

Each selected owner receives: issue + bounded slice, current base/head,
allowed paths and shared-interface lock, excluded surfaces, required tests,
expected evidence, existing PR/handoff and the condition that permits closure.

Stop and replan on changed ownership, an unanticipated universal authority,
base/candidate failure ambiguity, missing required backend or an expired
snapshot. Do not weaken a gate, fabricate a grant, declare an environmental
failure passed, or count a docs merge as product implementation.

Measure verified acceptance outcomes, substantive integrated slices, reopens,
queue age, blocked reason and active time by work class. Keep administrative
closures and raw merges separate. Do not turn the sample plan's points into
calendar estimates until actual class-specific cycle times and the entire
milestone residual are measured.

## Seed and limitations

`delivery-seed-2026-09-27.json` is a focused seed with deliberately incomplete
census flags and no invented behavioral evidence. It exercises the planner and
preserves the residual dependency structure. It should return exit code 2 and
no selected work until refreshed by the existing orchestrator/reviewer.

The executable planner is the initial tooling implementation. Full monorepo CI,
independent review, final contribution checks and actual external-orchestrator
integration are not implied by local unit tests or by opening a draft PR.
