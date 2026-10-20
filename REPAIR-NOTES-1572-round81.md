# Repair notes — #1572 round 81 (job 0d50f66c3f104b029ef9f2ce84b79238)

Dispatch head `c00db300a3659f49b1edf9f079ef48f3a32edddd`, develop base `3c761d14db94`.
Round verdict: **BLOCKED on the external execution-lifecycles grant** — unchanged conclusion,
this round re-proves it first-hand at the current tree and corrects the simulation recipe.

## 1. External state re-check (fresh this round)

- `git fetch origin develop`: tip **unchanged** — `origin/develop` = `3c761d14db94` = merge-base
  (branch 182 ahead; no sync conflict exists).
- `git grep GoalStatus origin/develop -- quality/` → **0 matches**: develop carries no
  GoalStatus ledger entry and no grant.
- `git ls-remote`: PR #1938 head still `2f5dd46969fc` (open, unmerged; `gh api` confirms
  `merged_at: null`). `2f5dd4696` is an **ancestor of this branch** — the in-branch grant commit
  cannot authorize its own change (see §3).

## 2. Blocking gate at HEAD, exact CI argv

`uv run python scripts/check-execution-lifecycles.py` (quality.yml:1541):

```
ratchet: execution-lifecycles  [python ast, metric v3]
  baseline: base 3c761d14db94
  candidate: c00db300a365
  19 classified lifecycles  ->  20 discovered lifecycles
FAIL
  - maistro.goals.model::GoalStatus: NEW work-state vocabulary is absent from the trusted
    base and has no already-landed authorization
EXIT=1
```

`uv run pytest tests/test_check_execution_lifecycles.py -q` → **1 failed / 28 passed**
(`test_the_shipped_ledger_matches_the_shipped_code`, gate-identical stdout) — the merge-queue
`test: failure` is this, 1:1. Sole failure; nothing else in the file or the gate output.

## 3. Why no in-branch repair exists (re-derived from source)

- The issue mandates the lifecycle itself: "Goal lifecycle: e.g. active, satisfied, cancelled,
  failed, superseded. Transitions are compare-and-set … Terminal states are final." Any
  implementation of that contract is a new work-state identity; renaming or removing
  `GoalStatus` would dodge the detector or delete mandated behavior — both prohibited.
- The gate accepts a newly discovered identity only if (a) it is in the base ledger, (b) its
  source is visible at base (`_discover_at_revision`), or (c) a grant exists — and grants are
  read from the **merge base**: `ratchet_provenance.load_authorizations(RATCHET,
  base=trusted_ref.base_sha)` (check-execution-lifecycles.py:773;
  `_unauthorized_additions` :704-707 also rejects candidate-ledger self-classification).
- `RATCHET_BASE_REV=HEAD` is refused (`_refuse_self_reference`,
  ratchet_provenance.py:258-275). No legitimate in-branch path exists — the repo's own rule:
  a floor raise takes two merges; land the grant first.

## 4. NEW this round: corrected simulation methodology + fresh proof pair

**Correction to round-77's recipe.** `resolve_baseline` reads the ledger at
`merge-base(base_sha, HEAD)` (ratchet_provenance.py:314-315). `RATCHET_BASE_REV` must therefore
name an **ancestor of HEAD**; pointing it at a sibling commit (SIM1 alone) silently degrades to
develop — re-derived the hard way this round (two runs both showed `baseline: 3c761d14db94`).
The candidate tree must be re-parented onto the grant commit.

Recipe (plumbing only; no branch/worktree mutations, scratch worktree removed after):

```
SIM1 69e48ef46  = develop + grant-only (+6/−1 quality/ratchet-authorizations.json, PR #1938 hunk)
SIM2 99b078f88  = git commit-tree <c00db300 tree> -p 69e48ef46   (current tree, re-parented)
git worktree add --detach /tmp/maistro-sim-g1572 99b078f88
```

Results at the **current** candidate tree:

| run (cwd = SIM2 worktree) | baseline used | result |
|---|---|---|
| `RATCHET_BASE_REV=69e48ef46` gate | 69e48ef46 (develop+grant) | **EXIT 0** — `authorized: maistro.goals.model::GoalStatus … OK: 20 work-state vocabularies, all classified (3 CANONICAL, 8 CONVERGE, 7 DOMAIN, 2 PROJECTION)` |
| `RATCHET_BASE_REV=69e48ef46` `pytest tests/test_check_execution_lifecycles.py` | 69e48ef46 | **29 passed, 0 failed** |
| `RATCHET_BASE_REV=3c761d14db94` gate (control, identical tree) | 3c761d14 (plain develop) | **EXIT 1** — same sole GoalStatus finding |

The pair proves the grant row is the only variable: **once the grant lands on develop, this
branch passes the blocking gate and the failing test with zero branch edits.**

## 5. Lane-brief vulture CI-repair exception — no target

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` (exact quality.yml argv): **EXIT 0**, `1323 reviewed identities -> 1323
findings`, zero unbanked rows. The permitted ledger amendment has nothing to amend.

## 6. Issue acceptance re-executed at HEAD (first-hand)

- Goals conformance suite: `pytest packages/maistro-core/tests/goals -q` → **48 passed /
  22 skipped** (skips are the PG legs; proven green on fresh pg17+pg18 in rounds 76/80 with
  `MAISTRO_REQUIRE_PG_LEGS=1`). Covers round-trips, append-only revisions/CAS, stale refusal,
  terminal-final, subgoal lineage + recorded agent transition, two-principals isolation
  (foreign == missing), immutable run binding, restart readback, Container wiring.
- SQLite/Alembic schema parity: `pytest
  packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -q` → 1 passed /
  1 skipped.
- Convergence freeze at CI argv (formal-conformance.yml:77):
  `check-m1-convergence-freeze.py --base 3c761d14db94` → **EXIT 0**, "no unapproved new
  architecture island" (AC: no `GoalRun`/`OrchestratorRun`/second executor/product-private
  Goal lifecycle).
- Production composition, source-read: `container.py:44` imports `wire_goal_store`, :2414 wires
  it inside `create_container`, :271-286 exposes the authorized `goal_reader` seam;
  shipped compositions call it — `maistro_server/main.py:344` and
  `hive-conductor/backend/adapters/maistro_core.py:148`.
- Driver logs at this head (job dir check-*.log): sync ok, ruff check clean, 3288 files
  formatted, 161 passed / 28 skipped, suite inventory 16334 ok.
- Known **local-only** artifact (not a branch defect): untracked gitignored
  `quality/ac-state.json` (.gitignore:81) trips
  `test_every_quality_json_state_surface_is_classified_once` via unconditional rglob
  (check-branch-independence.py:206); CI passes it. Left untouched.

## 7. External action required to unblock (maintainer)

Land the **grant-only** commit on develop — the `quality/ratchet-authorizations.json` hunk of
`2f5dd4696` (stand-alone as SIM `69e48ef46`, +6/−1, owner `@BlakeMatthews-dev`, issue #1572) —
e.g. by merging a grant-first PR or restructuring #1938 into grant + implementation. After that:
gate EXIT 0 and tests 29/29 (proven in §4), zero branch edits, no rebase required (merge-base
becomes the grant-carrying develop tip).

No code, test, ledger, or gate changes were made this round; this file is the only edit.
No inventory delta (no tests added or removed).
