# Late-August / September Correctness Specs

These specs operationalize the canonical architecture with narrow, directly tested invariants. Unless noted, their main next step is evidence/lifecycle promotion rather than redesign.

## August 29

- **SPEC-082926-061d — Convergence matrix unreachable share.** **AC Defined.** Keep counts derived from reachability tooling; direct test/source anchors are present. [SPEC](../../../specs/SPEC-082926-061d-convergence-matrix-unreachable-share.md)
- **SPEC-082926-0b72 — Conductor settings durability.** **AC Defined.** Preserve honest durable acknowledgement, but migrate the durable owner out of legacy Hive surfaces as ADR-096 cutover completes. [SPEC](../../../specs/SPEC-082926-0b72-conductor-settings-durability.md)
- **SPEC-082926-25a2 — AC-state per-branch notes.** **AC Defined.** Keep deterministic per-branch folding to avoid shared-baseline conflicts. [SPEC](../../../specs/SPEC-082926-25a2-ac-state-per-branch-notes.md)
- **SPEC-082926-2844 — Attempt typed output serialization.** **AC Defined.** Keep typed node output serialized at the Attempt boundary and verify every durable backend round-trips it without domain-specific side stores. [SPEC](../../../specs/SPEC-082926-2844-attempt-typed-output-serialization.md)
- **SPEC-082926-3b80 — Dashboard layout durability.** **AC Defined.** Preserve durable-or-fail writes; migrate ownership with the Workspace UI rather than keeping a second Hive authority. [SPEC](../../../specs/SPEC-082926-3b80-conductor-dashboard-layout-durability.md)
- **SPEC-082926-6f49 — Authorized corrected-measurement floor fall.** **AC Defined.** Keep explicit correction distinct from regression so measurement fixes can lower a bad baseline without opening a ratchet bypass. [SPEC](../../../specs/SPEC-082926-6f49-authorized-floor-fall-for-a-corrected-measurement.md)
- **SPEC-082926-730d — Container pool ownership.** **AC Defined.** Keep one owned asyncpg pool per database and explicit shutdown. [SPEC](../../../specs/SPEC-082926-730d-container-pool-ownership.md)
- **SPEC-082926-a44e — Resume parked schedule Run without replaying effects.** **AC Defined.** High-value M1 recovery invariant: resume from durable continuation or remain parked; never restart the whole Graph and repeat accepted effects. [SPEC](../../../specs/SPEC-082926-a44e-resume-a-parked-schedule-run-without-repeating-its-effects.md)
- **SPEC-082926-a6ab — Contained candidate validation.** **Accepted.** Direct tests/source anchors are strong; reconcile the concrete containment backend with ADR-093's autonomous security floor. [SPEC](../../../specs/SPEC-082926-a6ab-contained-candidate-validation.md)
- **SPEC-082926-c2d7 — ac-modules anchor resolution.** **AC Defined.** Keep unresolved evidence anchors as failures rather than silently awarding reachability. [SPEC](../../../specs/SPEC-082926-c2d7-ac-modules-anchor-must-resolve.md)
- **SPEC-082926-d90e — Schedule consumer node fidelity.** **AC Defined.** M1-critical: scheduled Runs must execute the actual admitted node semantics, including human pause reasons, not a lossy generic task projection. [SPEC](../../../specs/SPEC-082926-d90e-schedule-consumer-node-fidelity.md)
- **SPEC-082926-f1c3 — Reachability baseline module identity.** **AC Defined.** Keep baseline entries keyed to canonical module identities, including repository tooling. [SPEC](../../../specs/SPEC-082926-f1c3-reachability-baseline-module-identity.md)

## August 30

