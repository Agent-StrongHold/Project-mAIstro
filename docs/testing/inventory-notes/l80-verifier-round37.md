---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-core/tests: +0
---
# L80 verifier round 37 — named pip-audit CI failure not reproducible; refusal leak diagnosed as shared-daemon race

Head under validation: `18f49b972cac` (clean worktree, no develop drift:
`HEAD..origin/develop` is empty; merge base `f8a2df966a1d`). No code was
edited this round — this note records executed evidence for the two blocks
carried into it.

## 1. CI gate failure "Supply chain (pip-audit)" — NOT reproducible at head

Executed with CI's exact arguments (security.yml `supply-chain` job, lines
168–197), both for the dev-extras lock and the job's own `--all-extras`
environment:

- `uv sync --locked --all-extras` → 218 frozen deps
- `uv pip freeze --exclude-editable > deps.txt`
- `uv run pip-audit --strict --format=json -r deps.txt` → report complete
  on attempt 1 (audit exit 1: "Found 2 known vulnerabilities in 1 package")
- `uv run python scripts/pip_audit_gate.py pip-audit.json` → **RC=0**:
  `pip-audit OK (1 known, all triaged in ALLOWED)` — both findings are
  `ecdsa==0.19.2 PYSEC-2026-1325`, whose pair disposition already exists in
  the gate's `ALLOWED` ledger — and
  `direct-dependency usage OK: 11 packages, 66 runtime dependencies, 4
  reviewed dispositions`

The same gate also passes against the dev-extras freeze (223 deps, RC=0).
Head `18f49b972` already carries six supply-chain remediation commits
(5065aa984..18f49b972, dnspython/graphql-core/joserfx/otel-api, vendored
docker/cli, oauthlib/pyasn1/pypdf/soupsieve, temporalio, CPython base pins,
playwright/patchright + klauspost vendored patch). The queued evaluation's
failure either predates those commits or was a PyPI registry outage — the
workflow itself classifies an unusable report after 3 attempts as
infrastructure ("retry the job"). No ledger or allowlist change is warranted.

## 2. Previous block "recovery budget exhausted: provider error 404 (nous/poolside/laguna-s-2.1:free)"

Infra/orchestrator-side: the requesting model id does not exist in the
OpenRouter catalog. Nothing in this tree can fix or guard that; recorded as
UNRESOLVED-BY-CODE, to be retried by the dispatcher with a valid model.

## 3. Prior failed check (`check-3` of job 76aa850): refused entry "left a sandbox container behind"

Re-executed the container trio at head:
`uv run pytest packages/maistro-bootstrap/tests/test_container_lane.py
packages/maistro-bootstrap/tests/test_container_sandbox.py
packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py -q` →
**33 passed, 20 skipped**.

Diagnosis of the leak: the production refusal path does clean up —
`ContainerBuilderSandbox.__enter__` runs the ADR-093 Decision 2 gate inside
its `try` and the `except BaseException` handler calls `__exit__`, which
executes a synchronous `docker rm -f` (container_sandbox.py:305–309, 616–620).
The leaked container id `576e77045afa` therefore matches the race the test
itself documents for a **shared daemon**: "other work may legitimately ...
add unrelated containers between the two snapshots" — i.e. a concurrent
lane's sandbox (same `ancestor=maistro-builders:latest`) appeared in the
post-entry snapshot, not the pre-entry one. On this worktree's daemon the
refusal test is on the documented skip branch (the daemon provably provides
the userns boundary, `container_sandbox.py:109–115`), and the escape suite's
conformance branch is what runs instead. Post-run daemon state checked:
0 containers with `ancestor=maistro-builders:latest` — no leak.

## 4. Remaining battery at head (executed this round)

- `uv run ruff check .` RC=0; `uv run ruff format --check .` RC=0
  (3562 files) — driver check-1/check-2, re-confirmed by driver
- Vulture gate, CI-exact args (`packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`): **RC=0**, 1238 reviewed identities =
  1238 findings, `never_allowlist: 0`
- Suite inventory (`scripts/check-suite-inventory.py --suite
  packages/maistro-bootstrap/tests`): **ok** — 309 collected node IDs,
  309 unique identities, 0 duplicate evidence (driver check-4)

## Verdict

All executed gates RC=0 at head; neither carried block is a code defect at
`18f49b972`. Residual: CI re-run needed to confirm the pip-audit job
transient; the orchestrator provider 404 is dispatcher-side.
