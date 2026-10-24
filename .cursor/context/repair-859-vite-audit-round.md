# Repair #859 — `test` gate: canvas-frontend vite advisory (branch auto-859, head c630b87c2f9f)

Starting head `c630b87c2f9fc4b9eb4020e99ef57bed19d08935` (assigned), develop base
`ac1e2f9556f178fe2597927021d6218d78663101`. Worktree arrived clean; nothing from
the previous rounds was assumed — every claim below was re-derived in this tree.

## 0. What the prior round left wrong

The verify round `a20f90be` recorded MERGE-READY while CI was still queued. It was
not: `test` (check-run 118950389654) was already **red** on this exact head. CI
text was read as evidence, not as instruction:

`gh api repos/.../check-runs/118950389654/annotations` → 19 annotations, 17 of
them eslint `warning`s (pre-existing canvas/hive style warnings, unchanged by this
branch) and the two `##[error]` lines being pytest's
`PytestUnhandledThreadExceptionWarning` text, not failures. The failing step is
the last one, from the job log:

    2026-10-21T00:11:18 ##[group]Run npm audit --audit-level=high   # packages/maistro-canvas/frontend
    vite  8.0.0 - 8.1.5   Severity: high
    launch-editor: escapeCmdArgs() omits % escaping on Windows  GHSA-698v-4r3x-3vcv
    launch-editor: Editor CLI flag misinterpretation ...         GHSA-r825-w8mm-5pxw
    launch-editor: `fs.existsSync()` existence check bypassed ... GHSA-587h-7wmj-h5pm
    ##[error]Process completed with exit code 1.

Because GHA steps abort the job, every earlier step in `test` (server, both Turing
suites, design, ext-harness, ext-sdk, root `tests/`, both frontends, generated
types, hive backend) had already passed in that run.

## 1. Root cause is a stale lock, not the #859 change

`packages/maistro-canvas/frontend/package.json` still pinned `vite: ^8.0.10` and
`package-lock.json` resolved **8.1.5**, the last vulnerable release. The
advisories landed against a `launch-editor` sub-dependency after this branch's
last sync, so an *unchanged* tree turned red — the same shape as the pigeonhole
of the previous round's pillow/certifi fix.

## 2. Repair: mirror what `origin/develop` already ships

`git show origin/develop:packages/maistro-canvas/frontend/package.json` already
pins `vite: ^8.1.6` and its lock resolves 8.3.4. Copied by regeneration, not by
hand:

    packages/maistro-canvas/frontend$ npm install --package-lock-only  # → vite 8.3.4, "found 0 vulnerabilities"
    $ git diff --stat origin/develop -- package.json package-lock.json
    (empty)  # both files are now byte-identical to origin/develop

No new pin was invented and no advisory was suppressed.

## 3. Local evidence (CI's exact commands, CI's order)

| step | command | result |
| --- | --- | --- |
| audit (was red) | `npm audit --audit-level=high` | rc 0, `found 0 vulnerabilities` |
| lock consistency | `npm ci` | 287 packages, 0 vulnerabilities |
| canvas tests | `npm run test:ci` | 5 files / 79 tests passed |
| canvas lint | `npm run lint` | rc 0 (0 errors, 13 pre-existing warnings) |
| canvas build | `npm run build` | rc 0, `✓ built` |
| root suite | `pytest tests/ --ignore=tests/tools/registry` | 5397 passed, 138 skipped |
| server | `pytest packages/maistro-server/tests` | 591 passed |
| design / ext-harness / ext-sdk | per-suite | 575 / 273 / 147 passed |
| hive backend | `pytest packages/hive-conductor/backend/tests` | 3791 passed |
| cross-suite leakage | `pytest tests/ hive/backend/tests design/tests --timeout=60` | 9856 passed, 0 errors |
| inventory | `python scripts/check-suite-inventory.py` | ok, 21 suites, 32493 node IDs |
| duplicates | `python scripts/check-test-duplicates.py` | ok, 1639 files |

The two local runs that reported 3 failed / 4480 errors were a **local
environment artefact, not a code finding**: this box's `/tmp` tmpfs was at
100 % of its 1 Mi inodes (`df -i /tmp` → `IUsed 1048575`), so pytest's
`tmp_path` factory and `mkstemp` failed. Re-running the identical command with
`TMPDIR` on the root filesystem produced the clean 9856-passed result above.
`/tmp` was left untouched — other lanes' artefacts live there.

## 4. Deliberately not done this round

`origin/develop` is 8 commits ahead (131 files) — including gate definitions,
`quality/vulture-baseline.json` (two `personas/store.py::get_for_workspace` rows
this branch still banks and develop no longer needs), `uv.lock`, and
`deploy/scripts/verify-restore.sh`. That is a **merge-time** integration risk,
not the cause of the named gate failure; a sync is proposed as its own round so
this repair stays reviewable as one audit fix. See the round's final report.

## 5. Verification of the #859 acceptance surface (independent re-derivation)

Re-run at head `399f9824e` rather than trusting the prior verify round:

