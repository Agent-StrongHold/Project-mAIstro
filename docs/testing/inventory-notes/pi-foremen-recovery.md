---
inventory-delta:
  tests/: +85
---
# Portable Pi foremen and saved-session recovery

Adds 85 root-suite cases under `tests/pi_recovery/`, with no existing repository
cases removed or moved:

- 15 read-only process/tmux observation cases: shell versus Pi, full names,
  unknown identities, zombies, malformed inventories and preservation.
- 27 foreman/non-attaching launcher cases: ownership, duplicate prevention,
  bounded attempts, assignments, idle/native-intercom gating and honest progress.
- 20 journal/checkpoint cases: identity, integrity, atomicity, retention, locks,
  partial-tail restoration, task projection migration and native cold-load.
- 11 active-branch task cases: off-branch operations, reused IDs, missing or
  cyclic ancestry and unchanged journal data.
- 12 portability cases: disabled/private/exclusive initialization, explicit cwd,
  relocated CLI and non-secret path bindings across existing tmux servers.

The first 73 preserve the source mechanism's existing test names; the 12 binding
cases extend it. An isolated mutation control loses cwd/tmux bindings and fails
four relevant assertions; the actual implementation passes all 85 locally,
including the optional native SDK and three private dummy-tmux integrations.
No tests start agents, contact providers/GitHub or alter live services. Native
cases explicitly skip where their prerequisites are absent; collection still
includes them, and such skips are not native-integration proof.

Against pinned base `cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0`, root collection
in the isolated development environment is 4454 → 4539, exactly +85. Recorded
with `python scripts/check-suite-inventory.py --suite tests/ --update --note pi-foremen-recovery`;
the subsequent inventory check passed. No shared baseline, unrelated drift or
grant was changed.
