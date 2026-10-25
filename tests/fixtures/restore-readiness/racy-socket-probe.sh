# Pinned pre-fix readiness probe (racy) — extracted from verify-restore.sh as
# it shipped before #859's coverage-gate repair.
#
# A unix-socket `pg_isready -U ...` reports ready during the postgres image's
# *temporary* init server: that server comes up before POSTGRES_DB is created
# and is shut down again before the final server starts. A drill whose readiness
# signal this is can run pg_restore inside that window and die with
# `FATAL: database "maistro" does not exist` or
# `FATAL: the database system is shutting down` — both observed in the
# coverage-gate producer's root-suite run (tests/test_restore_oracle_characterization.py).
for _ in $(seq 1 60); do
  if docker exec "${SCRATCH_NAME}" pg_isready -U "${PG_USER}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "${SCRATCH_NAME}" pg_isready -U "${PG_USER}" >/dev/null 2>&1 \
  || fail_verifier "scratch postgres did not become ready"
