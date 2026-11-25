---
inventory-delta:
  tests/: +0
---

# Verification round at head bd2c40a21d (L1836, issue #1836) — driver checks green, full battery re-executed live

Verifier/writer round at the exact lane head `bd2c40a21d6d` (clean tree; branch
vs `origin/develop` tip `bd96877ed8` is 7 note-only files: the V-1..V-18 repro
script under `.cursor/context/` and six inventory notes — zero production
delta, `git diff --stat origin/develop..HEAD -- packages/` empty). No file
changed except this note (`tests/: +0`). Every claim below was executed live
this round, not trusted from prior rounds or from PR history.

## Driver deterministic checks (job 4ad856b1, check-0/1/2.log)

- `uv sync --locked --extra dev` rc 0; `uv run ruff check .` — "All checks
  passed!"; `uv run ruff format --check .` — "3656 files already formatted".

## Issue-exact deterministic acceptance pair

- `uv run python scripts/check-adr-status-language.py` rc 0 — "ok: 0
  baselined body-status contradiction(s), no new ones, none stale".
- `git diff --check` rc 0 (worktree) and `git diff --cached --check` rc 0
  (index).

## Contract document (the deliverable)

- `docs/specs/SPEC-101826-1836-approval-payload-bytes.md` present: front
  matter `status: Proposed`, `contracts: []`; payload-contract section with
  the ten-key field inventory (rows 1–10 covering human identity, delegate
  identity, action/capability, resource scope, effect/artifact/diff/config
  digests, policy version, nonce, issued-at, expires-at, revocation_ref);
  v2 canonical-bytes recipe with domain-separation prefix; legacy-digest
  compatibility decision (v1 frozen as legacy-row verifier, never minting);
  helper module path selection; golden vectors; implementation mapping.
- Accepted ADR preserved: `docs/adr/ADR-090726-9a4e-…` line 6
  `status: Accepted`; `git diff origin/develop..HEAD -- docs/adr/` empty.

## Helper unchanged; no implementation claimed

- `packages/maistro-core/src/maistro/capabilities/approval_store.py` —
  `approval_request_digest` unchanged (`default=str` retained, documented in
  the spec as the frozen v1 legacy behavior). `packages/` diff vs develop
  empty.
- No v2 symbols in the production tree: `grep -rn
  "canonical_approval_payload_bytes\|approval_request_digest_v2"
  packages/*/src/` → no matches (rc 1). The spec *selects* these names;
  implementation is explicitly not authorized by this decision gate.

## Golden vectors V-1…V-18 re-executed live

- `uv run python .cursor/context/repro-1836-vectors.py` → **35/35 PASS**,
  rc 0, against the production helper (reordered maps V-2; per-field
  mutations V-3..V-13 pairwise distinct; bool/int byte pins V-14; eight
  exact TypeErrors V-15; v1 key-coercion collision + v2 rejection V-16;
  ensure_ascii escape parity V-17; legacy row + `DurableApproval` fallback
  digest V-18). Ad-hoc probe: v1 digest stable under key reorder
  (`d6e63b7ab811ba1a…`), exact reproduction of the frozen legacy binding.

## Seam suites

- `uv run pytest` on the 7 approval/governed-invocation/HITL suites
  (`test_durable_approval.py`, `test_durable_approval_validation.py`,
  `test_durable_hitl_approval.py`, `test_governed_invocation.py`,
  `test_governed_invocation_delegation.py`, `test_inbox_approval.py`,
  `graph/nodes/test_capability_hitl.py`) → **101 passed**, 0 failed.

## Named CI gate (integration-scope)

- Stale: develop tip `bd96877ed8` (squash merge of PR #2264) is an ancestor
  of this head (`git merge-base --is-ancestor` → true), so the board
  accounting failure at `f7b5129` predates the fix already carried here.
- Root-cause leg re-proven live at this head: `npm audit --package-lock-only
  --json` rc 0 with **0 vulnerabilities** on all three CI-exact surfaces
  (`packages/hive-conductor/frontend`, `packages/maistro-canvas/frontend`,
  `packages/hive-conductor/tests/e2e`).

## Ledger / inventory gates

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` rc 0 — **1221 == 1221**
  (base `bd96877ed8cc`, candidate `bd2c40a21d6d`); no ledger amendment
  needed, none made.
- `uv run python scripts/check-suite-inventory.py` rc 0 — **21/21 suites**
  match the recorded inventory.
- `git diff --numstat origin/develop -- quality/` → empty; no rows gained
  or lost.

## Gate status (by design, no closure action)

- SPEC-101826 remains `Proposed` with `contracts: []` and an explicit
  "has not been accepted" statement; owner (ADR owner
  @BlakeMatthews-dev / designated reviewer) acceptance is unrecorded — the
  decision gate stays visibly open, per the issue's own boundary ("A
  successful hygiene command cannot resolve the decision"). Issue #1836
  remains open. No GitHub mutation performed.
