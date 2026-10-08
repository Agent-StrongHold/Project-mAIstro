---
inventory-delta:
  packages/maistro-core/tests: +38
---
# 888 M8-A8: replay / checkpoint / deterministic-state equivalence harness (+38)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #888 (epic #880, M8 exploratory research) asked for an evaluation of replay,
checkpoint, and deterministic-state equivalence testing over the durable subsystems, with a
GRADUATE/INCUBATE/REJECT/WATCH disposition. No live-store experiment exists in deterministic
CI (no pg backends, no real histories), so the research record
(`docs/research/888-replay-checkpoint-equivalence.md`) registers INCUBATE — promising
machinery whose detection power over line coverage is undemonstrated until the live-store
harness runs — and this change adds
the reproducible experiment machinery as one self-contained test module in
`packages/maistro-core/tests/tasks/`
(`test_m8a8_replay_equivalence_research.py`, +38 node IDs).

Unlike the offline M8 harnesses, this one drives the real production seams — the ADR-056
checkpoint fold, the ADR-086 event loop with the reference in-memory stores, the #462
recovery-event identity, and the ADR-082426 lifecycle transitions — because they are
offline-pure. The module is deliberately test-side and research-only (M8 guardrails 1-2, so
no vulture/reachability identity changes): its maistro imports are pinned to an explicit
allowlist by an AST test, and a second AST test (with a scanned-file-count guard so it
cannot pass vacuously) fails if any production module ever imports the harness.

The 38 cases validate the issue's full property matrix on deterministic, seeded fixtures
(no wall-clock assertions anywhere): fold idempotence and delivery-order insensitivity with
hand-checked arithmetic and the #624 task-level-marker rule; duplicate-delivery fidelity
(set-like kinds idempotent; the measured double-count of a duplicated SPEND_UPDATE row,
proven latent by an AST surface scan of which `CheckpointKind`s production actually
writes); ensemble recovery as a pure function of checkpoint history (repeat determinism,
version-drift refusal both stable and blocking); checkpoint-at-different-prefix equivalence
(crash before fan-out / after fan-out / after completion each converge to the unsegmented
run's canonical outcome, the completed case reusing results with zero wave re-execution);
the durable crash-loop tally opening deterministically on the fourth recovery (recorded as
a measured seam constraint — the tally cannot distinguish a completed recovery from an
interrupted one, and `recover` has no production caller at this head); event-loop
restart-halfway, repeated-replay-from-zero, concurrent-worker, and
resume-from-durable-cursor scenarios each converging to the no-crash baseline with exactly
one successful application per event and one `handler.failed` append; recovery-event
identity stable under replay and total over attempt statuses; terminal-status absorption
over the whole status space plus refusal of every revival; midpoint-checkpoint + suffix-log
replay reconstructing byte-identical records across 24 seeded legal walks (Run, NodeRun,
Attempt, lease renewals and reclaims included); projection order-independence with the
equal-ordinal tie and the WAITING-with-accepted-outcome PAUSED seam constraint pinned as
measured findings; and a frozen workload-size test that ties the note's runtime quote
(~4 s) to an exact, deterministic workload.
