# REPAIR-NOTES-1837 — develop sync 4019249e8 + `test:` gate revalidation (round 3)

Lane L1837 (issue #1837, Decision: Select WebAuthn verification adapter).
Incoming lane block: CI `test: failure` on the merge-queue evaluation, with
PR #2268 at `mergeable_state: dirty` — origin/develop had advanced two commits
(`8edb51fb9` builders domain helpers, `4019249e8` design.orchestrate connect +
vulture prune) past this branch's last sync point (`26879956a`, which merged
`09d56b6a0`).

## What this round did

1. **Sync.** `git merge origin/develop` → clean auto-merge, commit `d24d876da`.
   No textual conflicts. develop's 11-file diff (builders/design source +
   tests, `quality/vulture-baseline.json` −37 rows,
   `quality/reachability-*.json` −5/−25 rows, two new inventory notes) landed
   wholesale; this branch had never touched any of those paths, and the
   post-merge row check confirms it:
   `git diff --numstat origin/develop HEAD -- quality/` → empty (no silently
   dropped ledger rows — the multiset loss mode AGENTS.md warns about).
2. **Revalidation on the merged head.** Every gate re-run; nothing assumed
   from prior rounds.

## Evidence (merged head d24d876da)

Issue deterministic acceptance (`uv run python scripts/check-adr-status-language.py && git diff --check`):

- `ok: 0 baselined body-status contradiction(s), no new ones, none stale`; `git diff --check` clean → HYGIENE OK
- `scripts/check-adr-index.py` → `OK: every ADR-INDEX row agrees with its ADR's front matter`

ADR-101826-c3f1 completeness vs #1837's deterministic criterion — all present
in the reviewed document: library source (`duo-labs/py_webauthn` @ `webauthn`
3.0.1, wheel sha256 recorded), permitted algorithms (ES256 required, EdDSA /
RS256 permitted, PSS/SHA-1/ML-DSA explicitly excluded), required flags (UP+UV
forced by the adapter, sign-counter monotonicity, fail-closed exception
mapping), valid registration + valid assertion vectors and six invalid
mutation vectors (I1–I6) with observed refusals, dependency owner
(@BlakeMatthews-dev), exact module path
(`packages/maistro-core/src/maistro/capabilities/webauthn.py`), ADR-039 §3
maintainer-signal rationale, and the typosquat note distinguishing
`py-webauthn` from `webauthn`.

Quality ratchets (CI-exact arguments, base resolves to origin/develop):

- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → 1256 reviewed == 1256 findings
- `check-radon-baseline.py` → 127 == 127
- `check-promotion-surface.py` → ok
- `check-reachability.py` / `check-reachability-dispositions.py` → 104 unreachable, 37 groups, all dispositioned
- `check-ratchet-provenance.py` → 0 lifecycle violations
- `check-shipped-surface-truth.py` → matrix complete

Suite inventory: `check-suite-inventory.py` → 21/21 suites ok, 34693 unique
identities, 0 duplicates (develop's `cursor-m1-*` notes arrived with the merge,
so no new note was needed and none was added — no tests were added this round).

Lint: `ruff check .` clean; `ruff format --check .` 3529 files formatted.

CI `test:` job, every pytest step re-run locally on the merged head:

| step | result |
|---|---|
| maistro-server/tests | 646 passed, 10 skipped |
| maistro-turing/tests + backend/tests | 350 passed |
| maistro-design/tests | 662 passed, 1 skipped |
| maistro-ext-harness/tests | 273 passed |
| maistro-ext-sdk/tests | 147 passed |
| tests/ --ignore=tests/tools/registry | 5802 passed, 139 skipped |
| hive-conductor/backend/tests | 4062 passed, 29 skipped |
| cross-suite leakage (tests/ + hive backend + design, one process) | 10619 passed, 169 skipped |
| tests/test_check_image_lock_reconciliation.py (branch-owned change) | 76 passed |
| maistro-core/tests/builders/test_pipeline_spec_flow.py (merge-carried) | 15 passed |

Frontend npm steps: `git diff --name-only origin/develop..HEAD` contains no
frontend/package-lock/package.json paths — content-identical to develop's own
green run of those steps.

rsi note (carried from round 2): `test_real_container_runs_the_vector_and_returns_its_status`
is docker-gated and lives in the `coverage (no services)` producer, not the
`test` job; its scratch-env failure (pytest missing inside the builder image)
is an environment artifact, not reachable `test:` behavior.

## Still open by design (not resolvable by this lane)

Owner acceptance of ADR-101826-c3f1. #1837's Decision boundary reserves it to
@BlakeMatthews-dev (or a designated architecture/security reviewer); the
document stays `Proposed`, the dependency stays uninstalled, and the issue
stays visibly open until that human record exists. The ADR's "Acceptance
boundary" section states this verbatim.
