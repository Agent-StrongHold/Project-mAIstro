---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-core/tests: +0
---

# L80 verifier round 38 — CI 80/80 green at the round-37 head; pip-audit gate re-proven RC=0 (CI-exact args); refusal branch live-passed

Head under validation: `990799bb162e` (clean worktree; one docs commit ahead of
the round-37 head `18f49b972`, no code delta). No code was edited this round —
this note records executed evidence for the two blocks carried into it.

## 1. CI gate failure "Supply chain (pip-audit)" — green in CI at this exact head, re-proven locally

CI evidence: the check-runs captured for commit `990799bb162e` (dispatch
snapshot, 2026-11-16T14:05:10Z) list **80 completed checks, all conclusion
`success`** — including `Supply chain (pip-audit)`, `sandbox-conformance`,
`exact-debt-ledger`, `Quality / Vulture`, and `block`.

Local re-proof with CI's exact arguments (security.yml `supply-chain` job,
lines 168–197, the job's own `--all-extras` environment), executed at
`990799bb162e`:

- `uv sync --locked --all-extras` → 233 frozen deps
- `uv pip freeze --exclude-editable > /tmp/deps.txt`
- `uv run pip-audit --strict --format=json -r /tmp/deps.txt` → report
  complete on attempt 1 (audit exit 1: "Found 2 known vulnerabilities in 1
  package")
- `uv run python scripts/pip_audit_gate.py pip-audit.json` → **RC=0**:
  `pip-audit OK (1 known, all triaged in ALLOWED)` — both findings are
  `ecdsa==0.19.2 PYSEC-2026-1325`, whose pair disposition is already in the
  gate's `ALLOWED` ledger — plus `direct-dependency usage OK: 11 packages,
  66 runtime dependencies, 4 reviewed dispositions`

No ledger or allowlist change is warranted: the gate is green at head both in
CI and locally, so the queued failure either predates the head or was a PyPI
registry outage (which the workflow itself classifies as "retry the job").

## 2. Previous block "recovery budget exhausted: provider error 404 (nous/poolside/laguna-xs-2.1:free)"

Infra/orchestrator-side: the requesting model id does not exist in the
OpenRouter catalog. Nothing in this tree can fix or guard that; recorded as
UNRESOLVED-BY-CODE, to be retried by the dispatcher with a valid model.

## 3. Container trio and the live refusal branch at this head

Re-executed the container trio at head:
`uv run pytest packages/maistro-bootstrap/tests/test_container_lane.py
packages/maistro-bootstrap/tests/test_container_sandbox.py
packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py -q` →
**33 passed, 20 skipped**, and
`pytest test_container_sandbox.py::test_sandbox_refuses_a_rootful_unmapped_daemon -v`
→ **PASSED** against the real rootful daemon (identity uid map positively
observed — Docker 29.1.3, root-owned socket, no userns remap in
`/etc/docker/daemon.json`). The 20 skips are the structural fail-closed
branch (daemon rootful → sandbox refuses, escape suite deferred to the
self-provisioned rootless lane). The full escape branch is proven by the
`sandbox-conformance` CI check at this head: `success` (rootful refusal step,
rootless daemon provisioning, delegated-cgroup memory proof, then the suite).

## 4. Remaining battery at head

- Driver checks at `990799bb162e` (job `f14ccb20`): `uv run ruff check .`
  RC=0, `uv run ruff format --check .` RC=0 (3562 files), suite inventory
  `scripts/check-suite-inventory.py --suite packages/maistro-bootstrap/tests`
  ok (309 collected node IDs, 309 unique identities, 0 duplicate evidence).
- Acceptance walk of #80 against the tree (no new tests needed): the
  filesystem/process/namespace/network/device/host-socket/credential/
  privilege escape surface, network+credential default-deny, `.env`/`.git`/
  host-secret seed exclusion, non-root execution + userns boundary, pinned
  writable scope, timeout/kill/cleanup and memory exhaustion are each covered
  by named tests in `test_container_sandbox.py` /
  `test_container_sandbox_hardening.py` instantiating the production
  `ContainerBuilderSandbox`; the CI lane is registered required in
  `.github/branch-protection.json` (`sandbox-conformance`); SECURITY.md
  limitation #8 cites the Builder conformance evidence (SECURITY.md:374–383).

## Verdict

All executed gates RC=0 at `990799bb162e`; CI at this exact head is 80/80
success. Neither carried block is a code defect: pip-audit is green at head
(CI + local CI-exact re-proof), and the provider 404 is dispatcher-side.
