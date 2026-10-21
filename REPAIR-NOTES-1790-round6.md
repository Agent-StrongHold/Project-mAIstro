# #1790 round 6 — pip-audit repaired (aiohttp bump); remaining CI reds reduced to one owner-held root cause, now fully characterized

Incoming state: clean worktree at `bdc3aab40d19` (round-5 head). `git fetch`
confirms `origin/develop == e20e9f52e == merge-base(HEAD, origin/develop)` —
the develop sync the previous block asked about was already completed by
round 5's `b3c951888`; nothing was pending. No GitHub mutations.

## Repair landed this round

**Supply chain pip-audit / security aggregate:** `uv.lock` bumps
`aiohttp 3.14.3 -> 3.14.5` (with transitive `yarl 1.24.2 -> 1.25.1`); the diff
touches exactly those two package blocks. Evidence: `uv run pip-audit --strict
--format=json -r /tmp/deps.txt` (deps from `uv pip freeze --exclude-editable`,
CI's exact recipe, ci.yml:990) then
`uv run python scripts/pip_audit_gate.py /tmp/pip-audit.json` — **exit 0**
("pip-audit OK (1 known, all triaged in ALLOWed)"; the remaining `ecdsa
PYSEC-2026-1325` pair has no fixed version and is in the gate's ALLOWED list).
Before the bump the same command rejected `aiohttp==3.14.3`
CVE-2026-111064 / GHSA-2g87-pp6c-29x5 / CVE-2026-111063 (exit 1). This was
inherited from develop's lockfile, not branch-caused; `security`'s aggregate
job (`security.yml` `sast` needs sast-bandit/semgrep/gitleaks; supply-chain is
its pip-audit leaf) goes green with it.

## Coverage gate — first local execution, two components

1. **Diff coverage (the branch-causable part): GREEN.** Ran the two
   quality.yml producers whose `--source` covers this branch's changed
   production files: hive backend (`pytest packages/hive-conductor/backend/tests`
   under `--source=packages/hive-conductor/backend`: **3768 passed, 24
   skipped**) and scripts (`pytest tests/ tests/test_model_check_consumer_claim.py
   packages/maistro-core/tests/extensions/test_lifecycle_proof.py` under
   `--source=scripts`), `coverage xml`, then
   `uv run python scripts/check-diff-coverage.py coverage.xml --base e20e9f52e…`
   → **"ok: every measured file this change touches is at or above 90% lines
   / 80% branch arcs"** (2 changed files measured, 6 test files exempt).
2. **Publish-set floor (87%): inputs byte-identical to develop.**
   `git diff origin/develop HEAD` is empty for every floor-measured tree
   (maistro-{core,canvas,evolve,rsi,bootstrap}/src and server/turing/design/
   registry/ext-harness/ext-sdk), so the floor measures develop's own code
   unchanged.
3. **Why the job is red at this head (root cause, not branch-caused):** the
   gate's `combine` step runs under `set -euo pipefail` (quality.yml:558) and
   its scripts producer is `pytest tests/ …` — the root suite currently has 3
   failing reachability self-checks (below), so the step exits 1, the gate
   aborts before `coverage xml`, and the job reports failure. Fix the root
   suite and the gate completes; the diff-gate component is already proven
   green here.

## CI `test` job — cause established for the first time

Full CI-equivalent battery locally (REQUIRE_AUTH=false, MAISTRO_DRY_RUN=1,
RATCHET_BASE_REV=origin/develop for the root suite):

| step | result |
| --- | --- |
| server / turing / turing-backend / design / ext-harness / ext-sdk suites | 571✓8s / 210✓ / 102✓ / 575✓1s / 273✓ / 147✓ |
| root suite `pytest tests/ --ignore=tests/tools/registry` | 5396 passed, 138 skipped, **3 failed** |
| OpenAPI types (#1048) | regenerated `types.gen.ts` matches committed file (exit 0) |
| hive frontend `npm ci && npm run lint && npm run build` | 0 errors (94 pre-existing warnings), built ✓ |
| hive backend suite | 3768✓ 24s |
| suite inventory / test duplicates | ok / ok |

The 3 root-suite failures are exactly one root cause:
`test_check_reachability.py::test_baseline_matches_the_tree` and
`test_reachability_baseline_identity.py::{test_the_committed_baseline_passes_the_gate_it_now_carries,
test_the_baseline_is_exactly_the_unreachable_set}` all assert the committed
`quality/reachability-baseline.json` equals the tree's unreachable set; the
scan yields 169 vs the 168-row baseline because of `maistro.runs.admission_identity`.

## The one owner-held root cause (unchanged conclusion, now with full mechanism)

`maistro.runs.admission_identity` is #1851's deliberately unwired contract
leaf (`.cursor/context/repair-1851-9ddea59d.md`, committed on develop): scan
= 169 unreachable at BOTH base and head, baseline = 168 rows without it, so:

- `check-reachability.py` → exit 1 (the `Quality / Reachability` leaf);
- `check-ratchet-provenance.py` → its reachability consumer fails ("NEW
  unreachable module absent from trusted base and not previously authorized"),
  which reds `exact-debt-ledger` (its other two steps pass: `check-vulture-baseline.py`
  with CI's exact args → 1326 == 1326, exit 0; `check-shipped-surface-truth.py` → exit 0)
  and the `Quality gate` aggregate (which needs `quality-reachability`);
- the root-suite self-checks above → `test` job + Coverage-gate producer abort.

Not repairable in this branch, re-derived not assumed: `ratchet_provenance.load_authorizations`
reads `quality/ratchet-authorizations.json` **from the base revision**
(scripts/ratchet_provenance.py `load_authorizations` → `resolve_baseline(path,
base=trusted_ref.base_sha)`), so an in-branch grant is invisible (two-merge
wall), and the lane's ledger exception covers only the **vulture** ledger
(no vulture debt exists to amend — the scan banks exactly 1326 = 1326).
Wiring or deleting the leaf would violate #1851's contract (no fake callers,
no keep-alive imports). Owner fix path on develop: land the reachability
grant + baseline row for `maistro.runs.admission_identity` (two merges), or
land #1845's integration; after the next `origin/develop` sync-merge this
branch inherits green on all four remaining red checks.

## Residual (not re-run, branch has zero diffs there)

Canvas frontend npm steps (`test:ci`/`lint`/`build`/`audit`), the cross-suite
one-process step (runs `tests/`, so it cannot pass while the owner-held leaf
persists), and the full nine-producer coverage floor (needs MinIO built from
Go source; floor inputs byte-identical to develop per §2).
