# Issue #1790 verification round 3 (branch `auto-1790`)

Scope frozen at dispatch: head `39994663d0df52aa672dee39bb2d7739498e9ae6`,
develop base `35a72ff54d4f09429cf0b9349ecff7f3e9396f5d` (merge base with
`origin/develop` is `420d503d4156`, which the diff gates resolve to via
three-dot). This round performed independent verification of every acceptance
criterion against reachable behavior; no production code changed.

## The five corrections, each re-proven at this head

1. **`uv run` for the app-importing step** — `.github/workflows/quality.yml:1084`
   runs `uv run python scripts/check-route-permissions.py`; the source-only
   neighbor stays bare (`python3 scripts/check-public-routes.py`,
   `ci.yml:278`). The gate itself executed here: `ok: 41 declared, 0 tolerated
   undeclared prefix(es), none new`.
2. **`from_legacy_dict` complexity** — refactor landed as module-level
   `_frozenset_str` / `_roles_from_user` / `_workspace_ids_from_user`
   (`packages/maistro-core/src/maistro/identity/principal.py`).
   `radon cc -n C` on the module prints nothing (no C-or-worse block) and no
   `quality/*.json` row mentions `from_legacy_dict` — reduction, not grant.
   Both narrowing behaviors pinned by
   `packages/maistro-core/tests/identity/test_principal_legacy_dict.py`
   (5 passed): bare string → empty set; singular `role` beats plural `roles`.
3. **No self-approval** — both tolerated ledgers resolve through
   `ratchet_provenance.resolve_baseline` (`scripts/check-principal-identity.py:293`,
   `scripts/check-route-permissions.py:251`); the route registry is likewise
   base-resolved (`:263`) with candidate additions needing base-sha
   authorizations (`new_exemptions` + `load_authorizations`) — a stronger
   mechanism than the CANDIDATE_AUTHORED exception the issue sketched.
   `scripts/check-ratchet-provenance.py` — OK, 53 consumers.
4. **Quality surfaces classified** — `quality/branch-independence.json` carries
   `principal-identity-baseline` (base_derived, :341),
   `route-permissions-baseline` (base_derived, :349),
   `route-permissions-registry` (specification, :357).
5. **Nested-getattr census** (this branch, `39994663`) — mutation re-proven
   first-hand: against the `7afbc5f17` matcher the source
   `getattr(getattr(request, 'state', None), 'user', None)` yields **0**
   violations; the current matcher yields
   `state_user_access::… 2 dict-shaped user access(es)`. So
   `test_defensive_nested_getattr_user_read_is_counted` fails against the
   regression it names. The ratchet run: `ok: 4 tolerated …, none new`
   (4→4 against base `420d503d4156`).

## Coverage gate (the red CI check) — proven green locally at this head

CI's exact gate steps, run here (Docker present, `DOCKER_HOST` set):

- Root producer, `quality.yml` argv: `coverage run --append --branch
  --source=scripts -m pytest tests/ tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py --timeout=30
  -q` → **5428 passed, 135 skipped** (10m39s).
- Backend producer after `uv pip install -r
  packages/hive-conductor/backend/requirements.txt`: `coverage run --append
  --branch --source=packages/hive-conductor/backend -m pytest
  packages/hive-conductor/backend/tests --timeout=30 -q` → **3723 passed,
  20 skipped**.
- `coverage combine` + `coverage xml`, then CI's verdict:
  `scripts/check-diff-coverage.py coverage.xml --base 35a72ff54…` → **ok**
  (2 changed measured files, 5 exempt test files). Per-file: both
  `scripts/check-principal-identity.py` and
  `packages/hive-conductor/backend/routes/capabilities.py` score **100% lines /
  100% branch arcs** over their changed lines.
- The 87% publish-set floor is computed from the seven uploaded producers'
  sources; `git diff 7afbc5f17..39994663 --name-only` shows no publish-set
  source touched (scripts/ and hive backend are diff-gate-only), so the floor
  input is identical to what CI scored **success** at `7afbc5f17` (check-run
  117784717224). The red gate finding referenced `7e86cf238`, which predates
  the readiness-probe fix `e1a71d349`.
- Restore-oracle green first-hand: `tests/test_backup_restore_oracle.py` +
  `tests/test_restore_oracle_characterization.py` → **20 passed** under Docker,
  exercising the `deploy/scripts/verify-restore.sh` probe fix.

## Production fix re-verified

`capabilities.py:resolve_approval` reads the canonical
`services.request_principal.request_principal` (the same accessor as chat/hitl);
`Principal.has_permission` subsumes the old admin-or-permission check. Focused:
`test_chat_voice_gates.py` 49 passed; the three capabilities suites 35 passed.
Suite inventories: `--suite tests` ok at 5552 (with the recorded +2 note),
`--suite packages/hive-conductor/backend/tests` ok at 3743. Ruff check/format
pass; vulture ledger `1322 -> 1322` (CI argv).

## Salvage adjudication (the "uncommitted work" block)

`scripts/check-principal-identity.py.backup` — the only untracked file — was
`cmp`-verified byte-identical to `git show
7afbc5f17:scripts/check-principal-identity.py` (the pre-change committed
version; round-2 notes said the same). It carries no unique work and was
removed; its content remains recoverable from git history at `7afbc5f17`.

## Not locally reproducible

The aggregate 87% floor over all seven producers (MinIO/Postgres/unit/archive
services). Covered by CI check-run evidence at `7afbc5f17` (success) plus the
unchanged publish-set input at this head, above.
