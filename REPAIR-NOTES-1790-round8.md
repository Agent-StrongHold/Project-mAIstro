# #1790 round 8 — independent re-verification at the round-7 head; prior finding closed

Incoming state: clean worktree at `0f2d62165f19a7d7e2baffcc41ed14ad7b7e3c09`
(= `e8b3d66f3` + suite-inventory fix `1aeac75a4` + merge of develop tip
`eeef70a2a`). `origin/develop == eeef70a2 ==` the dispatch base, so CI's default
`RATCHET_BASE_REV` resolution (`origin/develop`) names exactly the merge base.
No edits to scripts, sources, ledgers, or tests were needed this round: every
gate was re-run from scratch and all passed as found. No ledger amendment
(vulture green: 1321 == 1321).

## Prior finding (verify job 8f39ece2) — resolved, re-proven

The finding said `1790-coverage-gate-readiness-init-server-race.md` claimed
`tests/: +1` with no test behind it (expected 5634, collected 5633). Commit
`1aeac75a4` re-lands
`tests/test_backup_restore_oracle.py::test_container_readiness_probes_require_the_final_server`
and updates the note. This round:

- `uv run python scripts/check-suite-inventory.py` → ok, 21 suites match the
  recorded inventory (previously the failing gate).
- The named test exists, passes, and demonstrably catches the regressions it
  names: executed in-memory against a socket-only mutation of the
  characterisation fixture's probe (the `-h 127.0.0.1` assertion fails) and a
  `SELECT version();` mutation (the `SELECT 1` assertion fails). Positive path
  passes against the committed tree. No tree file was mutated for this check.

## The five corrections re-verified against reachable behavior

| Correction | Evidence at `0f2d62165` |
|---|---|
| 1. route-permission step runs under `uv run` | `.github/workflows/quality.yml:1092` `run: uv run python scripts/check-route-permissions.py`; the gate imports the live hive app (log shows `logging configured`) and exits 0 — the ModuleNotFoundError class is gone |
| 2. `from_legacy_dict` refactored, not granted | `radon cc packages/maistro-core/src/maistro/identity/principal.py -s`: `from_legacy_dict` A(5), no C-or-worse block in the module; `quality/radon-baseline.json` has zero principal.py entries; `uv run python scripts/check-radon-baseline.py` 129 == 129 exit 0. Narrowing behaviours pinned by 5 tests in `packages/maistro-core/tests/identity/test_principal_legacy_dict.py` (all pass) |
| 3. Ratchets cannot approve themselves | `check-principal-identity.py` resolves its tolerated ledger via `prov.resolve_baseline(BASELINE)` and loads authorizations `base=trusted_ref.base_sha` (baseline header: `base eeef70a2a935`, candidate `0f2d62165f19`); `check-ratchet-provenance.py` exit 0 with the two documented `CANDIDATE_AUTHORED` exceptions for `route-permissions.json` / `public-routes.json` present at `scripts/check-ratchet-provenance.py:141-149` |
| 4. branch-independence entries | `quality/branch-independence.json` surfaces include `principal-identity-baseline` (base_derived), `route-permissions-baseline` (base_derived), `route-permissions-registry` (specification); `check-branch-independence.py` PASS |
| 5. census sees through nested `getattr` | `_is_state_getter` / `_is_state_attr_call` in `scripts/check-principal-identity.py`; `RATCHET_BASE_REV=origin/develop uv run python scripts/check-principal-identity.py` → 4 tolerated == 4 current, 0 `state_user_access`, none new. The last live dict-shaped read (`capabilities.py`) was migrated to `request_principal`; pinned by `test_defensive_nested_getattr_user_read_is_counted` (asserts detail starts with "2 ") and the non-user-attribute control |

## Gate battery re-run this round (all exit 0)

- `uv run ruff check .` / `uv run ruff format --check .` — clean / 3405 files
- `uv run python scripts/check-suite-inventory.py` — ok, 21 suites
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-principal-identity.py` — 4 == 4, none new
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-route-permissions.py` — 41 declared, 0 undeclared
- `python3 scripts/check-public-routes.py` — 12 == 12, base-authorized
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py` — 54 consumers have provenance
- `uv run python scripts/check-radon-baseline.py` — 129 == 129
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — 1321 == 1321
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-branch-independence.py` — PASS

## Tests re-run this round (all pass)

- `tests/test_check_principal_identity.py` + `tests/test_backup_restore_oracle.py`
  + `tests/test_restore_oracle_readiness_gate.py` +
  `packages/maistro-core/tests/identity/test_principal_legacy_dict.py` — 34 passed
- `tests/test_check_route_permissions.py` + the five ratchet-provenance suites — 189 passed
- `tests/test_restore_oracle_characterization.py` (live, docker pgvector) — 4 passed
- `packages/hive-conductor/backend/tests/test_chat_voice_gates.py` — 49 passed
  (covers the `capabilities.py` `Principal` migration)

## Residual

No code changes this round, so no inventory delta beyond this note. The
"Landing order" leg (grants PR before ratchets PR) is a GitHub-side property
enforced by `load_authorizations` reading grants from the merge base; the
grants are present in the base (`ratchet-provenance` exit 0 proves the
authorization path resolves), and enqueueing stays with the merge queue
(previous block: GH006 queue position — not actionable locally, no GitHub
mutations from this lane).
