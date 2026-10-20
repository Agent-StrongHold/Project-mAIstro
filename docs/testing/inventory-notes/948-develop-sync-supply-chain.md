# 948 — develop sync repairs the aiohttp supply-chain gate

No test was added, removed or renamed on this branch by this round, so there is
no `inventory-delta` block: the develop sync brought upstream's own tested
changes and their notes. The full `check-suite-inventory.py` run at the merged
head stays green (`ok: 21 suite(s) match`, 32401 collected node IDs).

## The failure, reproduced before the fix

At `ea2fd376c` the `security` workflow is red on one leaf: `Supply chain
(pip-audit)` (`sast` aggregation therefore also red). `sast-bandit`,
`sast-semgrep` and `sast-gitleaks` all pass. Reproduced locally against the
branch's own lock, before merging anything:

```
uv pip freeze --exclude-editable > /tmp/deps.txt
uvx pip-audit --strict --format=json -r /tmp/deps.txt   # exit 1, 5 advisories in 2 packages
uv run python scripts/pip_audit_gate.py /tmp/pip-audit.json
::error::pip-audit found advisories outside the triaged allowlist:
  aiohttp==3.14.3 CVE-2026-111064 -> upgrade to 3.14.4
  aiohttp==3.14.3 GHSA-2g87-pp6c-29x5 -> upgrade to 3.14.4
  aiohttp==3.14.3 CVE-2026-111063 -> upgrade to 3.14.4
```

`aiohttp` is a transitive dev dependency (via `cosmic-ray`, the mutation
runner), not a runtime dependency of any shipped package. The gate's own
instruction for a finding with an available fix is to upgrade the dependency —
not to widen `ALLOWED`.

## The repair is the develop sync, not a hand edit

`origin/develop` `9417bb2f4` already carries the correction, made for the same
gate in its own CI-repair round: `aiohttp` 3.14.3 -> 3.14.5 and `yarl` 1.24.2 ->
1.25.1 in `uv.lock` (plus its `pg_audit` absent-table repair and the associated
tests). This branch was behind that commit by exactly one. Merging
`origin/develop` into `auto-948` resolved the failure with no conflict and no
`uv.lock` hand edit; re-locking by hand would have produced a divergent lock
against the base the merge queue will use.

## Evidence at the merged head

- `uv sync --locked --extra dev`: aiohttp 3.14.3 -> 3.14.5, yarl 1.24.2 -> 1.25.1
- `uvx pip-audit --strict --format=json -r /tmp/deps2.txt` then
  `uv run python scripts/pip_audit_gate.py`: `pip-audit OK (1 known, all triaged
  in ALLOWED)` / `direct-dependency usage OK: 11 packages, 62 runtime
  dependencies, 4 reviewed dispositions` — exit 0. The only remaining advisory
  is the reviewed `ecdsa` PYSEC-2026-1325 pair.
- The same gate re-run over CI's exact shape — `uv sync --locked --all-extras`
  (210 frozen requirements, not the 208 of `--extra dev`) then pip-audit and
  `scripts/pip_audit_gate.py`: identical exit 0, identical triage line. The
  wider optional set adds no advisory.
- `uv run ruff check .` and `uv run ruff format --check .`: clean (3363 files).
- `uv run pytest packages/maistro-core/tests/extensions/test_lifecycle_proof.py
  packages/maistro-core/tests/runs/test_public_surface.py -q`: 25 passed.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_audit.py
  packages/maistro-core/tests/test_container_wiring.py -q`: 65 passed, 2 skipped
  (upstream's `pg_audit` repair, carried in by the same merge).
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`: 1326 reviewed identities -> 1326 findings, exit 0 — no
  ledger amendment was needed or made.
- `check-ratchet-provenance.py`: 168 unreachable modules, no
  candidate-approved expansion (all ratchets), exit 0.
- `check-shipped-surface-truth.py` and `check-reachability-dispositions.py`:
  exit 0 (48 groups cover all 168 unreachable modules).
