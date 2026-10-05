# M8-J research plan — human-agent interaction, generative UI, and mixed-initiative control

Epic: #909. Initiative: #879.

## Hypothesis

Interaction patterns — generative/A2UI surfaces, mixed-initiative planning
and editing, progressive disclosure of reasoning/evidence, approval and fence
interactions, live Graph/Run visualization, interruption/redirect/resume UX,
confidence presentation, collaborative artifact editing, and attention
policies for long-running Goals — can lower supervision burden and intercept
more Agent mistakes *without* client UI state becoming a second
execution/control authority. The null hypothesis the epic guards against: any
pattern whose value depends on the client inventing or holding state the
canonical stores do not hold.

## The projection rule (epic contract, operationalized)

Every M8-J experiment projects canonical state; none produces it. The shipped
tree already enforces this from both sides:

- **Server side.** The durable store is the only lifecycle authority (#48's
  fifth criterion, restated in the `hive-conductor` HITL door header,
  `packages/hive-conductor/backend/routes/hitl.py`): the route translates
  store refusals into status codes and re-decides nothing. The durable graph
  store is the canonical projection (ADR-082826-d9f5), and the one canonical
  Event envelope is persisted before compatibility consumers see it
  (`maistro.events.publisher`, #61) — delivery is at-most-once and never a
  second ordering authority. The Workspace Attention projection
  (`packages/hive-conductor/backend/services/attention.py`, #1049) is the
  pattern in miniature: computed at read time from the owners that already
  hold the state, persisted nowhere, and its items link back to the canonical
  settle route rather than offering a parallel one.
- **Client side.** The visual-artifact trust boundary (#768) owns every place
  model/persisted markup reaches the browser, and the Design Studio page
  states browser storage is never the system of record for loop state
  (`packages/hive-conductor/frontend/src/pages/DesignStudio.tsx`).

A UI experiment that fails this rule is not an M8-J result, however good its
numbers.

## Canonical seams (verified against the shipped tree)

| Interaction surface | Canonical state it must project | Shipped seam |
|---|---|---|
| Human pauses (question/approval/review) | Run + NodeRun pause records, durable deadlines | `human.ask_question` / `human.approve_draft` / `human.review_and_edit` / `human.delegate_to_role` nodes (`packages/maistro-core/src/maistro/graph/nodes/`); `RunStatus.PAUSED`; settle authority `DurableRunStore.submit_hitl_answer` |
| Human work discovery + settlement | pending pauses across Runs | HITL door: `GET /pending`, `GET /{run_id}/{node_id}`, `POST /{run_id}/{node_id}/answer|cancel`, `POST /expire` (`routes/hitl.py`); effective-principal `HitlAuthorization` with membership re-checked at settle time (`maistro.graph.durable_runs.hitl`) |
| Attention / triage | read-time classification of the above | `GET /{workspace_id}/attention` (`routes/attention.py`), deterministic classes, deadline horizon `time_sensitive` |
| Run observation | `Goal -> Graph -> Run -> NodeRun -> Attempt` records | `maistro.runs.model`; `GET /runs/{run_id}`, `GET /runs/{run_id}/node-runs` with attempt summaries, `POST /runs/{run_id}/cancel` (`maistro_server/api/runs.py`); append-only `RunEvalScore` evidence naming run/node_run/attempt + Goal/Rubric revisions |
| Live progress | canonical Events + task progress | task-scoped WebSocket (`maistro_server/api/ws.py`); canonical Event envelope store (#61); graph UI itself polls every 10 s (`DagRuns.tsx`) |
| Interruption / resume | Attempt terminal states with cause | `CancellationCause.REQUESTED` vs `RECOVERED` (#230, `maistro.runs.model`); parked-run resume (SPEC-082926-a44e); HITL timeout/cancel (SPEC-083026-73c1); state-history epochs (`durable_runs/time_travel.py`) |
| Generated UI artifacts | sanitized artifact trees, not client truth | `maistro-design` code outputs (`REACT_TSX`/`HTML`/`SVG`) under ADR-062326-702b artifacts; render-side sanitizers (#768: `visualArtifactRenderer.tsx`, `deckSanitizer.ts`) |
| Declarative agent-driven UI | designed, not implemented | ADR-070426-3a1f (A2UI v0.10 adoption) and SPEC-277 are **Proposed**; SPEC-277's own finding: "no code, no route, no catalog registry" |
| Human notifications | push feed, no state | `maistro.protocols.notification` (`Notification`/`NotificationClient`, ntfy); machine-readable `maistro.tasks.progress_webhook` |

## Candidate research directions

Status against the shipped tree: **exists**, **partial**, or **absent**. Each
becomes a leaf ending GRADUATE / INCUBATE / REJECT / WATCH. Baselines are the
shipped behavior; every metric below is one of the epic's six (task
completion, supervision burden, error interception, comprehension,
interaction cost, recovery from mistaken Agent actions).

- **A. Generative / A2UI interfaces — partial.** Generative UI ships today as
  *code artifacts*: an LLM writes React/HTML/SVG, the artifact tree stores it,
  and the #768 boundary sanitizes it at render. The data-driven alternative —
  A2UI declarative messages over a trust-reviewed component catalog, so the
  agent sends *data* the client renders inside a fixed safe component set —
  is adopted on paper (ADR-070426-3a1f, SPEC-277) with zero implementation.
  Leaf question: at equal task completion, do data-driven surfaces beat
  generated-code artifacts on error interception (hostile-component refusal
  before render vs sanitize-after) and interaction cost, without a client
  surface state that outlives its server-side `A2uiSurface` record?
  Baseline: the current generate-then-sanitize pipeline on the same briefs.
- **B. Mixed-initiative planning and editing — exists.** The human is a *node
  kind* in the canonical DAG (`human.*` pauses are checkpointed, durable, and
  resumable like any other node), and humans edit graphs pre-execution in
  DagBuilder. Initiative mixing is therefore already server-authoritative by
  construction. Leaf question: when does *asking* (`human.ask_question`
  mid-Graph) beat *deciding then explaining* on comprehension and recovery,
  at matched task completion? Baseline: the fully autonomous alternative —
  no human node, or the deadline paths where an unanswered pause ends in a
  `timed_out` verdict (`human.approve_draft`, `human.review_and_edit`) or
  fails the Run (`human.ask_question`'s timeout contract).
- **C. Progressive disclosure of reasoning/evidence — partial.** The record
  chain exists (NodeRun → Attempts with summaries, append-only `RunEvalScore`
  bound to Goal/Rubric revisions), and the runs API exposes one drill-down
  level (`/runs/{run_id}/node-runs`). There is no depth-tiered UI. Leaf
  question: does attempt-level evidence drill-down improve recovery from
  mistaken Agent actions (time-to-correct-cause-identification) without
  raising interaction cost for users who never expand it? Baseline: the
  status-only run list.
- **D. Approval / fence interaction patterns — exists.** Binary verdicts
  (`human.approve_draft`: approved/rejected/modified/timed_out), structured
  redlines (`human.review_and_edit`), durable deadlines with `POST /expire`,
  and the same doctrine in governance: promotion fences read `human:<id>`
  author provenance and fail closed on self-approval
  (`maistro.governance.promotion`). Leaf question: does batch approval of
  multiple pending pauses raise mistaken-approval rate (error interception)
  relative to per-pause settlement, at what supervision-burden saving?
  Baseline: today's one-pause-one-answer door.
- **E. Live Graph/Run visualization — partial.** The UI polls (10 s in
  `DagRuns.tsx`); a task-scoped WebSocket exists but there is no run-scoped
  event stream to the graph UI, and none may be built as a second event
  authority — a run-stream leaf must consume the canonical Event envelope
  store (#61) as a projection. Leaf question: does push (projected from the
  canonical event log) reduce time-to-notice of stalls/failures (supervision
  burden) versus the 10 s poll, at what server cost? Baseline: the polling
  page on identical Runs.
- **F. Interruption, redirect, and resume UX — exists (mechanism), absent
  (UX).** Cancel with cause (#230), parked-run resume without repeating
  effects (SPEC-082926-a44e), HITL answer/cancel/expire, and time-travel
  state epochs are shipped and tested. What does not exist is a *redirect*
  interaction — edit future state mid-Run and resume from an epoch. Leaf
  question: does mid-Run redirect beat cancel-and-replan on recovery cost
  (wall-clock and wasted Attempts) and task completion? Baseline: cancel +
  fresh Run on the same Goal.
- **G. Confidence/uncertainty presentation — absent at the human surface.**
  Internal predictors exist (RLPHD's point-estimate approval probability,
  request-analysis confidence), but nothing exposes uncertainty to a user,
  and the internal M8-E uncertainty/calibration leaf owns the measurement
  side. Any presentation leaf must consume calibrated, recorded confidence —
  not re-derive it client-side — or it violates the projection rule.
  Leaf question: does presenting calibrated uncertainty on approval requests
  change interception quality (reject/modify rate on would-be mistakes)
  without habituation (approval rate drifting back)?
- **H. Collaborative artifact editing with Agents — partial.** The
  server-side model of co-editing already exists and is good:
  `human.review_and_edit` carries field-level edits (dotted path, old/new,
  note) as *structured data* the Run records. Canvas and the fixed-page
  editors keep browser storage out of the system of record. No multi-user
  presence/OT/CRDT layer exists anywhere in the tree. Leaf question: do
  structured redlines outperform free-form replacement on comprehension of
  *what changed* and on recovery when an edit was itself mistaken, at equal
  interaction cost? Baseline: flat replacement blob
  (`human.approve_draft`'s modify verdict).
- **I. Notification/attention policies for long-running Goals — partial.**
  Attention is a deterministic read-time projection (#1049) with a 24 h
  deadline horizon; only `time_sensitive` and `queued` have producers today;
  the `severity`/`blocking`/`follow_up`/`proactive` classes are named but
  producer-less by design. Push exists (`Notification`/ntfy) but is not
  policy-wired to Runs. Leaf questions: which horizon and class ladder
  minimizes time-to-settle on time-sensitive pauses without inflating
  notifications per settled item (interaction cost)? Evidence is fully
  canonical: pause deadlines, settle timestamps, and deadline-elapsed
  (`timed_out`) verdicts are all persisted.

## Measurement contract

Leaves report all six epic metrics, and each names its canonical source up
front: task completion → terminal `RunStatus` + append-only `RunEvalScore`;
supervision burden → human-pause count and time-to-settle from durable Run
records; error interception → rejected/modified/timed_out verdict counts and
promotion refusals against realized mistakes; interaction cost → settlement
actions per pause and per completed Run (audit-log rows, HITL door calls);
recovery from mistaken Agent actions → `CancellationCause.REQUESTED` versus
`RECOVERED` counts, fresh-Attempt chains, epoch appends after redirect.
Comprehension has no canonical store today; a leaf that claims it must
define the instrument (a scored rubric over recorded Runs, evaluated by
humans under a fixed protocol) in the leaf itself, or drop the claim. A
metric with no named source is not reportable.

## Reproducible artifacts

Every measurement above reads records that already persist: durable Run
records with pause metadata and deadlines (`graph_state.metadata["pauses"]`),
append-only eval scores, audit-log rows from the HITL door, attention read
projections, and `CancellationCause` on Attempts. No experiment this note
reports, so no new artifact is added; per-leaf procedures must reuse these
stores rather than side logs, or they are not M8-J leaves.

## Record

This note reports no experiment. No interaction pattern has been measured
against a canonical MAIstro seam under the epic's six metrics; what exists —
the `human.*` node family, the HITL door, attention projection, runs API,
sanitizing renderers — is prior substrate that defines the baselines, not an
M8-J result. A2UI remains unimplemented (ADR-070426-3a1f and SPEC-277 are
Proposed). This change adds no product code, no flag, and no client surface.

## Disposition

WATCH at epic level. Directions A–I become leaves ending individually in
GRADUATE / INCUBATE / REJECT / WATCH. Any GRADUATE result routes product
changes to Design Studio/product/HITL owners per the epic's exit contract;
it can never authorize a client-side execution authority, because the
projection rule is the thing being tested *and* the boundary the result must
respect. The epic is done when every leaf carries a documented disposition.