- **SPEC-083026-14c3 — Attempt output repair.** **AC Defined.** Repair only from proven accepted outcome evidence; never infer or read a legacy authority. [SPEC](../../../specs/SPEC-083026-14c3-repairing-an-emptied-attempt-output.md)
- **SPEC-083026-20b2 — Execution correlation context binding.** **AC Defined.** Keep canonical execution IDs on logs/spans/events across HTTP and background execution. [SPEC](../../../specs/SPEC-083026-20b2-execution-correlation-context-binding.md)
- **SPEC-083026-2601 — DAG run history durability.** **AC Defined.** Useful product projection, but migrate toward projections of canonical Runs as Hive execution ownership disappears. [SPEC](../../../specs/SPEC-083026-2601-dag-run-history-is-durable-and-bounded-on-purpose.md)
- **SPEC-083026-2642 — Node metrics measured or absent.** **AC Defined.** Preserve unknown-as-absent and prove ingest callers; avoid fake zeroes. [SPEC](../../../specs/SPEC-083026-2642-node-metrics-are-measured-or-absent.md)
- **SPEC-083026-427c — Serialized prompt versions/labels.** **AC Defined.** Keep immutable version creation and mutable label promotion one serialized/idempotent operation. [SPEC](../../../specs/SPEC-083026-427c-serialized-prompt-versions-and-labels.md)
- **SPEC-083026-4b70 — Embedding column is vector.** **AC Defined.** Keep migration/schema type asserted mechanically; pre-1.0 dimension changes should be direct schema replacement when justified. [SPEC](../../../specs/SPEC-083026-4b70-memory-entries-embedding-is-a-vector.md)
- **SPEC-083026-56ee — Session turn producing Run.** **AC Defined.** Keep turn identity, execution provenance, and session correlation separate. [SPEC](../../../specs/SPEC-083026-56ee-a-session-turn-names-its-producing-run.md)
- **SPEC-083026-58de — Durable thumbs protocol.** **AC Defined.** Keep feedback durable and read through the protocol across all backends. [SPEC](../../../specs/SPEC-083026-58de-thumbs-are-durable-and-read-through-the-protocol.md)
- **SPEC-083026-5fab — Retried turn appends once.** **AC Defined.** Preserve logical turn idempotency across retries. [SPEC](../../../specs/SPEC-083026-5fab-a-retried-turn-appends-its-messages-once.md)
- **SPEC-083026-6bc5 — Design Project scope writable/enforced.** **AC Defined.** Reconcile domain soft axes with canonical Workspace/Project authorization; no fake FK authority. [SPEC](../../../specs/SPEC-083026-6bc5-design-project-scope-is-writable-and-enforced.md)
- **SPEC-083026-6cef — Turn reports supplied usage.** **AC Defined.** Report actual provider usage when supplied and absence otherwise; never fabricate token/cost zeroes. [SPEC](../../../specs/SPEC-083026-6cef-a-turn-reports-the-usage-it-was-given.md)
- **SPEC-083026-73c1 — HITL timeout/cancel.** **AC Defined.** M1-critical durable settlement invariant; answer/timeout/cancel races must settle once. [SPEC](../../../specs/SPEC-083026-73c1-hitl-timeout-cancel.md)
- **SPEC-083026-b2b5 — Record producer provenance.** **AC Defined.** Populate canonical execution provenance on derived records at write time. [SPEC](../../../specs/SPEC-083026-b2b5-record-producer-provenance.md)
- **SPEC-083026-ba26 — Episodic memory survives restart.** **AC Defined.** Keep durable Postgres episodic store selected in production and scope predicates consistent. [SPEC](../../../specs/SPEC-083026-ba26-episodic-memory-survives-a-restart.md)
- **SPEC-083026-ef62 — User profile durability/deletion.** **AC Defined.** Converge with canonical principal/UserModelFact ownership so there is one durable personal-profile authority. [SPEC](../../../specs/SPEC-083026-ef62-user-profile-durability-and-deletion.md)
- **SPEC-083026-fcc9 — Prune superseded independent grant.** **AC Defined.** Keep authorization-state cleanup semantics explicit and deny-wins safe. [SPEC](../../../specs/SPEC-083026-fcc9-a-grant-superseded-by-independent-landings-can-be-pruned.md)

## August 31 through September 26

- **SPEC-083126-5e62 — Generated quality evidence is not the judge.** **AC Defined.** Preserve protected-base verdict authority. [SPEC](../../../specs/SPEC-083126-5e62-generated-quality-evidence-is-not-the-judge.md)
- **SPEC-090226-e4a1 — Episodic memory names producing Run.** **AC Defined.** Keep run/node/attempt provenance and scoped producer queries in every store. [SPEC](../../../specs/SPEC-090226-e4a1-episodic-memory-names-its-producing-run.md)
- **SPEC-090326-b7e2 — Browser navigation uses canonical outbound policy.** **AC Defined.** No browser/navigation client may bypass the shared SSRF/redirect/origin guard. [SPEC](../../../specs/SPEC-090326-b7e2-browser-navigation-canonical-outbound-policy.md)
- **SPEC-091226-1341 — gates-ran path scope.** **AC Defined.** A skipped check is excused only by the reviewed scope evaluator; missing/ambiguous scope fails closed. [SPEC](../../../specs/SPEC-091226-1341-gates-ran-path-scope-evaluator.md)
- **SPEC-091726-7c2a — Brief interview before Goal commit.** **AC Defined.** Preserve explicit confirmation before durable Goal/CreativeBrief creation and integrate with stable Workspace Agent identity. [SPEC](../../../specs/SPEC-091726-7c2a-brief-interview-before-goal-commit.md)
- **SPEC-092526-c41d — Warden admission of RSI harvested content.** **AC Defined.** Treat harvested external content as untrusted before it can enter RSI/Evolve prompts, memory, or candidate context. [SPEC](../../../specs/SPEC-092526-c41d-warden-admission-of-rsi-harvested-content.md)
- **SPEC-092626-1831 — Workspace work campaigns.** **Proposed.** Keep campaigns narrowing-only: they may select/steer already-authorized work but never grant authority, own lifecycle, schedule/lease work, or create a second executor. Resolve open questions before acceptance. [SPEC](../../../specs/SPEC-092626-1831-workspace-work-campaigns.md)
