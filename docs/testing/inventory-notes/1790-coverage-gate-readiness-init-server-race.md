---
inventory-delta:
  tests/: +1
---
# 1790 — coverage gate: readiness probes must require the final PostgreSQL server

The coverage gate's root producer failed on CI (run 39130160694, job
117686209144) with four `ERROR`s in
`tests/test_restore_oracle_characterization.py`, all raised by the
module-scoped `pg_source_container` fixture: `docker exec … psql … CREATE
TABLE …` exited 2 — "connection to the server went bad" — immediately after
the fixture's own readiness probe had passed. The candidate's diff was two
test files, neither touching anything the fixture reads; the same suite
passed on `develop`'s tip run hours later. The gate was red on a flake class,
not on content.

The mechanism, reproduced locally against `pgvector/pgvector:pg17`: the
official image's entrypoint initialises the cluster under a **temporary
server bound to the unix socket only** (`listen_addresses=''`), and that
server answers `pg_isready` — and even an authenticated socket `psql` query —
before it is stopped and the final server starts. A probe landing in that
window reports ready, and the fixture's first statement races the temp→final
restart and dies with psql exit 2. A socket probe cannot distinguish the two
servers; a probe over `-h 127.0.0.1` stays unanswered until the final server
listens, because the temporary one never binds TCP.

Fixes, all in service of making the failing gate deterministic:

- `tests/test_restore_oracle_characterization.py::_wait_ready` now probes
  with `psql -h 127.0.0.1 … -c 'SELECT 1'` — TCP (temp server cannot answer)
  and an executed query (authentication and statement execution proven), the
  two things the statements after the probe rely on.
- `deploy/scripts/verify-restore.sh`'s scratch readiness loop had the same
  socket-probe race (`pg_isready` alone passes while the temp server runs); the
  loop now additionally requires a `psql -d "${PG_DB}"` query that executes
  `SELECT 1;` against the target database, and its post-loop guard fails as a
  verifier when the target database never answers. (develop #2185 owns this
  socket+query shape; its `test_scratch_ready_means_the_target_database_answers`
  pins it.)
- `tests/test_backup_restore_oracle.py` re-lands
  `test_container_readiness_probes_require_the_final_server`, pinning the
  characterisation fixture's readiness probe to TCP (`-h 127.0.0.1`) and an
  executed query (`SELECT 1`). The pin was carried by the #1790 readiness
  repair, dropped when develop #2185 rewrote this file, and re-landed here
  because the characterisation fixture keeps the TCP probe — the one that
  actually proves the final server — and was left unpinned by #2185. The drill
  script's shell readiness is pinned separately by #2185's test. Shown to fail
  against the pre-fix tree (socket `pg_isready`, no `-h`) and against a
  socket-only regression of the fixture's probe.

Reconciliation with develop: develop #2185 rewrote this file and replaced the
original two-path TCP pin with `test_scratch_ready_means_the_target_database_answers`
(socket `pg_isready` + `psql -d PG_DB` query for the drill script). The
characterisation fixture's TCP probe was left intact by #2185 but left
unpinned; re-landing this pin restores the round-4 intent that the structural
test assert every probe targets `-h 127.0.0.1` so a future sync cannot
silently lose the TCP half again.

Net count change: one test function added to `tests/`; no test removed or
parametrized. The live characterisation module's four tests are unchanged in
count — they errored on CI, they pass locally.
