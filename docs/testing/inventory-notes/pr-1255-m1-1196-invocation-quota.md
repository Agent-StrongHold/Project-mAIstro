# PR #1255: Invocation quota test inventory

Refs #1196. Status: draft implementation evidence, not issue closeout.
Base: `develop@78bb7290688a7b404d8d705a47d48c502afdc0a0`.

## Test delta

Added `packages/maistro-core/tests/quota/test_invocation_quota_boundary.py`:
53 collected parametrized cases. No existing tests, baselines, or gates removed.

The 53 cases passed again locally before publication against a reconstructed
source subset containing the actual InvocationExecutionService and the new quota
modules. All four published Python blob hashes match the locally tested files.
The changed upstream Invocation module was rechecked on publication-base develop
and still had its original pre-edit blob `b8b348e593bcd3753589c6ca794510b3d0bcad21`.

## Evidence groups

- Provider/Workspace/principal intersection, missing policies and upper bounds,
  protected headroom, opening-spend input, and atomic multi-policy denial.
- Canonical Invocation dispatch, token/cost/request settlement, cached replay,
  alternate service/provider routes, and missing-measurement holds.
- Two OS processes and independent SQLite connections racing the same budget.
- Repeated cancellation, pre-dispatch persistence failure, ambiguous provider
  outcomes, and usage-parser failure without repeating completed effects.
- Database reopen, late billing-period settlement, and repair of interrupted
  accounting after canonical terminal persistence.
- Absolute versioned corrections, duplicate/conflicting evidence, stale evidence,
  partial measurements, retracted non-effect proof, and transaction rollback.
- Integer validation, nonfinite cost, unit mismatch, truthful overage, and no
  request/result/configuration/credential material in quota tables.

## Validation limits

Local evidence is not a full uv-workspace or GitHub CI result. The verification
subset excludes package initializers, root conftest, full governed approval
composition, real provider transports, and PostgreSQL. Ruff and mypy were not
installed locally; an attempted installation failed on DNS resolution. No claim
is made that lint, formatting, typing, full-repository tests, or repository
coverage gates pass. CI status is recorded on the PR rather than inferred here.

Required repository command for the focused suite after dependency setup:

```sh
uv run pytest packages/maistro-core/tests/quota/test_invocation_quota_boundary.py -q
```

Production composition, PostgreSQL parity, ordinary-Agent recording, legacy
tracker retirement, and independent acceptance are still unfinished. Keep the
PR draft and #1196 open until its complete acceptance is proved.
