# #1790 round 4 — develop sync resolution + full acceptance re-verification

Incoming state: the worktree carried a **preserved, unfinished merge** of
origin/develop (MERGE_HEAD `64ea662cb`) with exactly one unmerged path,
`tests/test_restore_oracle_characterization.py`. Per the lane brief the sync
was resolved in place, the develop tip was merged on top, and every #1790
acceptance criterion was re-checked against reachable behavior. No GitHub
mutations; all work committed locally on `auto-1790`.

## Merge resolution (commits `d07c1a8a5`, `a5ac62379`)

Both sides had fixed the same readiness race differently:

- **auto-1790 (`e1a71d349`)**: probe over TCP (`-h 127.0.0.1`) because the
  docker-entrypoint's *temporary bootstrap server* answers socket queries —
  even authenticated `SELECT 1`s for the target DB once `docker_setup_db` has
  run — while it never listens on TCP (coverage-gate root producer, run
  39130160694).
- **develop (`64ea662cb`)**: socket probe requiring a `SELECT 1` round-trip,
  plus bounded `_READY_TIMEOUT_S`/`_READY_POLL_S` constants, deadline loop and
  stderr-tail failure, pinned by the new stub-docker suite
  `tests/test_restore_oracle_readiness_gate.py`.

Develop's socket probe still false-positives in the temp-server window, so the
resolution keeps **both**: develop's bounded gate structure (constants,
deadline, stderr tail — required by its stub tests) and this branch's TCP
flag, with a comment recording both incidents. The probe uses develop's
semicolon-free `SELECT 1` because the stub gate pins
`call[call.index("-c") + 1] == "SELECT 1"` exactly.

Two follow-ups fell out of the reconciliation:

1. `tests/test_restore_oracle_readiness_gate.py` — the structural test now
   also asserts every probe targets `-h 127.0.0.1`, so a future develop sync
   cannot silently drop the TCP half again (that is exactly how this conflict
   was born). Proven load-bearing: removing the pair makes
   `test_every_probe_is_select_1_against_the_target_database` fail with
   `ValueError: '-h' is not in list`; restored, 4/4 pass.
2. `tests/test_backup_restore_oracle.py::test_container_readiness_probes_require_the_final_server`
   pinned the pre-merge helper's byte shapes
   (`"-h",\n            "127.0.0.1",` and `"-c",\n            "SELECT 1;"`),
   which **cannot coexist** with the stub gate's argv-equality pin. The source
   pin was updated to the merged probe shape (TCP pair kept, semicolon-free
   `SELECT 1`); `-h` occurs exactly once in the characterization module, so
   the pin stays unambiguous. Count deltas: none (both files keep their test
   counts; `tests` suite inventory passes).

## Acceptance re-verification (all against `a5ac62379` + this round's edits)

| #1790 criterion | Evidence (executed this round) |
| --- | --- |
| 1. route-permission step under `uv run` | `.github/workflows/quality.yml:1084` `uv run python scripts/check-route-permissions.py`; bare `python3` only for the two ast/json/re scanners (`ci.yml:291`, `quality.yml:1123`), matching the issue's rule |
| 2. `from_legacy_dict` refactor | `identity/principal.py` names the dance once (`_frozenset_str`); radon: `from_legacy_dict` **A(5)**, module has no C-or-worse block; `check-radon-baseline.py` (RATCHET_BASE_REV=origin/develop) exit 0, 134→134; narrowing behaviors pinned by 74 identity tests + live probes (bare string → empty set; singular `role` beats plural) |
| 3. no ratchet self-approval | both `check-principal-identity.py` and `check-route-permissions.py` resolve tolerated ledger **and** registry via `prov.resolve_baseline`; new prefixes/exemptions need authorizations landed at the base; `check-ratchet-provenance.py` exit 0 ("53 quality JSON consumer(s) have explicit provenance") — note: the re-land base-resolves the registries rather than adding `CANDIDATE_AUTHORED` rows; strictly stronger (registry edits still cannot mint tolerated debt), accepted as satisfying the criterion's substance |
| 4. branch-independence classifications | `quality/branch-independence.json` has `route-permissions-registry` (specification), `route-permissions-baseline` (base_derived), `principal-identity-baseline` (base_derived); `check-branch-independence.py` exit 0 |
| 5. getattr undercount fixed | `_is_state_getter`/`_is_state_attr_call` see through `getattr(request, "state", None)` and count `getattr/setattr/hasattr(..., "user")`; 8 unit tests pass; live probes confirm all four shapes; tree has zero remaining `state.user` reads (last one migrated in `capabilities.py` to `request_principal`); gate exit 0 with 4 tolerated class-shape violations, none new |

## Battery (all exit 0 unless noted)

- `uv run ruff check .` / `uv run ruff format --check .`
- `uv run mypy` (AGENTS.md package set) — clean after `uv sync --locked --all-extras` (base-deps-only venv produces import-not-found noise; AGENTS.md documents this)
- `RATCHET_BASE_REV=origin/develop` ratchets: vulture (CI args: `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`, 1321→1321), radon, route-permissions (41 declared, 0 undeclared), principal-identity, public-routes, ratchet-provenance, branch-independence
- pytest: identity/ 74✓; `tests/test_check_principal_identity.py` 8✓; `tests/test_backup_restore_oracle.py` 24✓ (after pin reconciliation); `tests/test_restore_oracle_readiness_gate.py` 4✓; hive-conductor design/voice suites 89✓+4 skipped; durable_runs 710✓+63 skipped+4 xfail
- **Live characterization: `DOCKER_HOST=… uv run pytest tests/test_restore_oracle_characterization.py` — 4 passed in 11.37s** against real `pgvector/pgvector:pg17` containers, exercising the merged TCP+deadline readiness gate end-to-end
- `check-suite-inventory.py` for `tests`, `packages/maistro-core/tests`, `packages/hive-conductor/backend/tests` — all match recorded inventory

Coverage gate not re-executed locally (needs the full multi-producer
coverage.xml with services up). Round 3 proved it green at `39994663`; since
then the branch only absorbed origin/develop's own green content plus
test/doc edits — `git diff origin/develop...HEAD -- 'packages/*/src'` is
empty, so the publish-set floor and diff coverage over branch production
lines are unaffected by this round.

## Residual risks

- The `_uses_trusted_resolver` whitelist is script-granular: a *future* edit
  could add an unresolved ledger read to an already-resolving script and pass
  the inventory. Not this issue's regression; noting for gate owners.
- Live characterization depends on Docker; CI `test` job remains the
  authoritative runner for it.
