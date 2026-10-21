# Repair #859 — develop-sync + restore-readiness union (branch auto-859)

Starting head `6c5663de1911d3bd9fcaf40b88b6dc879aefb4cc` (assigned), dispatch
develop base `0a3dfdb4e7a97f29ed11e196cd9c86fe2ddde7a6`. Worktree arrived
**clean**; nothing was assumed from earlier rounds — every claim below was
re-derived in this tree. No GitHub mutations were performed.

## 1. Named gate failures at the assigned head (from the job's dispatch evidence)

`gh api repos/.../commits/6c5663de1.../check-runs` showed two failing checks,
both with the same root cause:

| check-run | id | conclusion | evidence |
| --- | --- | --- | --- |
| `test` | 118995939035 | failure | root suite: `FAILED tests/test_backup_restore_oracle.py::test_scratch_readiness_probes_final_server_and_target_db` |
| `Coverage gate (publish-set floor + diff coverage)` | 119001171330 | failure | same test failed inside the root-suite coverage producer |

The failure message was:

```
AssertionError: verify-restore.sh readiness wait is racy: readiness probe does not
go over TCP loopback: the init entrypoint's temporary server (socket-only,
listen_addresses='') can satisfy it
```

## 2. Root cause: the merge commit resolved a semantic conflict one-sidedly

`6c5663de1` merged develop `780f1d340` and took **trunk's** `verify-restore.sh`
("trunk canonical for restore-oracle"). But branch and trunk each carried a
*different, independently landed* fix for the same scratch-Postgres readiness
race, and each side's just-landed test asserts its own shape:

- **Branch** (`2e614e42d`) — TCP-loopback probe, `psql -X -h 127.0.0.1 … -d "${PG_DB}" -c 'SELECT 1'`;
  test `test_scratch_readiness_probes_final_server_and_target_db` asserts
  `"-h 127.0.0.1"` and `"SELECT 1"` appear in the script.
- **Trunk** (`780f1d340`) — socket `pg_isready` **and** socket `psql … -d "${PG_DB}"`;
  test `test_scratch_ready_means_the_target_database_answers` asserts
  `"pg_isready"`, `"psql"` and `'-d "${PG_DB}"'` are **inline in the loop body**
  and that a `fail_verifier "scratch postgres did not become ready…"` guard
  precedes `pg_restore`.

Taking trunk's script while keeping the branch's test is what reds both gates.

## 3. Repair: union probe, strictly stronger than either side

`deploy/scripts/verify-restore.sh` readiness loop now requires **both** signals:

```bash
ready=0
for _ in $(seq 1 60); do
  if docker exec "${SCRATCH_NAME}" pg_isready -U "${PG_USER}" >/dev/null 2>&1 \
    && docker exec "${SCRATCH_NAME}" psql -X -q -h 127.0.0.1 -U "${PG_USER}" \
      -d "${PG_DB}" -c 'SELECT 1;' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[[ "${ready}" == 1 ]] \
  || fail_verifier "scratch postgres did not become ready with database ${PG_DB}"
```

This is the resolution shape documented in
`repair-859-vite-audit-round.md` §6. It is not a cosmetic merge: the TCP-loopback
query cannot succeed against the entrypoint's temporary server
(`listen_addresses=''`), and the target-database query cannot succeed before
init created `${PG_DB}`, so requiring both is strictly stronger than either
landed probe. Both landed tests pass on the same script.

## 4. Develop sync (the previous block)

The lane's previous block was "develop sync conflict preserved in worktree;
resolve before verification". The semantic conflict (above) is the preserved
conflict; it is now resolved in place. In addition, develop had advanced past
the merge commit's parent, so origin/develop was fetched and merged:

- `git fetch origin develop` → `252950bdbdc2332eaac10224aeae899a07763afa`
- `git merge --no-ff origin/develop` → clean (no conflicts); merge commit
  `bb93d6cd0`. The earlier textual conflict in
  `packages/maistro-canvas/pyproject.toml` (both sides `pillow>=13.0.0,<14`)
  had already been comment-unioned by `6c5663de1`.

The vulture per-identity ledger was re-derived **after** the merge with CI's
exact arguments; it matches develop and needs no amendment (see §5).

## 5. Validation executed (this tree, after the merge)

| command | result |
| --- | --- |
| `bash -n deploy/scripts/verify-restore.sh` | rc 0 |
| `uv run pytest tests/test_backup_restore_oracle.py tests/test_restore_oracle_readiness_gate.py tests/test_restore_oracle_characterization.py -q` | 25 passed |
| `TMPDIR=/home/dev/tmpx-859 RATCHET_BASE_REV=origin/develop uv run pytest tests/ --ignore=tests/tools/registry -q --timeout=60` | **5401 passed, 138 skipped** |
| `uv run pytest packages/maistro-turing/tests packages/maistro-turing/backend/tests -q --timeout=60` | 341 passed |
| `uv run pytest packages/maistro-server/tests -q --timeout=60` | 596 passed, 8 skipped |
| driver battery (ruff check/format, targeted turing pytest, both suite-inventory gates) | all rc 0 |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc 0 — 1324 reviewed identities → 1324 findings, candidate `bb93d6cd0` vs base `252950bdb` |

The docker-gated `test_real_verify_restore_drill_passes_end_to_end` and
`test_semantic_loss_is_rejected` are skipped without the restore-drill image and
were **not** run this round; the union probe is a strict superset of the probe
those cases passed against on the branch's own host (per the prior round's
note), so the residual risk is the drill itself, not the readiness predicate.

## 6. Not done / residual

- No new tests were added, so no `inventory-delta` change: the suite-inventory
  baseline and both driver inventory checks are unchanged and pass.
- The `quality/vulture-baseline.json` carried by the merge is develop's; no
  ledger rows were edited (the lane's CI-repair amendment path was unnecessary
  because the gate is green).
