# Repair notes — auto-944 CI-gate round 2

Branch `auto-944`, worktree `/home/dev/Git/wt/auto-944`.
Started at `3c30e52f3f56d64b5f6d7851f66a38ee68b3b13d`; finished at `87a4962ee809`.
Base `origin/develop` = `e20e9f52ea94b393184f210cc9379f9f693f13d0`.

## What the dispatch asked

Repair the named gate failure from the last merge-queue evaluation
(**Supply chain (pip-audit)**) and the prior block
(`worker requested attention: NEEDS-DEEP-REVIEW`), then verify every
acceptance criterion against reachable production behaviour and meaningful
tests rather than against earlier verification claims.

## Finding 1 — Supply chain (pip-audit): already green at the starting head

Re-ran the workflow's exact commands, both scopes.

- `uv lock --check` → `Resolved 260 packages in 3ms`, exit 0.
- `uv pip freeze --exclude-editable > /tmp/deps.txt` (225 dists), then
  `uv run pip-audit --strict --format=json -r /tmp/deps.txt` → exits 1 with
  `Found 2 known vulnerabilities in 1 package`.
- `uv run python scripts/pip_audit_gate.py /tmp/pip-audit.json` →
  `allowed: ecdsa==0.19.2 PYSEC-2026-1325`,
  `pip-audit OK (1 known, all triaged in ALLOWED)`,
  `direct-dependency usage OK: 11 packages, 62 runtime dependencies, 4 reviewed dispositions`,
  **exit 0**.

The `[tool.uv] constraint-dependencies = ["aiohttp>=3.14.4"]` pin plus re-lock
landed in `3c30e52f3` is real and sufficient. No dependency edit was needed or
made.

Two incidental observations, neither a defect:

- `uv run --all-extras pip-audit` (no `-r`) crashes on
  `gallery-model-adapter (1.0.0)` — "Dependency not found on PyPI". CI never
  runs that form; both supply-chain jobs audit `uv pip freeze
  --exclude-editable` output, which does not contain that local dist.
- The advisory that pip-audit reports today is `ecdsa 0.19.2 /
  PYSEC-2026-1325`, not the `aiohttp 3.14.5` / `yarl 1.25.1` pair the previous
  round saw. The upstream advisory DB moved; the allowlist covers the current
  one. The gate's verdict is what decides, per its own docstring.

## Finding 2 — the real regression: `Quality / Convergence matrix` and the root `test` job

The previous round's claim *"`test` — FIXED by the banked row"* is **false**.
Banking `maistro.runs.admission_identity` into
`quality/reachability-baseline.json` cleared the reachability ratchet and broke
a different gate that reads the same file.

`scripts/check-convergence-matrix.py::unreachable_modules()` derives its
Unreachable column from `quality/reachability-baseline.json` (line 129), not
from a live scan. Before the bank the "Run / NodeRun / Attempt lifecycle"
census was 0/32, matching the row's `none`. After it, 1/32 — `few`.

Verified the regression is this branch's, not inherited:

- `git show 8ec45fb8b:quality/reachability-baseline.json | grep -c admission_identity` → 0
- `git show 3c30e52f3:quality/reachability-baseline.json | grep -c admission_identity` → 1
- `git diff --stat 8ec45fb8b 3c30e52f3 -- docs/architecture/CONVERGENCE-MATRIX.md` → empty

So the matrix is byte-identical across the two commits while its input moved.
`uv run pytest tests/` at `3c30e52f3` was **1 failed / 5488 passed**:
`tests/test_check_convergence_matrix.py::test_the_shipped_matrix_matches_the_shipped_code`.
`ci.yml` line 651 runs `uv run pytest tests/ --ignore=tests/tools/registry`, and
`quality.yml` line 2022 runs `scripts/check-convergence-matrix.py`, so both the
`test` job and `Quality / Convergence matrix` were red.

### Repair — `f7db22ed5`

`docs/architecture/CONVERGENCE-MATRIX.md`, Run / NodeRun / Attempt lifecycle
row: `none` → `` `few` — `runs.admission_identity` is the #1851 inactive
contract leaf: banked unreachable until #1845's admission backend wires it, so
the row is one module short of `none` ``. `#1845` added to Dependencies.

