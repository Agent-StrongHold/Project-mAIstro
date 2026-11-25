---
inventory-delta:
  tests/: +0
---

# Verification round at head 9edc9121ad (L1836, issue #1836) — note-only

Round at the assigned head `9edc9121ade186bc0aef138acab455206a7bda75`
(note-only commit on top of `5d6eeb7f18`, the develop sync merge of
`d5eea94329`). The prior worker round (`9e4fe5f4`, result.json in the job
dir) died on a provider 429 **before producing any review work** — its only
outputs were the driver's deterministic checks — and had requested
NEEDS-DEEP-REVIEW without recording a finding. This round therefore
re-executes the full acceptance battery itself, live, at this head.
No test files added or changed (`tests/: +0`).

## Deterministic acceptance of decision gate #1836 (issue-exact pair)

- `uv run python scripts/check-adr-status-language.py` rc 0 ("0 baselined
  body-status contradiction(s)"); `git diff --check` rc 0.
- Driver checks in this job's logs: `uv sync --locked --extra dev` rc 0,
  `uv run ruff check .` rc 0 ("All checks passed!"),
  `uv run ruff format --check .` rc 0 ("3655 files already formatted").

## Golden vectors V-1 … V-18 re-executed live

Reproduction script committed as
`.cursor/context/repro-1836-vectors.py`; **35/35 checks PASS, rc 0** against
the production helper (`maistro.capabilities.approval_store.approval_request_digest`,
unchanged at `approval_store.py:27`) and the SPEC's v2 recipe exactly as
written:

- V-1 canonical bytes **byte-identical** to the SPEC literal and digest
  `v2:8db816aa…8ca82c`; V-2 reversed top-level + nested `effect` key order →
  byte-identical output, V-1 digest.
- V-3 … V-13: one mutation per protected field (incl. the two nested `effect`
  rows); every digest matches the SPEC table and all twelve digests
  (V-1 + eleven mutations) are pairwise distinct.
- V-14: `true` ≠ `1` and `10` ≠ `10.0` at the bytes level.
- V-15: all eight unsupported inputs raise `TypeError` with the exact
  path-naming messages (`datetime`, `bytes`, `UUID`, `Decimal`, `set`,
  `object`, non-str key at `effect` with `(got int)`, NaN); the v1 hazard
  column re-proven (production helper silently digests `Decimal("10.00")` →
  `{"issued_at":"10.00"}`).
- V-16: production v1 helper digests `{"1": "a"}` and `{1: "a"}` identically;
  mixed keys raise `'<' not supported between instances of 'str' and 'int'`.
- V-17: v1 and v2 both produce `b'{"name":"caf\\u00e9"}'`; v1 digest
  `9db11f5f…f5128`.
- V-18: legacy row `1748e5b5…dc6c9` reproduced via the production helper
  **and** end-to-end through the unchanged `DurableApproval` fallback
  (empty `request_digest`, `params` without `request_digest`/`request` →
  `_derived_digest` re-digests `params` to the same value).

`canonical_approval_payload_bytes` / `approval_request_digest_v2` remain
absent from `packages/*/src` (grep count 0) — correct for an unaccepted
contract; no implementation is claimed.

## Named red gate — integration-scope (live CI evidence)

Read-only `gh api` check-run listing at the PR #2264 head
`5d6eeb7f1891a731b35ad70284d4e1573954841f` (the head CI evaluates; this
round's head adds only the previous note-only commit): **`integration-scope`
= completed/success**, `hive-conductor-e2e-ui` = completed/success (the
historical root cause leg), `hive-conductor-e2e` = success, `docker-build` =
success, `wheel-imports` = success, `JS supply chain (npm audit + GuardDog +
policy gate)` = success, `exact-debt-ledger` = success, Analyze triplet /
DevSkim / Container scan + SBOM + cosign / SAST triplet all success —
**zero failed legs**; the only in-flight run is the Coverage gate.

Local re-proof of the npm-audit signal with CI-exact arguments
(`npm audit --package-lock-only --json`, security.yml surfaces): rc 0 with
`total: 0` vulnerabilities for all three surfaces
(hive-conductor/frontend, maistro-canvas/frontend, hive-conductor/tests/e2e)
— the typescript-eslint 8.74.0 lockfile fix (`1c29c03bad`) holds. The
ci.yml canvas verdict: `npm audit --json` rc 0 +
`scripts/npm_audit_gate.py` rc 0 ("0 advisories reported, all triaged in
ALLOWED"). `scripts/js_dependency_gate.py` with the three audit reports
fails only on "no GuardDog report supplied" (scanner not installed locally);
that leg's green verdict is the live CI `JS supply chain` run above.

## Other gates re-proven at this head

- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — **1221 reviewed identities == 1221
  findings, rc 0**, base `d5eea94329` (CI-exact arguments; no ledger edit
  owed — the CI-repair ledger clause is vacuous).
- `scripts/check-suite-inventory.py` — **21/21 suites match, rc 0**.
- `scripts/check-ac-state.py` rc 0 (content-identical `quality/ac-state.json`
  rewrite; `git status` clean after). The ledger records SPEC-101826-1836:
  `declared_status: Proposed`, `declares_non_measurable: true`, tier none,
  `criteria_total: 0`.

## Gate status

SPEC-101826
(`docs/specs/SPEC-101826-1836-approval-payload-bytes.md`) status `Proposed`,
front matter `contracts: []`; owner (@BlakeMatthews-dev) acceptance remains
unrecorded, so the decision gate stays open **by design** — the issue states
the hygiene command cannot ratify the contract and this round takes no
closure action. The named CI gate failure (integration-scope) is proven
resolved with live check-run evidence at the PR head. No gate weakened, no
quality ledger edit, no GitHub mutation. Evidence artifacts committed this
round: this note and `.cursor/context/repro-1836-vectors.py`.
