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
- `deploy/scripts/verify-restore.sh` had the same socket-probe race on its
  scratch restore target; its two `pg_isready` calls now probe
  `-h 127.0.0.1 -d "${PG_DB}"`, so a lost race cannot surface as a false
  RESTORE failure in the end-to-end drill.
- `tests/test_backup_restore_oracle.py` gains
  `test_container_readiness_probes_require_the_final_server`, pinning both
  readiness paths to TCP with an executed-query probe in the Python fixture.
  Shown to fail against the pre-fix tree (socket `pg_isready`, no `-h`).

Net count change: one test function added to `tests/`; no test removed or
parametrized. The live characterisation module's four tests are unchanged in
count — they errored on CI, they pass locally.
