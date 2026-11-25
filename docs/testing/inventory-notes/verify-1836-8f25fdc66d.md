---
inventory-delta:
  tests/: +0
---

# Verification round at head 8f25fdc66d (L1836, issue #1836) — review-head block resolved on fresh fetch (origin/auto-1836 == lane head); integration-scope red gate disproven at this head with CI-exact classifier inputs; full battery re-executed live, nothing inherited

Starting state: tree clean at
`8f25fdc66d467352a54c6f69e0da5799446cc4a0` (the lane's exact starting head and
the prior round's committed end head), stated develop base
`90002c42d37db3f4663fc50b6c89b977d0a53733`. No earlier claim inherited: every
acceptance check below was re-executed live this round at this head.

## Lane blocks — resolved with fresh evidence

- launch/preflight "Hosted PR snapshot incomplete or not the review head":
  after `git fetch origin`, `origin/auto-1836` == HEAD ==
  `8f25fdc66d467352a54c6f69e0da5799446cc4a0`
  (`git rev-list --left-right --count origin/auto-1836...HEAD` → `0 0`). The
  hosted snapshot now carries both prior local commits (merge `7f555bba59` +
  note `8f25fdc66d`).
- develop sync: `origin/develop` == `90002c42d37d` and
  `git merge-base --is-ancestor origin/develop HEAD` → YES — no sync conflict;
  the branch already contains the develop tip.
- Named red gate `integration-scope` (board-reported failure at superseded head
  `f7b5129e2111`): disproven at this head.
  1. Gate classifier with CI-exact pull_request inputs
     (`scripts/ci_base_revision.py` PR contract → base `90002c42d`;
     `git diff --no-renames --name-only base...HEAD` → 20 note-only paths;
     `scripts/ci_merge_group_scope.py --json` →
     `{"docker_build": true, "hive_e2e": false, ...}`;
     `scripts/check-integration-scope.py --event-name pull_request
     --required-json`) → required set exactly `["docker-build"]`:
     `hive-conductor-e2e-ui` is NOT required for this diff.
  2. `npm audit --package-lock-only --json` rc 0 with 0 vulnerabilities (all
     severities) on all three CI-exact `security.yml` surfaces:
     `packages/hive-conductor/frontend`, `packages/maistro-canvas/frontend`,
     `packages/hive-conductor/tests/e2e` — the historical root cause
     (npm-audit exit 1 inside the image build at `f7b5129`) no longer exists:
     `grep npm audit` over every hive Dockerfile → rc 1 (none found).
  3. Classifier unit tests `tests/ci/integration-scope.test.cjs` 14/14 pass.

## Driver checks — green (re-run independently)

- `uv sync --locked --extra dev` rc 0 (driver log check-0.log; env cached).
- `uv run ruff check .` → "All checks passed!" (driver check-1.log, re-run).
- `uv run ruff format --check .` → "3662 files already formatted" (driver
  check-2.log, re-run).

## Issue-exact deterministic acceptance — rc 0

- `uv run python scripts/check-adr-status-language.py` → "ok: 0 baselined
  body-status contradiction(s)" rc 0 (post-#1532 script).
- `git diff --check` rc 0; `git diff --cached --check` rc 0.

## Golden vectors V-1..V-18 — 35/35 PASS rc 0

- `.cursor/context/repro-1836-vectors.py` → "RESULT: ALL PASS" rc 0, executed
  against the production helper
  `packages/maistro-core/src/maistro/capabilities/approval_store.py`, sha256
  `99069e040861cc757dcc163c26e6bff3c9f49f5533118ee180a23bd605e6b057` —
  byte-identical to `origin/develop` (verified via
  `git show origin/develop:... | sha256sum`).
- Coverage: exact bytes+digest, reordered maps, V-3..V-13 protected-field
  mutation table pairwise distinct, V-14 bool/int + `10` vs `10.0`, V-15 exact
  TypeErrors (datetime/bytes/UUID/Decimal/set/object/non-str-key/NaN) with the
  v1 `default=str` hazard rows made explicit, V-16 v1 key collision +
  mixed-key raise, V-17 ensure_ascii pin, V-18 legacy `DurableApproval`
  fallback.

## Quality ratchets — green, no amendment

- Vulture CI-exact (`RATCHET_BASE_REV=origin/develop`,
  `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`):
  base `90002c42d37d` candidate `8f25fdc66d46`, 1220 reviewed identities ==
  1220 findings, rc 0. `git diff --numstat origin/develop -- quality/` EMPTY —
  no ledger rows added, removed, or reordered.
- Suite inventory: `scripts/check-suite-inventory.py` → "ok: 21 suite(s) match
  the recorded inventory", rc 0.

## Tree invariants

- Branch-vs-develop delta: exactly 20 note-only files (this note + 18 prior
  note files + `.cursor/context/repro-1836-vectors.py`).
  `git diff origin/develop..HEAD -- packages/ docs/adr/ docs/specs/ scripts/
  .github/ tests/` → EMPTY. No production change on this branch.
- No v2 implementation symbols: `grep -rn
  "approval_request_digest_v2|payload_bytes_v2|v2_digest" packages/*/src` →
  rc 1 (none found). SPEC-101826's implementation mapping remains marked
  "not authorized".
- SPEC-101826-1836 read in tree: `status: Proposed`, `contracts: []`,
  ten-key inventory (human identity, agent/delegate identity,
  action/capability, resource scope, effect payload covering
  artifact/diff/config digests, policy version, nonce, issued-at, expires-at,
  revocation reference), explicit v1-frozen `default=str` legacy
  compatibility decision, helper module path selection
  (`maistro.capabilities.approval_store`), golden vectors, revision history,
  `ac-state: non-measurable` decision-boundary marker preserved.
- ADR-090726-9a4e read in tree: `status: Accepted` preserved.

## Suites re-run live at this head

- `packages/maistro-core/tests/capabilities` → 846 passed, 8 skipped (PG legs
  down, same as develop).
- `packages/maistro-core/tests/conformance` → 50 passed, 20 skipped, 2 xfailed.
- ADR status-language suites (`tests/test_check_adr_status_language.py` +
  provenance) → 100 passed (includes develop's post-#1532 rewritten tests).
- Hive auth + setup suites (`test_human_auth_mode`, `test_auth_middleware`,
  `test_voice_auth`, `test_setup_first_run_questions`, `test_setup_guard`) →
  97 + 26 passed.

## Decision boundary — open by design, no closure action

Issue #1836 open; 318 captured comments, acceptance-marker regex sweep → 0
hits (latest comments are progress/handoff markers from prior jobs). The
owner's explicit acceptance of the contract + vectors (decision gate,
@BlakeMatthews-dev per issue text) is not provable from code and must stay
visibly open. SPEC-101826 stays Proposed/`contracts: []`; no closure action
taken; parent #329 untouched.
