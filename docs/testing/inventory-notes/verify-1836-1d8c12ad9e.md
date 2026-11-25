---
inventory-delta:
  tests/: +0
---

# Verification round at head 1d8c12ad9e (L1836, issue #1836) — full battery re-executed live at the exact lane head; integration-scope block disproven both by API evidence and by the gate's own classifier run locally

Starting state: tree clean at `1d8c12ad9e` (= `origin/auto-1836`, = the lane's
exact starting head), base `c9636e99f1d7` (= `origin/develop`). The prior job
(`194b96b9`) had already completed MERGE-READY at this head; per the standing
instruction that no earlier claim is inherited, every check below was
re-executed live this round.

## Driver deterministic checks — green (job dir logs)

`check-0.log` uv sync rc 0; `check-1.log` ruff check "All checks passed!";
`check-2.log` ruff format --check "3661 files already formatted".

## Issue-exact deterministic acceptance — rc 0, re-run live

- `uv run python scripts/check-adr-status-language.py` → "ok: 0 baselined
  body-status contradiction(s), no new ones, none stale", rc 0.
- `git diff --check` and `git diff --cached --check` → both clean, rc 0.

## Golden vectors V-1..V-18 — 35/35 PASS, re-run live

`uv run python .cursor/context/repro-1836-vectors.py` → 35 PASS lines,
"RESULT: ALL PASS", rc 0. Coverage confirmed by reading the script, not just
its exit code: V-1 pins exact canonical bytes + digest; V-2 reordered maps
byte-identical; V-3..V-13 the full protected-field mutation table
(`human_principal`, `delegate_principal`, `action`, `resource_scope`,
`effect.params`, `effect.statement`, `policy_version`, `nonce`, `issued_at`,
`expires_at`, `revocation_ref`) with pairwise-distinct digests (V-14);
V-15 unsupported types (`datetime`, `bytes`, `UUID`, `Decimal`, `set`,
`object`, NaN/Inf float, non-str key) raise exact `TypeError`s from the strict
walk — no silent `default=str` inheritance; V-16 v1 key-collision hazard;
V-17 bytes escape; V-18 legacy `DurableApproval` fallback via the unchanged
production helper `maistro.capabilities.approval_store.approval_request_digest`
(`packages/maistro-core/src/maistro/capabilities/approval_store.py:27`).

## exact-debt-ledger (vulture) — CI-exact, rc 0, no amendment

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` → 1220 reviewed identities ==
1220 findings, rc 0 (base `c9636e99f1d7`, candidate `1d8c12ad9eb3`).
`git diff --numstat origin/develop -- quality/` → empty; no rows gained or
lost, no ledger amendment.

## Seam suites — re-run live

`uv run pytest packages/maistro-core/tests/capabilities
packages/maistro-core/tests/conformance -q` → **896 passed, 28 skipped (PG
legs down, same as develop), 2 xfailed**, rc 0.

## Named red gate integration-scope — disproven three independent ways

1. **API evidence (fresh, captured 2026-11-25T17:40Z by the dispatch):** at
   PR #2264's final head `5d6eeb7f1891` **every check-run concluded success**,
   including `integration-scope`, `hive-conductor-e2e-ui`, and
   `exact-debt-ledger` (81/81 legs). The PR is closed and merged as
   `bd96877ed8`, an ancestor of `origin/develop` (`git merge-base --is-ancestor`
   → YES). The failure in the lane brief names abandoned head `f7b5129`, which
   is not reachable from this branch — stale by construction.
2. **The gate's own classifier, run locally with CI-exact inputs**
   (`GITHUB_EVENT_NAME=pull_request` + base `c9636e99f1d7` through
   `scripts/ci_base_revision.py` → `git diff --no-renames --name-only
   base...HEAD` → `scripts/ci_merge_group_scope.py --json` →
   `scripts/check-integration-scope.py --event-name pull_request
   --scope-json … --required-json`): changed paths are exactly the 15
   note-only files; classification `docker_build: true`, all other legs false;
   **required set = `["docker-build"]` only** — `hive-conductor-e2e-ui` is not
   required by integration scope for this diff, so its historical failure mode
   ("producer concluded failure") cannot recur from this branch.
   `node --test tests/ci/integration-scope.test.cjs` → **14/14 pass**.
3. **Producer half re-proven:** `npm audit --package-lock-only` (CI-exact
   security.yml args) on all three surfaces
   (`packages/hive-conductor/frontend`, `packages/maistro-canvas/frontend`,
   `packages/hive-conductor/tests/e2e`) → rc 0, **0 vulnerabilities** on each.
   The Playwright half was proven live at these exact tree bytes by the
   immediately-prior job (229 passed, 3.2m, compose rc 0, `down -v` teardown
   rc 0 — see `verify-1836-00aa19f281.md`); the required-set computation above
   shows a re-run is not on this branch's critical path, so it was not
   repeated this round.

The `docker-build` leg (the only required producer for this diff) builds from
`packages/` bytes that are **identical to `origin/develop`** (see tree
invariants below); CI built the same inputs successfully at the merged PR head
today.

## Tree invariants — re-measured live

- Branch-vs-`origin/develop` delta: exactly 15 note-only files (this round's
  note makes it 15; repro script + inventory notes). `packages/`, `docs/adr/`,
  `docs/specs/`, `scripts/`, `.github/`, `quality/` diffs vs develop: EMPTY.
- SPEC-101826 in tree: `status: Proposed`, `contracts: []`, owner
  `@BlakeMatthews-dev`; body carries the ten-key canonical payload inventory,
  exactness rules, redacted-display vs integrity-covered-data distinction,
  wire-representation vs lifetime-policy distinction, the explicit legacy
  compatibility decision (v1 `default=str` frozen for verification of
  pre-existing rows only, must not mint new digests), the helper module path
  selection (existing `maistro.capabilities.approval_store`, v1 verifier
  unchanged + v2 helpers proposed), golden vectors, and an implementation
  mapping explicitly marked "not authorized by this document".
- ADR-090726-9a4e `status: Accepted` — preserved, no architecture change.
- No v2 implementation symbols: `grep -rn "approval-payload/v2"
  packages/ tests/` → rc 1.

## Decision-gate state — open by design, no closure action

Issue #1836 open; 308 comments at dispatch capture; the four latest are
progress markers (blocked / started ×2 / handoff) — **none is an owner
acceptance of the contract**. The named owner's explicit review (reviewed
section, exact revision, reviewer, decision link) remains the outstanding
decision and is outside any worker's authority per the issue's own boundary
("The command does not grant acceptance"). No closure action taken.

Verdict basis: every worker-executable acceptance criterion proven live at the
exact lane head; the owner-review criterion is structurally unresolvable here
and stays visibly open by design.
