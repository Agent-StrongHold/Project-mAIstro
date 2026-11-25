---
inventory-delta:
  tests/: +0
---

# Verification round at head ecab6e6198 (L1836, issue #1836) — battery re-proven live after the develop-tip merge

Verifier/writer round at the exact lane head `ecab6e6198665` (worktree clean
at start and end; HEAD == `origin/auto-1836` after fetch). This head is the
merge `ecab6e6198` of the prior note-only branch content with the **new
develop tip `8955cf07a2`** (the #2304 python-base repair carrier), so every
gate was re-executed rather than inherited from the prior round's proof at
`79d59e7f27` — in particular the hive image bytes changed with the merge.
No file changed except this note (`tests/: +0`).

## Branch/review-head state (previous block resolved)

- `git fetch origin`; `git rev-parse origin/auto-1836` → `ecab6e6198665` =
  HEAD: the hosted branch **is at the review head**, so the merge-queue
  block "launch/preflight: Hosted PR snapshot incomplete or not the review
  head" has no tree residual (merge-queue snapshot infrastructure).
- `git rev-parse origin/develop` → `8955cf07a21e` = the lane base, and
  `git merge-base --is-ancestor origin/develop HEAD` → true: the sync
  already happened as merge `ecab6e6198` (parents `816393ad12` +
  `8955cf07a2`), **no conflict, nothing to resolve**.
- Branch vs develop tip `8955cf07..HEAD` = 11 note-only files (the V-1..V-18
  repro script under `.cursor/context/` + ten inventory notes), zero
  production delta; `git diff --numstat 8955cf07..HEAD -- quality/` empty
  (no rows gained or lost).

## Driver deterministic checks (job a74fa526, check-0/1/2.log)

- `uv sync --locked --extra dev` rc 0 (Resolved 460 packages); `uv run ruff
  check .` — "All checks passed!"; `uv run ruff format --check .` — "3659
  files already formatted".

## Named red gate: integration-scope / hive-conductor-e2e-ui — re-proven live at the merged head

- CI-exact invocation (ci.yml `hive-conductor-e2e-ui`, working-directory
  `packages/hive-conductor`, `MAISTRO_ROUTER_API_KEY=test-harness-not-a-real-key`):
  `docker compose -f docker-compose.test.yml --profile test up --build
  --abort-on-container-exit --exit-code-from e2e-tests e2e-tests` → images
  **rebuilt from the current head bytes** (post-merge Dockerfile: pybuild
  pinned `python:3.13.18-slim-bookworm`, runtime on `python:3.15.2-slim-bookworm`
  with the grafted venv — develop's #2304 repair state), in-image build
  smokes passed, Playwright suite **229 passed (3.2m)**, compose exit code
  **0**. CI's teardown step re-run verbatim (`down -v` with the job-level
  key set): rc 0, stack removed, worktree stayed clean at `ecab6e6198`.
- Environment deviations, recorded (unchanged from the prior round): host
  8101 still bound by the stale `rootlesskit` process (pid 1112), so the
  run added the **tracked, documented** override `-f
  docker-compose.e2e-port.yml` (host 18101:8101, `!override` tag);
  container-side healthcheck/e2e paths unaffected. Compose temp output
  redirected via `TMPDIR=/home/dev/tmp-compose` (host `/tmp` tmpfs at 88%,
  no space fault hit this round). No repo path involved.
- Root-cause leg live: `npm audit --package-lock-only --json` (CI-exact
  args from security.yml "JS supply chain") rc 0 with **0 vulnerabilities**
  on all three surfaces: `packages/hive-conductor/frontend`,
  `packages/maistro-canvas/frontend`, `packages/hive-conductor/tests/e2e`.

## Issue-exact deterministic acceptance pair

- `uv run python scripts/check-adr-status-language.py` rc 0 — "ok: 0
  baselined body-status contradiction(s), no new ones, none stale".
- `git diff --check` rc 0; `git diff --cached --check` rc 0.

## Golden vectors V-1…V-18 re-executed live

- `uv run python .cursor/context/repro-1836-vectors.py` → **35 PASS lines,
  0 FAIL**, rc 0 ("RESULT: ALL PASS") against the production helper:
  reordered maps, per-field mutations pairwise distinct, unsupported-type
  byte pins, exact TypeErrors, v1 key-collision + legacy
  `DurableApproval` fallback digest.

## Seam suites

- `uv run pytest` on the 7 approval/governed-invocation/HITL suites →
  **101 passed** (1.68s). Exact paths: `packages/maistro-core/tests/
  capabilities/test_durable_approval.py`, `…_validation.py`,
  `test_durable_hitl_approval.py` (the prior note's `…_hitl_approval.py`
  abbreviation), `…_governed_invocation.py`, `…_governed_invocation_delegation.py`,
  `…_inbox_approval.py`, `packages/maistro-core/tests/graph/nodes/
  test_capability_hitl.py`.

## Ledger / inventory gates (post-merge)

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` rc 0 — **1221 reviewed
  identities == 1221 findings** (base `8955cf07a21e`, candidate
  `ecab6e619866`); no ledger amendment needed, none made.
- `uv run python scripts/check-suite-inventory.py` rc 0 — **21/21 suites**
  match the recorded inventory (36501 collected node IDs, 0 duplicates).
- `uv run python scripts/check-image-pins.py` rc 0 — **11/11 registered**;
  newly relevant after the merge: develop's #2304 image-ledger repair
  holds at this head (independently re-proven, not trusted from the
  develop commit message).

## Contract document and no-implementation claim — re-inspected live

- `docs/specs/SPEC-101826-1836-approval-payload-bytes.md`: `status:
  Proposed` (line 6), `contracts: []` (line 20) — the decision gate stays
  visibly open by design.
- `docs/adr/ADR-090726-9a4e-crypto-bound-approvals-hybrid-webauthn-
  biscuit-hash-chain.md`: `status: Accepted` (line 6) — preserved.
- `git diff --name-only 8955cf07..HEAD -- packages/ docs/adr/ docs/specs/`
  → empty: production tree identical to the develop tip; the deliverable
  of this decision gate is the reviewed document, not code.
- `grep -rln "canonical_approval_payload_bytes\|approval_request_digest_v2"
  packages/ --include="*.py"` → rc 1, no matches: no v2 implementation in
  tree, exactly as the gate requires.

## Gate status (by design, no closure action)

- Owner acceptance remains unrecorded; issue #1836 stays open and the gate
  stays visibly open per the issue's own boundary ("A successful hygiene
  command cannot resolve the decision"). No GitHub mutation performed; no
  gate weakened.
