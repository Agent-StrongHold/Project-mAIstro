# Issue #1790 repair checkpoint (round 2, branch `auto-1790`)

Frozen scope: issue #1790 lane, branch `auto-1790`, supplied head
`7afbc5f174512e8c2176fa25f11dc3107ab1c30e`, develop base
`35a72ff54d4f09429cf0b9349ecff7f3e9396f5d`. Incoming uncommitted salvage from
the rejected verify round was preserved first
(`/home/dev/maistro/jobs/10160776543e4f7885eef41605e076a7/incoming-salvage-1790.patch`)
and then adjudicated piece by piece; nothing was wiped.

## Salvage adjudication (three pieces)

1. **`_is_state_attr_call` nested-getattr fix — KEPT, rewritten.** The idea is
   correction 5 of the issue: the census must see through
   `getattr(getattr(request, "state", None), "user", None)`. The salvage's
   version was one-level-only and unformatted; replaced with a `_is_state_getter`
   helper that accepts `x.state` as an attribute or a defensive `getattr` call at
   any depth.
2. **Baseline row for `capabilities.py` — REJECTED.** Adding
   `state_user_access::packages/hive-conductor/backend/routes/capabilities.py`
   to `quality/principal-identity-baseline.json` creates new tolerated debt; the
   `principal-identity` grants at the merge base (`420d503d4156`) do not cover
   that identity, and a grant added on this branch cannot authorize it
   (authorizations are read from the base, #534 two-merge rule). The row was
   removed; the debt is fixed instead (below), so the candidate ledger keeps its
   4 trusted-base entries and the ratchet passes as `4 -> 4, none new`.
3. **`#!/usr/bin/env uv run python3` shebang — REJECTED.** Not a valid Linux
   shebang (`env` would receive `uv run python3` as a single argument), and the
   correction-1 fix lives in the workflow step, which already reads
   `run: uv run python scripts/check-route-permissions.py`
   (`.github/workflows/quality.yml:1084`, landed with the #1805 re-land on
   develop). The script's docstring documents the same invocation. Shebang
   reverted to `#!/usr/bin/env python3`.

`scripts/check-principal-identity.py.backup` (untracked, left in place) is
byte-identical to the committed pre-change script (`cmp` against
`git show HEAD:scripts/check-principal-identity.py`) — it carries no unique
work.

## New evidence found by the widened census

AuthMiddleware stopped writing `request.state.user` when it migrated to
`request.state.principal` (`packages/hive-conductor/backend/middleware/auth.py`
has no `state.user` writer). `capabilities.py:290` still read the dict-shaped
`state.user` through the invisible nested `getattr`, so in production the read
resolved to `{}` and `resolve_approval` raised 401 on **every real HTTP
approval**; only direct provider tests that faked `state.user` worked. The
ratchet certifying that file clean was exactly the failure mode correction 5
describes.

Fix: `resolve_approval` now reads the canonical
`services.request_principal.request_principal` (same accessor as chat, hitl,
feedback), with `Principal.has_permission` subsuming the old
`role == "admin" or principal_has_permission(user, ...)` check. The two
`test_chat_voice_gates.py` tests that faked the dict now stamp a real
`Principal`; admin-approve and config-editor-403 semantics unchanged. Two new
scanner unit tests pin the nested-getattr census (+2 in `tests/`, delta recorded
in `docs/testing/inventory-notes/1790-nested-getattr-principal-reads.md`); the
first test was proven to fail against the pre-fix matcher before the fix was
applied.

## Validation executed (all at the post-fix tree)

- `uv run ruff check .` / `uv run ruff format --check .` — pass (3324 files).
- `uv run python scripts/check-principal-identity.py` —
  `ok: 4 tolerated principal-identity violation(s), none new`.
- `uv run python scripts/check-route-permissions.py` —
  `ok: 41 declared, 0 tolerated undeclared prefix(es), none new`.
- `uv run python scripts/check-ratchet-provenance.py` — OK, 53 consumers.
- Focused: `tests/test_check_principal_identity.py` +
  `packages/maistro-core/tests/identity/test_principal_legacy_dict.py` 13
  passed; `test_capabilities_routes.py` 10 passed;
  `test_chat_voice_gates.py` 49 passed; `tests/test_ratchet_provenance.py`
  67 passed; `tests/test_backup_restore_oracle.py` 16 passed;
  `tests/test_restore_oracle_characterization.py` 4 passed under Docker
  (pgvector/pg17).
- Coverage-gate producers, CI's exact argv: root producer
  (`coverage run --branch --source=scripts -m pytest tests/
  tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py`)
  **5427 passed, 136 skipped** in 10m40s — this is the producer whose
  restore-oracle fixture raced the pgvector temp→final server restart and red
  the gate at `7e86cf238`; the readiness-probe fix (`e1a71d349`) plus Docker
  present makes it green here. Backend producer
  (`--source=packages/hive-conductor/backend`) **3723 passed, 20 skipped**.
- `uv run python scripts/check-suite-inventory.py --suite tests` — ok at 5552
  with the recorded +2 note; `--suite packages/hive-conductor/backend/tests` —
  ok at 3743.
- Mutation check: old (HEAD) matcher misses the nested source, new matcher
  reports `2 dict-shaped user access(es)` — the new test fails against the
  regression it names.
- `scripts/check-diff-coverage.py coverage.xml --base 35a72ff…` — after commit,
  scores the two newly-changed measured files (`scripts/check-principal-identity.py`,
  `packages/hive-conductor/backend/routes/capabilities.py`) from the combined
  two-producer data; result recorded in the final report.

Not locally reproducible: the 87% publish-set aggregate floor needs all seven
producers (MinIO/Postgres/server/design/registry/ext jobs). CI evidence: at
`7afbc5f17` every coverage producer and the gate itself were green (dispatch
check-runs); this change only adds exercised lines to two measured files and
touching no publish-set source.
