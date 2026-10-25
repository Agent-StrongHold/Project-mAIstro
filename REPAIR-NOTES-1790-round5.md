# #1790 round 5 — finish the preserved develop sync (fad17a87c → e20e9f52e) and re-prove all five corrections

Incoming state: the worktree carried the **preserved, unfinished merge** of
develop tip `fad17a87c` (started by a prior attempt that died on a provider
error, job `3267757de`) with exactly one unmerged path,
`deploy/scripts/verify-restore.sh`. Per the lane brief the sync was resolved in
place, then the current develop base tip `e20e9f52e` was merged on top (clean),
and every #1790 acceptance criterion was re-proved against reachable behavior
with fresh commands — none of round 4's claims assumed. No GitHub mutations;
all work committed locally on `auto-1790`.

## Merge resolutions (commits `e5d9f5f3a`, `b3c951888`)

1. **`e5d9f5f3a` — completed preserved merge of `fad17a87c`.** Develop had
   reworked `deploy/scripts/verify-restore.sh` for the #88 conductor-data
   drill (`verify_backup_manifest` / `verify_conductor_backup`, `main()`
   structure) and regressed the readiness probe to a socket `pg_isready -U`.
   Resolution: take develop's #88 structure wholesale and port this branch's
   TCP probe (`-h 127.0.0.1 -U "$PG_USER" -d "$PG_DB"`, both calls) into
   `main()`'s scratch section with the two-incident comment. Against
   `origin/develop`'s copy the file's only delta is that probe (verified by
   diff). The entrypoint's temporary bootstrap server answers socket probes
   (incidents: run 39130160694, job 117822537422), so only TCP proves the
   final server answers; `tests/test_backup_restore_oracle.py` pins exactly
   two `pg_isready -h 127.0.0.1` occurrences (holds: count == 2).
2. **`b3c951888` — merged `origin/develop` (`e20e9f52e`) on top.** Clean
   except auto-merged files; brought #1851's `runs/admission_identity.py` and
   its tests. **Ledger-merge audit (AGENTS.md rule):** the auto-merge silently
   replaced the branch-side `pydantic-declarative-field` row of
   `quality/vulture-baseline.json` with develop's copy; multiset comparison
   proved HEAD's ledger ⊇ develop's ledger and, post-merge,
   `git diff origin/develop HEAD -- quality/` is **empty** and
   `git diff origin/develop HEAD -- 'packages/*/src'` is **empty** — nothing
   lost relative to the base tip.

## Acceptance re-verification (all commands executed this round, at `b3c951888`)

| #1790 criterion | Fresh evidence |
| --- | --- |
| 1. route-permission step under `uv run` | `.github/workflows/quality.yml:1084` `run: uv run python scripts/check-route-permissions.py`; gate exit 0 (41 declared, 0 undeclared). `check-public-routes.py` stays bare `python3` (ci.yml:291, ast/json/re only), per the issue's rule |
| 2. `from_legacy_dict` refactor | `identity/principal.py:16` `_frozenset_str` names the dance once; `radon cc -n C` on the module prints nothing (no C-or-worse blocks); `check-radon-baseline.py` exit 0, 134→134; semantics pinned by `test_bare_string_yields_empty_set_not_characters` / `test_singular_role_beats_plural_roles` (in the 74 passing identity tests) |
| 3. no ratchet self-approval | `check-principal-identity.py:293` and `check-route-permissions.py:251,263` resolve tolerated ledger **and** registry through `prov.resolve_baseline` (registry base-resolved rather than `CANDIDATE_AUTHORED` — strictly stronger). In this round's `check-ratchet-provenance.py` run both scripts' trusted-base gates passed; the only failing consumer was reachability (see risks). A new violation is provably rejected: the live probe below failed with "NEW parallel principal surface absent from the trusted base and not previously authorized" |
| 4. branch-independence classifications | `quality/branch-independence.json` contains `route-permissions-registry`, `route-permissions-baseline`, `principal-identity-baseline`; `check-branch-independence.py` exit 0 |
| 5. getattr undercount fixed | `_is_state_getter` / `_is_state_attr_call` see through nested `getattr(x, "state", None)` and count `getattr/setattr/hasattr(..., "user")`; 8 scanner tests pass; **live probe**: a scratch file whose only user reads are `getattr(request.state, "user")` / nested-`getattr` shapes moved the gate 4→5 with `state_user_access` counted, FAIL exit 1 (file removed, gate back to 4 tolerated/none new); `grep 'state\.user'` over the tree shows only comments/docstrings — zero live reads |

## Battery (all exit 0 unless noted)

- `uv sync --locked --extra dev`; `uv run ruff check .`; `uv run ruff format --check .` (3363 files)
- `uv run mypy` (AGENTS.md 7-package set) — clean, 906 files
- pytest: identity/ 74✓; `tests/test_check_principal_identity.py` 8✓; `tests/test_restore_oracle_readiness_gate.py` 4✓; `tests/test_backup_restore_oracle.py` 16✓ (13 functions, 3 parametrized — file byte-identical to pre-merge head `9a61311c7`, nothing lost; round 4's "24" bundled these 16 with the scanner's 8); hive-conductor `test_chat_voice_gates.py` 49✓
- **Live characterization: `DOCKER_HOST=… uv run pytest tests/test_restore_oracle_characterization.py` — 4 passed in 11.53s** against real `pgvector/pgvector:pg17` containers, exercising the resolved drill (`test_real_verify_restore_drill_passes_end_to_end`) and the merged TCP readiness gate end-to-end
- Ratchets (`RATCHET_BASE_REV=origin/develop`): vulture (CI args `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`, 1326→1326), radon 134→134, route-permissions 41/0, principal-identity 4 tolerated/none new, public-routes 12/12, promotion-surface + its provenance, direct-effects 53 sites, shipped-surface-truth, branch-independence, suite-inventory (21 suites) — all exit 0

## Residual risks / owner-held

- **Reachability (pre-existing on develop, not this branch):**
  `check-reachability.py` and `check-ratchet-provenance.py` exit 1 on exactly
  one identity — `maistro.runs.admission_identity`, the intentionally unwired
  #1851 leaf awaiting #1845 integration. This is develop's own documented
  state: `.cursor/context/repair-1851-9ddea59d.md` (committed on develop)
  records the identical rc=1 and marks it owner-held. It cannot be
  branch-caused: `packages/*/src` is byte-identical to `origin/develop` and
  `admission_identity` is imported only by its own (unchanged, develop-side)
  test. Not banked here — the two-merge wall requires an owner-landed
  authorization, and this lane's ledger exception covers only the vulture
  ledger as instructed.
- Coverage gate not re-executed locally (needs the full multi-producer
  coverage.xml with services up); branch production lines are byte-identical
  to the develop base tip, so the publish-set floor and diff coverage over
  `packages/*/src` are unaffected by this round.
