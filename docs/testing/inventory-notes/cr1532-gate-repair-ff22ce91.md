---
inventory-delta:
  tests/: +0
---

# cr-1532 gate repair at ff22ce910 (CI-repair round: stale contract golden)

Repairs the hosted CI failures at `ff22ce9100b7` (base `f8a2df966a1d`). No test
was added, removed, or renamed: the only change is one sha256 digest in the
`tests/fixtures/ci_quality_obligations.json` contract golden, so the collected
`tests/` count is unchanged (6129 = 5990 passed + 139 skipped locally).

## Root cause (measured, not assumed)

8f15f2ef0 raised the coverage-gate job's `timeout-minutes: 30 -> 45` in
`.github/workflows/quality.yml` (rationale in that commit) but did not update
the contract golden, so `tests/test_ci_quality_split.py::
test_every_original_quality_obligation_survives_with_its_profile` failed with
`assert 'a97ddcd8707b...' == '7211a89d2b91...602abd89e1cf2'` — reproduced
locally, byte-identical to the CI log. The mismatch is the single
`coverage_jobs["coverage-gate"]` digest; the parsed job differs from base in
exactly one key (`timeout-minutes`), and the YAML comment is not part of the
digest. One failing test broke two gates: the ci.yml `test` job and the
quality.yml coverage-gate scripts producer (which runs the same `tests/` under
`--source=scripts` and aborts the producer on any non-zero pytest exit, hence
"producer contributed no coverage data"). This is the same mechanism
79e380299 already repaired for a XENON_BASELINE change; the fixture has no
generator and is read as the trusted snapshot, so a one-line golden update is
the correct mechanism, not a revert of the timeout repair (reverting would
re-create the 30m18s cancellation that motivated 8f15f2ef0).

## Gates re-run locally at the repaired tree

- `uv run pytest tests/ -q` — 5990 passed, 139 skipped (superset of the CI
  `test` job's argv, which ignores only `tests/tools/registry`; that directory
  passed in this run too).
- coverage-gate scripts producer extra legs:
  `tests/test_model_check_consumer_claim.py` +
  `packages/maistro-core/tests/extensions/test_lifecycle_proof.py` — 49 passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI's exact args) — RC=0,
  1238/1238 banked, 0 unclassified; no ledger amendment needed this round.
- `uv run python scripts/check-adr-status-language.py` (registry.yml argv) —
  RC=0; independent grep finds 0 body status lines in `docs/adr` + `docs/specs`
  and the diff vs base removes exactly 93 `**Status:**` body lines (the ADR's
  claimed count).
- `python scripts/check-suite-inventory.py` — ok, `tests/: 6129` unchanged.
- `uv run ruff check .` / `uv run ruff format --check .` — clean.

## Not branch-caused (structural evidence, left to trunk/infra)

security, Supply chain (pip-audit), and Container scan + SBOM + cosign failed
with registry-outage messaging ("pip-audit produced no usable report after 3
attempts ... registry/network outage; retry the job"). The branch's diff vs
`f8a2df966` touches no pip-audit/container/cosign input: no `uv.lock`, no
`pyproject.toml`, no `requirements*`, no `Dockerfile*`, no `deploy/`, no
compose, no `security.yml`/`ci.yml`. Those gates consume byte-identical inputs
on this branch and on develop, so their advisories/outages exist on trunk
independently of #1532.
