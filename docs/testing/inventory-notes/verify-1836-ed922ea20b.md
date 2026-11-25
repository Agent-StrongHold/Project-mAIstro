---
inventory-delta:
  tests/: +0
---

# Verification round at head ed922ea20b (L1836, issue #1836) — repair-phase driver checks green, full battery re-executed live

Verifier/writer round at the exact lane head `ed922ea20b3d` (clean tree at
start; branch vs `origin/develop` tip `bd96877ed8` is 8 note-only files: the
V-1..V-18 repro script under `.cursor/context/` and seven inventory notes —
zero production delta, `git diff --stat origin/develop...HEAD` lists no
`packages/` path). No file changed except this note (`tests/: +0`). Every
claim below was executed live this round, not trusted from prior rounds or
prior `result.json` artifacts.

## Driver deterministic checks (job bfcbeab7, check-0/1/2.log)

- `uv sync --locked --extra dev` rc 0; `uv run ruff check .` — "All checks
  passed!"; `uv run ruff format --check .` — "3656 files already formatted".

## Issue-exact deterministic acceptance pair

- `uv run python scripts/check-adr-status-language.py` rc 0 — "ok: 0
  baselined body-status contradiction(s), no new ones, none stale".
- `git diff --check` rc 0 (worktree) and `git diff --cached --check` rc 0
  (index).

## Contract document (the deliverable) — re-inspected live

- `docs/specs/SPEC-101826-1836-approval-payload-bytes.md`: front matter
  `status: Proposed`, `contracts: []`; payload-contract section with the
  ten-key field inventory (rows 1–10: human identity, delegate identity,
  action/capability, resource scope, effect/artifact/diff/config digests,
  policy version, nonce, issued-at, expires-at, revocation_ref); v2 recipe
  with domain-separation prefix; legacy-digest compatibility decision (v1
  frozen as legacy-row verifier, never minting; `default=str` retained for
  verification of pre-existing rows only); helper module path selection;
  golden vectors V-1…V-18; implementation mapping (proposal, not authorized).
- Accepted ADR preserved: `docs/adr/ADR-090726-9a4e-…` line 6
  `status: Accepted`; branch-vs-develop file list contains no `docs/adr/`
  or `docs/specs/` path.
- Downstream placeholder replacement present: the Implementation mapping
  names `maistro.capabilities.approval_store`,
  `GovernedInvocation` (`governed_invocation.py`), and
  `packages/maistro-core/tests/capabilities/test_durable_approval.py`.

## Helper unchanged; no implementation claimed

- `packages/maistro-core/src/maistro/capabilities/approval_store.py` —
  `approval_request_digest` unchanged (`default=str` retained as the frozen
  v1 legacy behavior the spec documents). `grep -rn
  "canonical_approval_payload_bytes\|approval_request_digest_v2" packages/
  --include="*.py"` → no matches: no v2 implementation in tree, exactly as
  the decision gate requires (it does not authorize implementation).

## Golden vectors V-1…V-18 re-executed live

- `uv run python .cursor/context/repro-1836-vectors.py` → **35/35 PASS**,
  rc 0, against the production helper (reordered maps V-2; per-field
  mutations V-3..V-13 pairwise distinct from V-1 and each other; bool/int
  and int/float byte pins V-14; eight exact TypeErrors V-15 incl. the
  non-string-key and non-finite-float rejections plus the v1 Decimal
  coercion hazard; v1 key-collision + v2 rejection V-16; ensure_ascii
  parity V-17; legacy row and `DurableApproval` fallback digest V-18).

## Seam suites

- `uv run pytest` on the 7 approval/governed-invocation/HITL suites
  (`test_durable_approval.py`, `test_durable_approval_validation.py`,
  `test_durable_hitl_approval.py`, `test_governed_invocation.py`,
  `test_governed_invocation_delegation.py`, `test_inbox_approval.py`,
  `graph/nodes/test_capability_hitl.py`) → **101 passed**, 0 failed, in
  1.74s.

## Named CI gate (integration-scope) and its root cause

- Stale gate: develop tip `bd96877ed8` (squash merge of PR #2264, the fix
  carrier) is an ancestor of this head (`git merge-base --is-ancestor` →
  true), so the board-accounting failure at `f7b5129` predates the fix this
  branch already contains.
- Root-cause leg re-proven live at this head with CI's exact invocation
  (`.github/workflows/security.yml` "JS supply chain" job):
  `npm audit --package-lock-only --json` rc 0 with **0 vulnerabilities**
  (info/low/moderate/high/critical all 0) on all three CI-exact surfaces:
  `packages/hive-conductor/frontend`, `packages/maistro-canvas/frontend`,
  `packages/hive-conductor/tests/e2e`.
- "launch/preflight: Hosted PR snapshot incomplete or not the review head"
  (previous block) is merge-queue snapshot infrastructure, not a tree
  defect: the review head must equal the committed head, which is the case
  here (`ed922ea20b3d`, clean tree). No tree change can address it.

## Ledger / inventory gates

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` rc 0 — **1221 reviewed
  identities == 1221 findings** (base `bd96877ed8cc`, candidate
  `ed922ea20b3d`); no ledger amendment needed, none made.
- `uv run python scripts/check-suite-inventory.py` rc 0 — **21/21 suites**
  match the recorded inventory; 0 redundant byte-identical groups.
- `git diff --numstat origin/develop -- quality/` → empty; no rows gained
  or lost.

## Gate status (by design, no closure action)

- SPEC-101826 remains `Proposed` with `contracts: []` and the explicit
  "This document has not been accepted" statement; owner (ADR owner
  @BlakeMatthews-dev or a designated architecture/security reviewer)
  acceptance is unrecorded — the decision gate stays visibly open, per the
  issue's own boundary ("A successful hygiene command cannot resolve the
  decision"). Issue #1836 remains open. No GitHub mutation performed.
