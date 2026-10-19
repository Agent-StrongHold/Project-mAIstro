---
inventory-delta:
  tests/: +4
---

# restore-oracle-readiness-gate

Repairs the `test` CI job failure at
`6e2eca944ddbac50631b4ca7d92598a16c01d112` (run 39177311554, job
117822537422): all four `tests/test_restore_oracle_characterization.py` tests
errored at fixture setup because the `pg_source_container` fixture gated
readiness on `pg_isready` alone. The docker-entrypoint's *temporary bootstrap
server* answers `pg_isready` on the same Unix socket before the real server
replaces it, so the fixture's first `psql CREATE TABLE` landed in the
startup window and failed with psql exit status 2 ("connection to server went
bad"). This is the statement-channel form of the #689 lesson already recorded
for workflow service health checks.

## Changes

- `tests/test_restore_oracle_characterization.py` — `_wait_ready` now requires
  a bounded `psql … -c "SELECT 1"` round-trip on `PG_DB` (window and poll
  interval are module constants), and its failure names the last probe's exit
  code and stderr tail. No production code changed; both characterization
  fixtures (`pg_source_container`, `restore_container`) share the gate.
- `tests/test_restore_oracle_readiness_gate.py` — new: four Docker-free tests
  that pin the corrected gate with a stub `docker` binary whose `pg_isready`
  always exits 0 while `psql` exits 2 until the startup window passes:

  - `test_pg_isready_alone_is_not_readiness` — the CI regression: the
    bootstrap-answerable state must never satisfy the gate. Fails against the
    pre-fix `_wait_ready` by construction (observed live: the old gate
    declared the stub ready in 0.02s while its next `psql` exited 2).
  - `test_the_failure_names_the_last_probe_exit_and_stderr` — timeout
    diagnosability.
  - `test_ready_only_after_a_real_select_round_trip` — retries happen and
    only the round-trip ends the wait.
  - `test_every_probe_is_select_1_against_the_target_database` — structural
    pin against regressing to `pg_isready` or probing another database.

## auto-1790 merge resolution delta (round 4)

Merging develop (64ea662cb) dropped this file's TCP requirement: develop's
`_wait_ready` probes over the Unix socket, which the entrypoint's temporary
bootstrap server *also* answers with a successful authenticated `SELECT 1`
once `docker_setup_db` has run — the coverage-gate root producer hit exactly
that window at run 39130160694 (fixed on this branch by requiring
`-h 127.0.0.1`; the temp server never listens on TCP). The merge keeps both
sides — develop's bounded deadline/stderr-tail gate and this branch's TCP
probe — and the structural test now also asserts every probe targets
`-h 127.0.0.1`, so a future sync cannot silently lose the TCP half again.
Verified the pin is load-bearing: with the `-h 127.0.0.1` pair removed from
the probe, `test_every_probe_is_select_1_against_the_target_database` fails
(`ValueError: '-h' is not in list`); restored, all four pass.

## Evidence

- `uv run pytest tests/test_restore_oracle_readiness_gate.py -q` — 4 passed.
- `DOCKER_HOST=unix:///var/run/docker.sock uv run pytest
  tests/test_restore_oracle_characterization.py -v` — the four
  CI-errored tests: **4 passed in 13.99s** against real
  `pgvector/pgvector:pg17` containers.
- Regression reproduced against the pre-fix gate before editing: old
  `_wait_ready` returned "ready" in 0.02s against the stub while the
  container's `psql … CREATE TABLE` exited 2 — the CI signature.
