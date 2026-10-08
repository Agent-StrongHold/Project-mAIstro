# M8-A8 research note — replay, checkpoint, and deterministic-state equivalence testing

Leaf: #888. Epic: #880 (M8 — Exploratory research and graduation).

## Hypothesis

For durable/event-driven MAIstro subsystems, replay equivalence and idempotent recovery
properties can detect correctness failures that line coverage and endpoint tests cannot.

## Canonical seams

Every seam the issue names already ships as offline-pure production code, which is what makes
this leaf prototypable without services:

- **Task/graph checkpoints (SPEC-256 / ADR-056).** `TaskCheckpoint`
  (`packages/maistro-core/src/maistro/tasks/checkpoint.py`) is the durable row; the recovery
  fold is `replay()` (`packages/maistro-core/src/maistro/tasks/replay.py`) — a pure fold,
  ordered by `sequence`, producing `ResumeState` (open tool calls, per-wave status,
  cumulative spend, pending approval gates). The production writer is the wave ensemble
  (`packages/maistro-core/src/maistro/orchestrator/waves/ensemble.py`): two task-level
  markers (`state: waves_planned` / `state: waves_complete`) plus recovery's own
  `RECOVERY_ATTEMPTED` tally that exists to survive the restart it counts. Recovery re-reads
  the whole history every time (`_recover` → `load` → `replay` → `waves_complete` short
  circuit), quarantines on the durable crash-loop count, and refuses on
  `recipe_version`/`code_registry_version` drift (both #624 lessons).
- **Durable Events and idempotent recovery (SPEC-070226-b234 / ADR-086).**
  `process_events`/`process_events_batch` (`packages/maistro-core/src/maistro/events/processing.py`)
  with injected `EventLogStore`/`TriggerStore`/`InvocationStore`: at-least-once delivery whose
  cursor only advances past an event once every matching trigger's invocation is terminal;
  `(trigger_id, event_id)` claim dedupe (atomic, lease-backed); retry capped at `MAX_ATTEMPTS`
  (3) then `handler.failed` appended once; holes reported so a durable consumer never persists
  a cursor past an uncommitted `BIGSERIAL` gap.
- **Recovery-event identity (#462/#61).** `CanonicalRecoveryEventSink` and
  `disposition_of` (`packages/maistro-core/src/maistro/runs/recovery_events.py`): the
  canonical event id is `sha256` over the logical disposition
  (type, run, node_run, attempt, disposition, cause) — deliberately identity-of-fact, not
  identity-of-delivery, so a replayed recovery cannot allocate a second Workspace sequence.
- **Run/NodeRun/Attempt reconstruction (ADR-082426-a47f/e3ff/f170).** The lifecycle module
  (`packages/maistro-core/src/maistro/runs/lifecycle.py`): transition tables where terminal
  statuses have empty target sets (absorbing); `transition_*` with injected `at` timestamps;
  `latest_node_runs` (newest ordinal per node wins — the one-level-up fence rule);
  `check_completion_is_earned` (only COMPLETED must be earned; a paused human wait blocks);
  `reclaim_attempt`/`lease_is_expired` (a terminal Attempt is never expired);
  `settle_open_node_run` (cascade to `CANCELLED` naming the Run's outcome);
  `refuse_completion_under_terminal_run` (#1335's fence).

## Record

This note does not report a live-service experiment. No PostgreSQL/pg backends, real crash
windows, or production histories exist in the deterministic CI environment, and manufacturing
them was out of scope; absent evidence is recorded rather than simulated (M8 guardrail 3). No
product code, flag, or authority path changed.

What this leaf adds is the reproducible experiment machinery, driving the **real seams** (not
replicas of them — they are offline-pure) on synthetic histories:
`packages/maistro-core/tests/tasks/test_m8a8_replay_equivalence_research.py` (test suite
only; +38 node IDs; its maistro imports are pinned to an explicit allowlist by an AST test,
and a second AST test fails if any production module ever imports the harness — M8
guardrails 1–2, enforced structurally). The issue's case matrix is covered in full:
duplicate delivery, restart halfway, repeated replay, and checkpoint-at-different-prefix.

### Measured properties (all exercised, all verdicts below are from the harness at this head)

- **`replay(history)` is stable/idempotent** — HOLDS. Repeated folds of one history are
  value-identical; delivery order is irrelevant because the fold sorts by `sequence`
  (checked over seeded histories × shuffled permutations). Hand-checked arithmetic pinned
  (open calls, wave statuses, gate sets, spend 1.5 + 0.25 = 1.75), including the #624 rule
  that task-level `state` markers contribute no per-wave record. One boundary is measured
  **NOT idempotent**, and that is a finding, not a property: at the ensemble's `recover()`
  the durable tally appends a `RECOVERY_ATTEMPTED` row on every call *before* it looks for
  completion, so a task whose every recovery succeeded still opens the crash-loop breaker
  on the fourth recovery and its completed result becomes unreachable through `recover`.
  The tally counts rows, not failures — it cannot distinguish a completed recovery from an
  interrupted one. Latent at this head because nothing in production calls `recover()` yet
  (measured: the only callers are this harness), so no real workload can trip it; recorded
  as the third seam constraint below.
- **checkpoint + suffix replay equals full replay** — HOLDS at both boundaries where the
  property is consumable. Ensemble boundary: a history segmented as [planned marker] +
  (restart, re-execute) lands on the same canonical winner as the unsegmented run (and a
  `waves_complete` checkpoint replays to the same winner with zero re-execution); the
  lifecycle boundary: midpoint record + suffix log reconstructs a byte-identical
  `model_dump()` (timestamps included) across seeded legal transition walks for Run,
  NodeRun, and Attempt. The event loop's cursor is the same property one level out:
  restart-from-zero and resume-from-durable-cursor both converge to the no-crash baseline
  with each event applied exactly once.
- **duplicate delivery does not duplicate canonical effects** — HOLDS for the event loop
  (atomic claim: concurrent workers deliver once; terminal invocations are never re-claimed
  across repeated replays; `handler.failed` is appended exactly once per permanently-failed
  event no matter how often the history replays) and for recovery-event identity (same
  disposition fact → same canonical event id; different disposition → different id). At the
  task-checkpoint fold, the property HOLDS for the set-like kinds and **FAILS for spend**:
  a duplicated `SPEND_UPDATE` row double-counts (`replay((c, c)).cumulative_spend == 2×
  delta`). This is a **measured fidelity constraint, not a live defect at this head**: the
  harness's AST surface scan shows the only production writers are
  `WAVE_FAN_OUT`/`WAVE_COMPLETED`/`RECOVERY_ATTEMPTED` — nothing writes `SPEND_UPDATE`
  (nor `TOOL_CALL_*`/`APPROVAL_GATE_*`; `MEMORY_PROMOTE` is referenced by no code at all
  outside its definition, and `RECOVERY_ATTEMPTED` is written but only ever *counted*,
  never folded). Any future replay-based spend assertion must dedupe by
  `(task_id, sequence)` before folding or constrain its store contract to key uniqueness.
- **terminal state never regresses after replay** — HOLDS structurally: terminal statuses
  have empty transition sets in both tables, `transition_path` refuses to leave them, a
  terminal Attempt refuses every revival transition and `reclaim_attempt`, is never
  lease-expired, and `refuse_completion_under_terminal_run` refuses post-terminal
  completions for all four terminal Run statuses.
- **equivalent durable histories reconstruct equivalent observable state where ordering
  contracts permit** — HOLDS, with the boundary now exact. `latest_node_runs` and the
  completion verdict are invariant under arbitrary delivery order of *distinct* NodeRuns;
  a re-execution (ordinal 2) wins over ordinal 1 under every ordering. Two measured
  ordering-contract edges: (1) two records claiming the same node AND ordinal violate the
  store contract, and the projection then keeps whichever came first — a replay harness
  must dedupe by identity+ordinal before projecting; (2) the Run transition table admits
  WAITING→PAUSED for a NodeRun carrying an accepted outcome, but the record validator
  rejects the carried WAITING outcome on a PAUSED record — so the replay state space is
  `(status, has-accepted-outcome)`, not status alone. Neither is reachable from production
  writers at this head (the reconciler's pause path short-circuits WAITING records), but
  both are exactly the kind of latent seam disagreement this class of testing exists to
  surface, and both are pinned so they are measured once instead of rediscovered per
  harness.

### Normalization / fidelity complexity and the fields that must be controlled

Comparing reconstructions required controlling exactly four nondeterminism sources, all
already injectable in production code: wall-clock timestamps (every lifecycle seam takes
`at=`; models accept explicit `created_at`/`finished_at`), identity minting (explicit
`node_run_id`/`trigger_id` — trigger ids are store-local, so cross-store comparisons key on
event ids), evidence containers (frozen dicts/lists compare by value), and the invocation
store's lease clock (`time.time()`, harmless at test scale). No field required production
change. Version currency (`recipe_version`/`code_registry_version`) is a fifth axis that
does not need normalization but must match: drift refusal is itself a replay-stable
decision, measured.

### Runtime and gating

The full harness (38 cases: 60 fold replays over 10 seeded histories, 5 event-loop
restart/replay scenarios, 24 seeded lifecycle walks × midpoint splits) runs in ~4 s in CI
conditions. That cost profile supports **PR-gating the pure-seam property suite** (it is
already cheaper than many existing integration cases); what must remain nightly or
on-demand is anything driving the pg/sqlite stores with real crash injection between
durable writes — that harness does not exist yet (see procedure). This suite is deterministic
(seed-fixed, no wall-clock assertions, single-event-loop) and is safe to gate.

## Benchmark procedure (what a real experiment must do)

1. Record representative live histories: real task checkpoint streams from ensemble
   recoveries, real durable event logs with their invocation rows, real Run/NodeRun/Attempt
   transition logs from a workspace doing ordinary work (exported through the canonical
   stores only; no synthetic rows mixed in).
2. For each history, replay to the canonical final state with the production seam, then
   compare against the store's own final rows: any disagreement is a live defect and routes
   to the M0–M7 owner (ADR-056 / ADR-086 / execution spine) — it does not stay in this
   research lane.
3. Inject crash windows at every durable-write boundary (between checkpoint append and wave
   start, between handler return and cursor persist, between Attempt write and Run write);
   replay from the surviving durable state; compare canonical effects against the no-crash
   baseline (the property the in-memory harness already pins, now against real transaction
   semantics, `BIGSERIAL` holes, and lease expiry races).
4. Sweep checkpoint-at-different-prefix over real histories (resume from every prefix), and
   run the duplicate-delivery matrix with real double-delivery (two workers, real leases).
5. Report per property: holds/fails, defect count with severities, normalization effort,
   runtime at production history sizes, and the nondeterministic fields that had to be
   controlled on real data (the four above are the prior).
6. Re-run the AST surface scan: if production begins writing the currently-unwritten
   checkpoint kinds (notably `SPEND_UPDATE`), the duplicate-spend fidelity constraint
   becomes live defect surface and must be re-measured before any replay-based spend
   feature ships.
7. Update the disposition here.

## Trust boundary

Every verdict the harness produces is advisory evidence. It writes only the reference
in-memory store implementations production itself ships for tests/dev, reads no Goal, owns
no event authority, and makes no recovery decision; recovery policy stays in
`WaveOrchestrator`/the reconcilers and this module cannot be imported by production (its
own AST test fails the suite if that ever changes), nor may it widen its maistro imports
beyond the pinned allowlist. The canonical execution model
(`Goal -> Graph -> Run -> NodeRun -> Attempt`) is untouched; the harness observes its seams
and asserts nothing into them.

## Disposition

- #888 (replay / checkpoint / deterministic-state equivalence testing): **INCUBATE** — the
  prototype works and the properties hold on the pure seams (three latent seam constraints
  found and recorded; zero live defects at this head), but no experiment against live
  stores or real histories exists, so the hypothesis's *detection power over line
  coverage* is undemonstrated on MAIstro workloads. Next required evidence: the
  live-store crash-injection harness (procedure steps 1–4) runs on real histories and
  either finds a real recovery defect the existing suites miss (then also PR-gate the
  property suite as regression coverage) or completes a sweep with measured runtime and
  defect counts.
- Move to **REJECT** if live-store replays agree with store state everywhere the in-memory
  harness already agrees and the only findings remain the three recorded latent constraints —
  i.e. the properties add no detection beyond the existing per-seam suites at material
  runtime cost.
- The three recorded seam constraints get fixed through normal implementation work owned
  by their owners if they ever become reachable: duplicate-`SPEND_UPDATE`
  dedupe (or a store-contract note) when a spend-writing checkpoint producer lands; a
  decision (allow-and-migrate, or refuse-at-transition) for WAITING→PAUSED with a carried
  accepted outcome if a writer ever needs it; and a recovery tally that distinguishes
  completed from interrupted recovery (or keys the breaker on incomplete recoveries) when
  `recover()` gains its first production caller — the ensemble owner's call.

No adoption is authorized by this note.
