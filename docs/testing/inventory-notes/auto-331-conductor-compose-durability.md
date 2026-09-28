---
inventory-delta:
  packages/maistro-core/tests: +11
  packages/hive-conductor/backend/tests: +8
---

# #331 Conductor Compose data-directory durability

Issue #331 makes the standalone Compose deployment's persistent-state contract
real and testable.

## Production changes

- `packages/hive-conductor/backend/services/data_dir_guard.py` (new): the
  startup guard. `verify_durable_data_dir` creates the configured
  `CONDUCTOR_DATA_DIR`, proves writability with a real write/fsync probe, and
  — only when running inside a container (`/.dockerenv` /
  `/run/.containerenv`) — refuses a data directory that is not a mounted
  filesystem (`DATA_DIR_EPHEMERAL`), because container-layer state is
  discarded on recreate. `CONDUCTOR_ALLOW_EPHEMERAL_DATA_DIR=1` is the
  documented escape hatch for throwaway harnesses; it does not skip the
  writability probe.
- `packages/hive-conductor/backend/services/foundation.py`: `Foundation.start`
  runs the guard before the vault/state/credential subsystems touch a file,
  so a refusal leaves nothing half-initialized and the lifespan refuses to
  serve.
- `packages/hive-conductor/docker-compose.yml` (standalone): mounts the named
  volume `conductor-data` at `/data` and sets `CONDUCTOR_DATA_DIR=/data`.
  The image pre-creates `/data` owned by the nonroot runtime uid 65532, so
  the empty named volume inherits least-privilege ownership on first use.
- `packages/hive-conductor/docker-compose.test.yml`: declares the escape
  hatch explicitly — the e2e harness wants throwaway state so every run
  exercises the one-shot setup wizard.
- `packages/maistro-core/src/maistro/cli/_security.py`: `maistro security
  backup` captures every file in the data directory in one pass into a
  single archive (staged `.tmp`, fsynced, then renamed — the output name
  never names a partial archive); `maistro security restore` extracts to a
  staging sibling and swaps with two renames, so a crash leaves either the
  old directory or the restored one, never a half-restored mix of coupled
  files (vault without identity key, credential store without master key).
  Dry-run by default, like the other `maistro security` operators; refuse
  corrupt/truncated archives and unsafe paths before touching the target.
- `packages/hive-conductor/scripts/verify-compose-durability.sh` (new) +
  `hive-conductor-compose-durability` CI job: guard refusals, then
  create → write → recreate (down/up AND image rebuild) → read → backup →
  restore, all against the real standalone compose file.

## Test deltas

- `packages/maistro-core/tests/cli/test_security.py`: TestBackup (+5) and
  TestRestore (+6) — atomic single-pass capture, staged rename, default
  output location, empty/missing-dir refusals, no-overwrite, dry-run
  inertness, coupled-file round trip with the master key still decrypting,
  owner-only restored directory, corrupt/truncated archive refusal before
  the target is touched, stale-staging refusal, and path-traversal refusal.
- `packages/hive-conductor/backend/tests/test_data_dir_guard.py` (new, 8
  tests): creation+probe cleanup, unwritable refusal, uncreatable-parent
  refusal, in-container ephemeral refusal, in-container mounted pass, escape
  hatch (still probing writability), no mount requirement on a host, and
  Foundation.start refusing before any subsystem initializes.

## Known pre-existing, out of scope

`test_registration_policy.py::TestInvitations::
test_independent_process_writers_publish_one_username` fails intermittently
under full-suite machine load (spawned workers re-import the backend behind
a 10 s barrier and a 20 s join timeout) and passes in isolation. Its import
and execution path (models.schemas, maistro.state, services.model_store,
services.registration_policy, routes.auth, stores) does not touch any file
this branch changes; reproduced 2/2 under full-suite load and 1/1 in
isolation on branch auto-331.

## Validation

- `uv run pytest packages/maistro-core/tests/cli/test_security.py
  packages/hive-conductor/backend/tests/test_data_dir_guard.py -q` → 34 passed.
- `uv run pytest packages/hive-conductor/backend/tests -q` → 2938 passed,
  6 skipped, 1 pre-existing load flake (above), before and after identical
  except for that flake.
- Full compose durability scenario executed locally against real Docker
  (results in the PR/lane notes) — guard refusals and the complete
  create/write/recreate/read/backup/restore round trip.
