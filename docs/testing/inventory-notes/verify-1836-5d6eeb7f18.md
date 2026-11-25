---
inventory-delta:
  tests/: +0
---

# Verification round at head 5d6eeb7f18 (L1836, issue #1836) — note-only

Round at the assigned head
`5d6eeb7f1891a731b35ad70284d4e1573954841f` — the develop sync merge
(d5eea94329, "bump actions/download-artifact 7→8") on top of the last fully
proven round `0e99dc24a4`/`2101fc9525`. The merge diff
(`git diff 2101fc9525..HEAD --stat`) touches only
`docs/issues/issue-2372-repair-gitleaks-public-routes.md`,
`.github/workflows/mutation-nightly.yml`, `.gitleaksignore`,
`quality/public-routes.json`, and this branch's own verify note — **no
runtime code, no hive-conductor code, no e2e specs** — so the heavy
producer evidence carries over; nevertheless every claim below was
re-executed live at this head. No test files added or changed (`tests/: +0`).

## The named red gate — integration-scope

Root cause of the historical failure (head `f7b5129e2`, CI job
133440583445) was hive-conductor-e2e-ui dying on npm audit minimatch
findings; the in-tree fix (typescript-eslint 8.74.0 in
`packages/hive-conductor/frontend/package-lock.json`, commit `1c29c03bad`)
is re-proven at this head with CI-exact arguments:
`npm audit --package-lock-only --json` for all three CI surfaces
(hive-conductor/frontend, maistro-canvas/frontend, hive-conductor/tests/e2e)
— **rc 0, 0 vulnerabilities at every severity, all three**.

Captured CI check-runs at this exact head (dispatch context,
2026-11-25T10:28Z): every completed leg is `success` — including
exact-debt-ledger, DevSkim, Analyze (actions / javascript-typescript /
python), JS supply chain, Mutation gate, workflow-lint, SAST triplet,
hive-conductor-compose-durability, postgres pg17/pg18, wheel-imports — and
the previously named legs (`integration-scope`, `hive-conductor-e2e-ui`,
`hive-conductor-e2e`, `docker-build`) were still `in_progress` at capture
time with **no failure recorded anywhere at this head**. The aggregator
gives evidence 240 minutes; the capture window predates its conclusion, so
"integration-scope: failure" from the last merge-queue evaluation maps to
the pre-repair head, not this one.

Producer carry-over soundness: `git diff 2101fc9525..HEAD` contains none of
the paths the four scope-required producers execute. Prior round's local
re-execution (e2e 229 passed / 3.3m, api-tests 14 passed 14 skipped,
wheel-imports 12 wheels rc 0, docker-build every step rc 0 incl. #406
probes and dual-builder canary) therefore carries over verbatim.
Merge-base check: `git merge-base HEAD d5eea94329` == `d5eea94329` — the
branch contains the develop base; no conflict remains.

## Deterministic acceptance of decision gate #1836

- `uv run python scripts/check-adr-status-language.py` rc 0 ("0 baselined
  body-status contradiction(s)"); `git diff --check` rc 0 — the issue's
  exact command pair.
- Golden vectors **V-1 … V-18 re-executed live against this tree**, all
  pass byte-exact: V-1 bytes+digest (`v2:8db816aa…`), V-2 reordered maps
  byte-identical, V-3…V-13 one mutation per protected field (all digests
  distinct from V-1 and each other), V-14 true≠1 / 10≠10.0, V-15 rejection
  table (datetime, bytes, UUID, Decimal, set, object, non-str key, NaN —
  each `TypeError` names the offending path), V-16 v1 `{1:}`/`{"1":}`
  collision demonstrated on the production helper, V-17 ensure_ascii pin
  (`9db11f5f…`), V-18 legacy row `1748e5b5…` reproduced via the unchanged
  production `approval_request_digest`. The v2 recipe used is exactly the
  SPEC's; `canonical_approval_payload_bytes` / `approval_request_digest_v2`
  remain absent from `packages/*/src` — correct for an unaccepted contract.
- Seam suites: `uv run pytest packages/maistro-core/tests/capabilities/
  test_durable_approval.py test_durable_approval_validation.py -q` —
  **47 passed** (23 incl. the DurableApproval legacy-fallback seam, 24
  validation). `approval_store.py` diff is empty across
  `77873faf3f..HEAD`.
- SPEC-101826 (`docs/specs/SPEC-101826-1836-approval-payload-bytes.md`)
  status `Proposed`, `contracts: []`, diff empty across the range;
  `quality/ac-state.json` records `declares_non_measurable: true`,
  tier none, 0 criteria. Owner (@BlakeMatthews-dev) acceptance remains
  unrecorded, so the decision gate stays open **by design**; no closure
  action taken (prohibited). A repo-wide grep finds no text claiming
  acceptance.

## Other gates re-proven at this head

- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — **1221 reviewed identities == 1221
  findings, rc 0**, base `d5eea94329` (CI-exact arguments; no ledger edit
  owed — the CI-repair ledger clause is vacuous).
- `scripts/check-suite-inventory.py` — **21/21 suites match, rc 0**.
- `scripts/check-ac-state.py` rc 0 (content-identical `quality/ac-state.json`
  rewrite; tree clean after).
- Merge-touched ledger gates: `scripts/check-public-routes.py` rc 0
  (12 == 12 identities, base-authorized — the develop-side re-justification
  of the two `/v1/auth/register`, `/v1/setup/` exemptions); 
  `scripts/check-route-permissions.py` rc 0 (42 declared, 0 undeclared);
  `uv run pytest tests/test_m1_542_policy_coverage.py
  tests/test_autonomous_merge_policy_inputs.py -q` — **22 passed**.
- workflow-lint (actionlint + shellcheck, incl. the merged
  `mutation-nightly.yml` which arrived from develop already validated
  there): `success` in CI at this exact head.
- Driver checks in this job's logs: `uv sync --locked --extra dev` rc 0,
  `uv run ruff check .` rc 0, `uv run ruff format --check .` rc 0.

## Gate status

The named red gate's root cause (npm audit) is proven fixed at this head
with CI-exact arguments; CI at this head shows zero failed legs. The
decision gate itself stays open by design pending the named owner's
explicit acceptance of SPEC-101826's contract and vectors (issue #1836
decision boundary) — a human decision no round can grant. No gate weakened,
no quality ledger edit, no GitHub mutation; worktree left clean
(note-only commit).
