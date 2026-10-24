# REPAIR — PR #2226 / issue #944 CI-gate round (branch `auto-944`)

Job `74c891a995a14ec1ae049d88aced8cfa`, 2026-10-20. Starting head
`8ec45fb8bd23c1ea8c91f483291e255d471eeaec`, base `e20e9f52ea94b393184f210cc9379f9f693f13d0`
(develop tip). Scope: the merge-queue reds carried on this head.

## What was red, reproduced first

Seven check-runs were failing at `8ec45fb8b`. Two independent root causes:

1. **Supply chain (pip-audit)** — `aiohttp==3.14.3` (transitive via the
   cosmic-ray dev tool) carries three advisories, all fixed in 3.14.4
   (CVE-2026-111064 / GHSA-2g87-pp6c-29x5 / CVE-2026-111063). Both the
   `ci.yml` `security` job (`--extra dev`) and `security.yml` `supply-chain`
   (`--all-extras`) audit `uv pip freeze`, so both red.
2. **Reachability ledger** — develop merged the #1851 inactive contract leaf
   `packages/maistro-core/src/maistro/runs/admission_identity.py` at
   `e20e9f52e` without banking it. The candidate scan reports 169 unreachable
   modules; the trusted baseline carries 168, and the module is absent from
   both. This reds `Quality / Reachability`, the three root-suite self-checks
   (`test_check_reachability.py::test_baseline_matches_the_tree`,
   `test_reachability_baseline_identity.py::test_the_baseline_is_exactly_the_unreachable_set`,
   `...::test_the_committed_baseline_passes_the_gate_it_now_carries`) — hence the
   `test` job — and `Quality gate` / `Coverage gate`, which depend on those.

Reproduced on the base tree (worktree at `e20e9f52e`): `check-reachability.py`
reports `169 unreachable` and `git show e20e9f52e:quality/reachability-baseline.json
| grep -c admission_identity` is 0. The develop tip fails the gate on its own;
every candidate cut from it inherits the red.

## Fixes

### 1. pip-audit floor (`pyproject.toml`, `uv.lock`)

Added a uv resolution constraint and re-locked:

```toml
[tool.uv]
constraint-dependencies = ["aiohttp>=3.14.4"]
```

`uv lock` bumped `aiohttp 3.14.3 -> 3.14.5` (and its `yarl` dep
`1.24.2 -> 1.25.1`). aiohttp is not a declared project dependency, so the
constraint — not a new dev requirement — is the right place to hold the floor:
no namespace-inventory surface changes and the next resolve cannot drift back.

### 2. Reachability ledger (`quality/reachability-baseline.json`, `quality/reachability-dispositions.json`)

Banked the module once, honestly: one baseline row plus one `CONNECT`
disposition naming the integration that reaches it (#1845's admission backend /
C2 classifier). The module is a published library handoff contract with its own
suite — it is not dead code, so the ledger row (not a fake caller) is the
campaign-precedent fix (auto-948 `b47cb2d09`, auto-881 `fe80d4c55`).

## Validation battery at the repaired tree

- `uv sync --locked --all-extras` → ok; `uv pip freeze` shows `aiohttp==3.14.5`.
- `uv pip install pip-audit && uv run pip-audit --strict --format=json -r /tmp/deps.txt`
  → only `ecdsa==0.19.2 PYSEC-2026-1325`, which the gate's allowlist carries;
  `scripts/pip_audit_gate.py` → `pip-audit OK`, exit 0.
- `scripts/check-reachability.py` → `1419 production modules, 169 unreachable`, exit 0.
- `scripts/check-reachability-dispositions.py` → `49 groups give all 169 unreachable
  modules a disposition`, exit 0.
- `tests/test_check_reachability.py tests/test_reachability_baseline_identity.py
  tests/test_check_reachability_dispositions.py tests/test_check_ratchet_provenance.py
  tests/test_ratchet_provenance_repository.py` → 67 passed (was 4 failed at the
  old baseline; reproduced by restoring `HEAD:quality/reachability-baseline.json`).
- Focused extension suites → 73 passed. Combined focused + reachability self-checks → 140 passed.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  → 1326 reviewed identities = 1326 findings, exit 0. **No vulture ledger amendment
  was needed** (and none made).
- `scripts/check-dependency-namespaces.py` → no unreviewed top-level namespaces.
- `scripts/check-suite-inventory.py --suite packages/maistro-core/tests` → ok, 16857 node IDs.
- `scripts/check-diff-coverage.py /tmp/diff-cov.xml --base e20e9f52e` (coverage from the
  two extension suites over `packages/maistro-core/src/maistro`) → `ok: every measured
  file ... at or above 90% lines / 80% branch arcs`. `_vulture_whitelist.py` is
  reported as unmeasured scope, as before.
- `uv run ruff check .` → All checks passed. `uv run ruff format --check .` → clean.
- `uv run mypy` over the seven canonical package src trees → Success, 908 files.
- No conflict markers anywhere in the tree; `git merge-base HEAD origin/develop` is
  `e20e9f52e`, so the develop-sync conflict is resolved.

## Residual red: `exact-debt-ledger` (structural, owner-held)

`scripts/check-ratchet-provenance.py` still fails on exactly one leg:

```
FAIL: reachability ratchet moved away from trusted state
  - maistro.runs.admission_identity: NEW unreachable module absent from trusted base and not previously authorized
FAIL: reachability dispositions moved away from trusted state
  - maistro.runs.admission_identity: NEW disposition absent from trusted ledger and not covered by an already-landed reachability authorization
```

Banking the row cannot authorize itself: `ratchet_provenance.load_authorizations`
reads `quality/ratchet-authorizations.json` **from the merge base** (`e20e9f52e`),
so a candidate-side grant for this module is inert under the two-merge rule, and
the trusted baseline cannot be edited from this branch. This is the same
conclusion #1851's deep-review round recorded (`7d3b6ff44`) and auto-948 recorded
(`5c4be908a`): the prerequisite is a reachability grant for
`maistro.runs.admission_identity` landed in **develop** ahead of the row, or the
#1845 integration that makes the module reachable and lets the row be pruned.
No gate, grant, or leaf edit on this branch can close it.

Everything else in the round's `check-ratchet-provenance.py` inventory is green:
adr-status-language, ac-state, wiring-reads, shell-execution, contract-markers,
promotion-surface, etc. all report `OK: ... no candidate-approved expansion`.

## Verdict of this round

- `Supply chain (pip-audit)` — FIXED.
- `security` (ci.yml pip-audit) — FIXED (same root cause).
- Develop sync conflict — already resolved; re-verified marker-free.
- `Quality / Reachability`, `Quality / Reachability dispositions`, `test`,
  `Quality gate`, `Coverage gate` — FIXED by the banked row.
- `exact-debt-ledger` — still red on the reachability provenance leg only; the
  vulture leg passes. Structural, owner-held.

Not MERGE-READY: the exact-debt-ledger acceptance criterion is not proven.
