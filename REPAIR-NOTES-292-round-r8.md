# REPAIR NOTES — issue #292, round r8 (job 19ed33d9919a4a43859fb3708d2041cc)

Head at dispatch: `29a683b4dcddc11266512002786594d14432555f`; base `e20e9f52ea94b393184f210cc9379f9f693f13d0`.
No code changed this round (see §5); this note records fresh verification evidence and one correction to earlier rounds' claims.

## 1. Driver checks at HEAD — all green

`check-0..4.log` in the job directory: `uv sync --locked --extra dev` ok; `ruff check .` ok;
`ruff format --check .` ok (3364 files); `pytest packages/hive-conductor/backend/tests/test_cli_contract.py -q -x`
→ **23 passed**; `check-suite-inventory.py --suite packages/hive-conductor/backend/tests` → 3815/3815 unique, matches inventory.

## 2. exact-debt-ledger (the only gate named for repair this round) — red, proven external

Executed this round at HEAD, CI's exact arguments:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  → **rc=0**: 1326 reviewed identities → 1326 findings, unclassified 0, never_allowlist 0.
  The vulture ledger is exact; the lane brief's permitted amendment (quality/vulture-baseline.json) has **zero scope** — there is nothing to add or remove.
- `uv run python scripts/check-ratchet-provenance.py` → **rc=1**, every leg green except one:
  `FAIL: ratchet provenance inventory is incomplete — check-reachability-provenance.py: trusted-base gate returned 1`.
- `uv run python scripts/check-reachability.py` → **rc=1**: 1418 production modules, 169 unreachable,
  sole NEWLY-unreachable identity: **`maistro.runs.admission_identity`** (168-row baseline).

### Root cause and ownership (fresh evidence, not inherited claims)

- The module's own docstring (`packages/maistro-core/src/maistro/runs/admission_identity.py:3-6`) declares it an
  **"inactive contract leaf"**: "Nothing in production imports it yet; a later, separately reviewed integration lands
  the runtime consumer". It belongs to issues #1851/#1859, not #292.
- The fix already exists: `origin/auto-1859` commit `43361b8ed` ("fix(#1859): publish the admission identity vocabulary
  from maistro.runs to green exact-debt-ledger") re-exports it via `maistro/runs/__init__.py`. Empirical proof:
  `git archive origin/auto-1859 | tar -x -C /tmp/auto1859-arch && check-reachability.py` there → **rc=0**
  (1417 modules, 168 unreachable). The fix is **not** in `origin/develop` and **not** in this branch.
- `git fetch origin develop` → origin/develop is **still `e20e9f52ea94`** (unchanged since the lane base);
  `git merge-base HEAD origin/develop` = `e20e9f52ea94`, `git rev-list --count origin/develop ^HEAD` = 0.
  **No develop-sync conflict exists and no merge is available that would carry the fix.**

### Why no in-lane repair is possible (each bar re-verified this round)

1. Banking the row in `quality/reachability-baseline.json` cannot work: `scripts/ratchet_provenance.py:305-350`
   (`resolve_baseline`) reads every ledger from the **merge-base commit**, so a candidate-side edit is never the
   trusted base. Re-read in this round's tree.
2. Wiring the module from this lane to fake reachability is gate-gaming against that module's own contract
   (r5 §2 still applies).
3. Duplicating auto-1859's 12-line publication fix here guarantees a conflicting double-landing of another lane's
   reviewed change; removing the module destroys #1851/#1859's deliberate leaf and its tests
   (`packages/maistro-core/tests/runs/test_root_admission_identity.py`).

Conclusion: the gate is red for **every** branch cut from develop `e20e9f52ea94` — including develop's own tip —
until auto-1859 merges to develop and PR #2223 re-evaluates against the updated target. Integrator action, not lane action.

## 3. Correction to r4–r7 claims

Earlier rounds reported `git diff --name-only <base>..HEAD -- 'packages/*/src'` as empty ("no production diff").
That was a **pathspec artifact**: hive-conductor uses `backend/`/`frontend/`, not `src/`. The branch's true production
delta vs base is `packages/hive-conductor/backend/routes/cli.py`, **added** `packages/hive-conductor/backend/services/cli_commands.py`
(both in issue #292's scope), plus frontend files. `cli_commands.py` accounts for the 1417→1418 production-module count
and is reachable (imported by `routes/cli.py`; absent from the newly-unreachable list). The correction does not change
any verdict: the failing identity is still only `maistro.runs.admission_identity`.

## 4. Other CI legs named in the dispatch findings — still green or unmoved in-lane

Code frozen since r5 (`git diff --name-only ae1622fd1..HEAD` outside docs/notes = empty), so r5's executed evidence
binds to HEAD, and bandit was re-run fresh this round:

- `uv run bandit -r packages/hive-conductor/backend/routes/cli.py packages/hive-conductor/backend/services/cli_commands.py -ll`
  → **rc=0**, 0 issues at every severity/confidence.
- Diff-coverage leg: r5 §3 with CI's own producer (`coverage run --branch --source=packages/hive-conductor/backend -m pytest …`)
  → 3792 passed/23 skipped, `check-diff-coverage.py --base origin/develop` rc=0.
- Supply chain (pip-audit): `git diff <base>..HEAD -- uv.lock pyproject.toml` → empty; the branch cannot move that gate.

## 5. Changes this round

- `REPAIR-NOTES-292-round-r8.md` (this file). No source, test, ledger, or doc changes; no inventory delta
  (no test added or removed — `check-suite-inventory` still reports the recorded 3815).

## 6. Residual risk / handoff

The lane cannot demonstrate exact-debt-ledger green. Required sequence: #1859's lane lands auto-1859 → develop absorbs
it → PR #2223 re-evaluates (merge-base moves past `e20e9f52ea94`, the trusted base then contains the publication,
reachability returns to 168, provenance leg greens). Everything else about the lane is proven green at this head.