This is the candidate-editable ledger the gate itself points at ("Update the
matrix row (or the code) so the two agree"); `check-convergence-matrix.py` is
not in `scripts/check-ratchet-provenance.py`'s trusted-base inventory, so it has
no develop-side grant requirement. It is a factual correction, not a cosmetic
one: the row now names the module and the issue that closes the gap, and the
reachability ratchet's own two legs are untouched and still owner-blocked.

### Result

- `scripts/check-convergence-matrix.py` → `OK: 52 subsystems classify all 1419
  production modules; 169 unreachable modules are attributed`, exit 0
- `pytest tests/test_check_convergence_matrix.py` → 60 passed
- `pytest tests/` (full root suite) → **5489 passed, 138 skipped, 0 failed**

## Finding 3 — a real test gap, found by mutation testing

Deleting the `org {org_id!r} is not registered with extension policy` reason in
`resolve_extension_policy` (`packages/maistro-core/src/maistro/extensions/policy.py:311`)
left **all 37** sibling tests green.

The reason it survived: `test_unregistered_org_denies_everything` resolves
against a bare `ExtensionPolicyLedger()`, where the *Workspace* "not
registered" reason already denies. Two independent deny reasons satisfying the
same assertion mask each other, so neither is pinned.

The table shape where they do not overlap — a Workspace override recorded with
no org policy — cannot be built through the ledger
(`set_workspace_override` raises "not registered; set its policy first"), which
is why nothing else reaches it. It *is* reachable through the exported pure
`resolve_extension_policy`, which takes whatever table it is handed.

With the reason removed that shape resolves to `enabled=True`,
`permission_ceiling=None`, `pin=None`: an org with no recorded policy gets an
enabled extension with no ceiling and no version pin.

### Repair — `87a4962ee`

`test_org_absent_from_a_workspace_scoped_table_denies` in
`packages/maistro-core/tests/extensions/test_extension_policy_governance.py`,
plus the `resolve_extension_policy` import. Inventory note
`docs/testing/inventory-notes/auto-944-c0ve.md` (+1 node ID).

**Proof it is meaningful:** with the reason deleted the suite is `1 failed, 37
passed` and the single failure is this test, with
`assert not True ... enabled=True, reasons=(), pin=None,
permission_ceiling=None`. Restoring the line gives `38 passed`.

The 21 mypy errors a bare `mypy <test file>` reports are pre-existing (21 at
`HEAD` too) and outside the gate, which measures `packages/*/src` only:
`mypy packages/maistro-core/src ...` is clean at 908 files.

## Mutation testing carried over from the prior round (re-confirmed)

| Mutation | Result |
|---|---|
| `quarantine.py::_require_authorized` neutered | 2 tests fail — `test_extension_actor_cannot_mutate_governance_state`, `test_extension_actor_cannot_clear_an_administrator_quarantine` |
| `policy.py` tenant bucketing `setdefault((org_id, ""), {})` broken | 2 tests fail — `test_tenant_views_are_structurally_isolated`, `test_tenant_state_never_leaks_under_mixed_operations` |

Both restored; tree verified by md5sum and `git status --porcelain`.

## Full validation battery at `87a4962ee809`

| Gate | Outcome |
|---|---|
| `uv lock --check` | exit 0 |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 3366 files already formatted |
| `pip-audit` + `pip_audit_gate.py` (exact CI commands) | gate exit 0 |
| `scripts/check-dependency-namespaces.py` | exit 0 |
| `scripts/check-shipped-surface-truth.py` | matrix complete |
| `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1326 identities → 1326 findings, exit 0 |
| `scripts/check-reachability.py` | 1419 modules, 169 unreachable, exit 0 |
| `scripts/check-reachability-dispositions.py` | 49 groups, 147 CONNECT / 20 LIBRARY / 2 RETIRE, exit 0 |
| `scripts/check-merge-markers.py` | exit 0 |
| `scripts/check-convergence-matrix.py` | exit 0 |
| `scripts/check-suite-inventory.py` | 21 suites, 32459 node IDs, 0 duplicates, exit 0 |
| `mypy packages/*/src` (908 files) | Success |
| `pytest tests/` (root self-checks) | 5489 passed, 138 skipped |
| `pytest packages/maistro-core/tests` | 15720 passed, 1131 skipped, 7 xfailed |
| `pytest packages/maistro-core/tests/extensions` | 1189 passed |
| `scripts/check-diff-coverage.py` (vs base) | exit 0 |

Diff coverage, per file over the changed lines: `policy.py` 198/199 lines
(99.5%, the one uncovered line is `_utc_now`'s body — the injectable default
`clock`, never invoked because every test passes an explicit clock) and 32/32
branch arcs; `quarantine.py` 249/249 lines (100%) and 37/38 arcs (97.4%);
`extensions/__init__.py` 2/2. Both test files are `EXEMPT` by declaration;
`_vulture_whitelist.py` is unmeasured scope (no producer).

## Still red, and why it cannot be fixed here

`RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
→ exit 1 on exactly two legs:

- `ratchet: reachability` — `168 unreachable modules -> 169`
- `ratchet: reachability-dispositions` — `168 dispositioned modules -> 169`

Both name one module: `maistro.runs.admission_identity`,
`NEW ... absent from trusted base and not previously authorized`.

`origin/develop` (`e20e9f52e`, PR #1936 from `auto-1851`) merged that inactive
contract leaf without a `reachability` grant in
`quality/ratchet-authorizations.json` (11 grants there, none for it).
`ratchet_provenance.load_authorizations` reads the ledger from the merge base,
so a candidate-side grant is inert by the two-merge rule — the gates say so
("candidate baseline edits cannot approve them").

This is a develop-side gap, not a #944 defect. Closing it needs a maintainer to
land the grant on `develop` (or to delete the leaf) in a separate change; the
prior `#1851` repair note reached the same conclusion.

## Verdict

`NEEDS-REPAIR` — the #944 implementation itself is green and every acceptance
criterion is verified, but the branch cannot merge until develop-side
authorization lands for `maistro.runs.admission_identity`.
