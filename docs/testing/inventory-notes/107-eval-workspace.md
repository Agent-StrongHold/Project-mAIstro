---
inventory-delta:
  packages/maistro-core/tests: +41
---

# Persistent, forkable evaluation workspaces (#107)

Adds `maistro.eval_workspace` to maistro-core and 41 node IDs covering it.
The module is the durable bookkeeping substrate for evaluation environments:
environment digests for matched comparisons, digest-addressed snapshots,
fork/pause/resume/restore records, and a warm pool keyed by environment
digest. It deliberately contains no execution lifecycle — workspaces ride
the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model (ownership
per ADR-083026-e602: records name their producing execution; blank means
absent, and an unresolved run id returns nothing rather than everything) and
real environments stay behind `SandboxProtocol`.

The coverage splits along the guarantees the issue asks for:

- **Digest determinism** (11): identical environments hash identically across
  constructions; any comparison-invalidating difference — fixture content,
  egress grant, resource limits, isolation floor, insertion order, projection
  schema version — hashes differently.
- **Record lifecycle and ownership** (10): one Attempt holds a workspace at a
  time; release by a non-owner is an ownership violation; retiring is
  terminal and refuses while held; paired-field invariants (status↔owner,
  status↔retirement) are enforced at the store's write door, matching the
  canonical run store's fence-on-transition discipline.
- **Fork / identical start state** (7): two forks of one snapshot are a
  provable matched pair (`start_states_match`); forking without a recorded
  start state, restoring a snapshot from another environment, and forking a
  retired workspace are all refused rather than allowed to fake
  comparability.
- **Warm pool** (6): a claim serves exactly the requested digest or misses —
  a near-miss environment (same image, different fixtures or wider egress) is
  never substituted; a held workspace is never handed out twice; released
  workspaces return to the pool or park; FIFO under equal timestamps via
  insertion-order tiebreak.
- **Provenance** (7): workspaces and snapshots name their producing
  execution; `produced_by_run` answers "what did this Run produce"; blank
  run ids return nothing, not everything; snapshot content digests are
  computed from the captured bytes, never self-declared.

All 41 run in the default (no-services) environment: the in-memory store is
the behavioural backend, in line with ADR-083026-e602's rule that the dev
backend must do the same work the durable one does.

Naming note: the workspace status vocabulary is deliberately worded as
resource availability (`PROVISIONING`/`AVAILABLE`/`IN_USE`/`PARKED`/
`RETIRED`) rather than execution-state words (`CREATED`/`RUNNING`/
`CLAIMED`/`PAUSED`…). `check-execution-lifecycles.py` reserves that
vocabulary for the one execution identity (`Run`/`NodeRun`/`Attempt`); a
resource record that borrowed it would read as a second execution lifecycle
to the gate and to every reader. Verified: the gate discovers zero
work-state vocabularies in `maistro.eval_workspace`.