| Criterion | Production evidence | Test evidence |
|---|---|---|
| Scoped self-model keying/authz | `state.py::_require_scope`, `WorkspaceSelfModelState`, `execution.py::scope_for` (deterministic `uuid5` from `user_id`); routes resolve via `get_execution_plane().scope_for(user.user_id)` | `test_scope_isolation.py::{test_two_users_have_isolated_self_model_snapshots, test_admin_facet_patch_cannot_reach_another_users_scope}`, `test_state_scoping.py::{test_self_model_state_is_scoped_per_principal, test_self_model_state_requires_an_explicit_principal_scope}` |
| Bounded chat state (ownership + lifetime + cardinality) | `ChatSessionRegistry` keyed by `(workspace_id, session_id)`, `MAX_CHAT_SESSIONS=256`, `CHAT_SESSION_TTL_SECONDS=3600`, `MAX_SESSION_ID_CHARS=128`, per-partition LRU | `test_state_scoping.py::{test_chat_session_registry_is_bounded_by_capacity, test_chat_session_eviction_never_crosses_workspaces, test_chat_session_registry_lru_order_survives_timestamp_ties, test_chat_session_registry_expires_idle_sessions}`, `test_scope_isolation.py::test_guessed_session_id_cannot_attach_to_another_users_session` |
| Single validated mutation path with clamps | `TuringState.set_mood` / `set_facet` — `Mood` constructor is the range authority; candidate validated before any scope is materialized (`test_state_scoping.py::test_rejected_writes_do_not_install_a_scope_for_an_unseen_principal`) | `test_state_scoping.py::{test_set_mood_rejects_out_of_range_values_at_the_seam_without_mutating, test_set_facet_rejects_out_of_range_and_unknown_facets_at_the_seam}` |
| Exact actor/Workspace provenance, no process-global fallback | no global self model exists; `LookupError` on empty scope | `test_state_scoping.py::test_self_model_state_requires_an_explicit_principal_scope` |
| Restart semantics durable vs ephemeral | `SelfModelStateStore` protocol + `is_shared_across_replicas` declaration; `_guard_replica_authority` refuses unshared stores as replica authority | `test_scope_isolation.py` restart/replica block (ephemeral store loses state; a `is_shared_across_replicas=True` store survives a new `TuringState`; an arbitrary injected store is not treated as replica-safe) |
| Isolation tests present | — | `test_scope_isolation.py` (two users / two Workspaces, admin cannot cross) |

Executed: `uv run pytest packages/maistro-turing/tests packages/maistro-turing/backend/tests -q` → **341 passed**. `npm audit --audit-level=high` at head → `found 0 vulnerabilities`; frontend `package.json`/`package-lock.json` are byte-identical to `origin/develop`.

## 6. Develop-sync conflict analysis (for the next round, do not redo)

A trial merge of `origin/develop` into this branch (scratch worktree, aborted afterwards) resolves 129/131 files cleanly and conflicts in two:

1. `deploy/scripts/verify-restore.sh` — **semantic**, not just textual. This branch waits for readiness with a TCP-loopback `psql -d "${PG_DB}" -c 'SELECT 1'` in a `scratch_ready()` helper (temporary init server sets `listen_addresses=''`, so socket probes false-positive). Develop landed a different fix to the same race: `pg_isready` **and** `psql -d "${PG_DB}"`, both over the socket, inline in the 60-try loop — plus its own test `tests/test_backup_restore_oracle.py::test_scratch_ready_means_the_target_database_answers`, which asserts `"pg_isready" in loop_body` and `'-d "${PG_DB}"' in loop_body`. This branch's `test_scratch_readiness_probes_final_server_and_target_db` asserts `-h 127.0.0.1` and `SELECT 1` in the script. Each landed test fails against the other's script, so a plain "keep ours" or "keep theirs" breaks a just-landed gate.
   Resolution that satisfies both suites (union probe, strictly stronger): inside the loop require `docker exec … pg_isready -U "${PG_USER}"` **and** `docker exec … psql -X -q -h 127.0.0.1 -U "${PG_USER}" -d "${PG_DB}" -c 'SELECT 1;'`, keeping this branch's `ready=0`/`[[ "${ready}" == 1 ]] || fail_verifier "scratch postgres did not become ready"` shape. Then re-run `tests/test_backup_restore_oracle.py`, `tests/test_restore_oracle_characterization.py`, `tests/test_restore_oracle_readiness_gate.py`, `bash -n deploy/scripts/verify-restore.sh`, and the docker e2e restore drill.
2. `packages/maistro-canvas/pyproject.toml` — both sides landed `pillow>=13.0.0,<14`; this branch adds a CVE comment. Comment-union resolution, no semantic change.

Also inherited at merge time (mechanical, no conflict): `quality/vulture-baseline.json` — this branch banks 2 rows develop no longer needs (`personas/store.py::unused method 'get_for_workspace'` ×2) while develop adds 14 `quality/durable-table-retention.json` rows; plus develop's `scripts/check-reachability.py` exclusion and `.github/workflows/{ci,quality}.yml` changes. Re-derive the vulture ledger after the merge with the CI-exact command; never `set()` the multiset.
