# Persistent Pi foremen and recovery

Optional operator tooling, not a product daemon or a second autonomous fleet.
Read [the runbook](../../docs/operations/pi-foremen.md) before operating it.

- `pi`: human control/recovery front door; recover the exact registered journal.
- `maistro`: operations, ownership and bounded stall diagnosis.
- `homie1`: one admitted repair with reproducible verification; idle if unassigned.
- Source: `scripts/pi_recovery/`; tests: `tests/pi_recovery/`.
- Native intercom messages, never terminal keystroke injection or destructive
  pane replacement. Liveness, delivery, progress and remote completion differ.
- Startup/pokes grant no implementation, publication, merge or service authority.
  Reconcile existing work/owners and full remote SHAs before effects; no replay.
- Repo-owned memory is this portable contract/runbook, not private conversations.
  Live IDs, assignments, journals, credentials and host evidence remain outside Git.

A clone provides code and instructions, not a running installation or restored
private memories. Nothing is armed by checkout, import, or test collection.
