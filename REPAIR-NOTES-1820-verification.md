# Independent verification round for #1820 CI gate repair

Candidate: `auto-1820` @ `0a36de03e` — "CI repair: refresh the aiohttp lock for the
security gate; record the base-owned reachability failures".
Base: `origin/develop` @ `e20e9f52e` (`git merge-base HEAD origin/develop` = e20e9f52e).

The prior round already committed the lane-owned fix — `aiohttp` 3.14.3 → 3.14.4
in `uv.lock` (commit `0a36de03`) — and recorded full evidence in
`REPAIR-NOTES-1820-ci-gate-repair.md`. This round's mandate was to **run the
named gates locally to prove the fix** (security + the vulture per-identity
ledger CI-repair). The production tree was **not edited**; this is an
evidence-only commit. No `quality/*.json` ledger was modified: the vulture
ledger needs no amendment (see below), and the lane brief restricts this round
to a `vulture-baseline.json` amendment only.

## Gates run locally at HEAD `0a36de03e` (exact CI shapes reproduced)

| Gate (CI shape) | Command | Result |
|---|---|---|
| Lock validity | `uv sync --locked --all-extras` → `Resolved 260 packages` | ok |
| Lint | `uv run ruff check .` | `All checks passed!` (driver check-1) |
| Format | `uv run ruff format --check .` | `3363 files already formatted` (driver check-2) |
| Core pytest | `uv run pytest tests/test_delivery.py tests/test_plan.py tests/test_upgrade.py -q` | `120 passed` (driver check-3) |
| Suite inventory | `uv run python scripts/check-suite-inventory.py` | `ok: 21 suite(s) match the recorded inventory` (driver checks 4/5) |
| **Supply chain (pip-audit)** | `uv pip freeze --exclude-editable > /tmp/deps.txt` (225 dists); `uv run pip-audit --strict --format=json -r /tmp/deps.txt`; `uv run python scripts/pip_audit_gate.py /tmp/pip-audit.json` | `allowed: ecdsa==0.19.2 PYSEC-2026-1325` / `pip-audit OK (1 known, all triaged in ALLOWED)` / `direct-dependency usage OK: 11 packages, 62 runtime dependencies, 4 reviewed dispositions` → **exit 0** |
| **#1820 acceptance tests** | `uv run pytest tests/test_install_runtime_selection.py tests/test_backup_restore_oracle.py tests/test_install_compose_floor.py tests/test_install_engine_floor.py -q` | `82 passed` (matches REPAIR-NOTES-1820-ci-gate-repair.md §3) |
| **Vulture CI-repair** (exact-debt-ledger) | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | `1326 reviewed identities -> 1326 findings`; `unclassified: 0`; `never_allowlist: 0` → **exit 0**; `quality/vulture-baseline.json` left untouched |
| Shipped-surface truth | `uv run python scripts/check-shipped-surface-truth.py` | `Shipped-surface truth matrix is complete.` → **exit 0** |
| Reachability (structural) | `RATCHET_BASE_REV=origin/develop uv run python scripts/check-reachability.py` | exit 1 — **identical to the documented base-owned regression** (see §3) |

Installed `vulture` in this interpreter is **2.16** (the gate reports it as the
analyzed tool identity, metric v1).

## Independently reproduced pre-fix regression (security)

With `aiohttp==3.14.3`: `uv run pip-audit --strict -r /tmp/deps.txt` returns
`CVE-2026-111064`, `GHSA-2g87-pp6c-29x5`, `CVE-2026-111063`, all of which list
`3.14.4` as the fix. At HEAD (`aiohttp==3.14.4`, confirmed via
`uv pip freeze --exclude-editable | grep aiohttp` == `aiohttp==3.14.4`) those
three advisories are absent; only the reviewed
`ecdsa==0.19.2 PYSEC-2026-1325` remains, and it is allow-listed in
`scripts/pip_audit_gate.py`'s `ALLOWED`. Hence the lane-owned `security`
failure is **repaired and proven** by the supply-chain gate exiting 0.

## Vulture ledger reconciliation (resolves a prior mis-transcription)

A condensed prior summary claimed `check-vulture-baseline.py` reported "12
UNBANKED findings" against a "configured 1342, observed 1354" ledger. That text
**does not appear in the gate's actual output** and is not reproducible: the
authoritative save of the run
(`/tmp/vulture.log` → `vulture baseline summary:` /
`1326 reviewed identities -> 1326 findings` / `unclassified: 0` /
`never_allowlist: 0`) is green at exit 0, with **zero candidate-added debt and
zero stale rows**. The candidate diff touches no production Python (only
`uv.lock`), so it introduces no dead code; `quality/vulture-baseline.json`
requires no amendment and was left untouched. `quality/ratchet-authorizations.json`
is unchanged as well.

## Scope note — residual red is owner-held, not a candidate regression

The single remaining red gate is **reachability**. It is byte-identical to CI's
failure and to a reproduction on a pristine `origin/develop` worktree:

```
1417 production modules, 169 unreachable from any entry point
1 module(s) are NEWLY UNREACHABLE:
  maistro.runs.admission_identity  (maistro.runs.admission_identity)
```

The newly-unreachable module is `maistro.runs.admission_identity`, introduced by
base commit `e20e9f52` (develop PR #1936 / `auto-1851`), imported only by
`packages/maistro-core/tests/runs/test_root_admission_identity.py`, and absent
from `quality/reachability-baseline.json`. This lane's diff touches neither the
module nor that ledger. Per §2–§3 of `REPAIR-NOTES-1820-ci-gate-repair.md` this
is the owner-held `auto-1851` regression and is out of scope for this round;
banking it would require a `reachability-baseline.json` amendment, which the
lane brief forbids ("no other ledger/grant edits"). This round did not repair
it and confirms it was not caused by the candidate.

## Conclusion

All gates this lane owns are green locally at `0a36de03e`: **security**
(pip-audit supply-chain) ✓, **vulture CI-repair** ✓ (1326→1326, 0 deltas, no
ledger amendment), **shipped-surface truth** ✓, lint/format ✓, suite inventory
✓, and #1820's own acceptance tests ✓ (82 passed). The only residual red is
the pre-existing, base-owned `admission_identity` reachability regression
documented in `REPAIR-NOTES-1820-ci-gate-repair.md` §2 — owner-held by
`auto-1851` (#1936), reproduced on a clean `origin/develop` worktree, not
introduced by this candidate.
