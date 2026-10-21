# REPAIR-NOTES-292-round-r6.md

CI-repair round 6 for issue #292 (`auto-292`). The previous in-flight attempt
(`0c5495ea`) was rate-limited before producing any output, so **nothing from
r2–r5 is taken on faith**: every claim below is re-derived by executing a
command at this head `ae1622fd1665` against a base of `e20e9f52ea94`
(origin/develop, re-fetched this round, unchanged; `git merge-base --is-ancestor
e20e9f52ea94 HEAD` -> true, so no sync conflict to resolve).

Assigned gate: `exact-debt-ledger` (`.github/workflows/vulture-ratchet.yml:30`),
which runs three steps in order: `scripts/check-ratchet-provenance.py`, then
`scripts/check-shipped-surface-truth.py`, then
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'`.

## 1. Exact-debt-ledger steps, freshly executed

| Step | Command | Result |
| --- | --- | --- |
| 1 (provenance) | `uv run python scripts/check-ratchet-provenance.py` | **rc=1** — only the delegated `reachability` leg fails; every other ratchet leg (adr-status-language, citation-status, promotion-surface, reachability-dispositions, shell-execution, contract-markers, enumerations, lifecycle) is OK. The failing identity is `maistro.runs.admission_identity` ("NEW unreachable module absent from trusted base and not previously authorized"; "current unreachable module missing from candidate baseline"). |
| 2 (shipped truth) | `uv run python scripts/check-shipped-surface-truth.py` | rc=0 — "Shipped-surface truth matrix is complete." |
| 3 (vulture) | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0 — `1326 reviewed identities -> 1326 findings`, `unclassified: 0`, `never_allowlist: 0`. |

**The vulture ledger half — the half this round is permitted to amend — is
already exact.** There are **no unbanked vulture identities**, and
`quality/vulture-baseline.json` at the base already banks the five
`admission_identity` rows (`git show e20e9f52ea94:quality/vulture-baseline.json
| grep -c admission_identity` -> 5). Nothing to bank, nothing to remove; amending
`vulture-baseline.json` would only break a green half.

## 2. The red leg is develop-inherited (proven on develop's own content)

`check-reachability.py` resolves ROOT from `__file__` and reads develop's own
`quality/reachability-baseline.json`, so running it inside an extract of develop
is a clean develop-vs-develop test with no worktree contamination:

```
rm -rf /tmp/dev-base-292 && mkdir -p /tmp/dev-base-292
git archive e20e9f52ea94b393184f210cc9379f9f693f13d0 | tar -x -C /tmp/dev-base-292
cd /tmp/dev-base-292 && python3 scripts/check-reachability.py
-> 1417 production modules, 169 unreachable from any entry point
   1 module(s) are NEWLY UNREACHABLE:
     maistro.runs.admission_identity  (maistro.runs.admission_identity)
   rc=1
```

develop's committed `quality/reachability-baseline.json` holds **168** rows and
**0** `admission_identity` rows (`git show
e20e9f52ea94:quality/reachability-baseline.json | grep -c admission_identity` ->
0). develop's own tip therefore fails the reachability ratchet **against its own
content**, before this branch is involved.

Supporting facts, all re-checked:

- `git diff --name-only e20e9f52ea94..HEAD -- 'packages/*/src'` -> empty; the
  branch changes no `packages/*/src` Python.
- `git diff --stat e20e9f52ea94..HEAD -- quality/` names **only**
  `frontend-typed-client-baseline.json` and `shipped-surface-truth.json` — no
  edit to `vulture-baseline.json`, `reachability-baseline.json`, or
  `ratchet-authorizations.json`.
- `git show
  e20e9f52ea94:quality/ratchet-authorizations.json | grep -c admission_identity`
  -> **0** grants at the base.
- The worktree scans **1418** modules (develop 1417 + this branch's one added
  module `maistro-canvas` -> no: the branch's one added module is
  `@flat/hive-conductor/services.cli_commands`) and reports the identical 169
  unreachable set — the branch's one added module is reachable, so the branch
  contributes **no debt of its own**.

## 3. The lane cannot repair this red (two-merge rule, proven from code)

`scripts/ratchet_provenance.py:600-629` `load_authorizations` reads grants from
`{baseline.base_sha}:{path.name}`, and `resolve_baseline`
(`:246-350`) sets `base_sha` to `_git("merge-base", base_sha, "HEAD")` — i.e.
**the merge-base commit (develop e20e9f52ea94), not the candidate worktree**.
Because the base carries 0 `admission_identity` grants, a candidate-side grant
added in this branch is never read, and banking the reachability row in this
branch still fails the authorization half. This is exactly the two-merge rule
documented in `.cursor/AGENTS.md` ("a grant never authorizes the change that
introduces it… land the grant first, then the change").

The module's own contract
(`packages/maistro-core/src/maistro/runs/admission_identity.py` docstring)
declares it an *inactive contract leaf* whose "runtime consumer" lands in "a
later, separately reviewed integration" (draft PR #2178); the prepared owner
repair still exists on `auto-881` at `fe80d4c55` (reachability baseline row,
reachability disposition, convergence-matrix census) and has not landed on
develop. So in-lane "fixes" remain rejected on the same grounds as r2–r5:

- wiring the inactive leaf into the CLI surface is gate-gaming against its own
  contract;
- pulling in draft PR #2178 is another lane's unreviewed work;
- banking the row locally turns `check-reachability.py` green but
  `check-reachability-provenance.py` still rc=1 (authorization reads the base).

## 4. #292 acceptance criteria (re-verified against the tree, not prior claims)

- ruff check: `All checks passed!`
- ruff format: `3364 files already formatted`
- Compatibility test: `uv run pytest packages/hive-conductor/backend/tests/test_cli_contract.py -q -x` -> **23 passed in 2.91s** (includes `test_frontend_command_surface_matches_the_backend_manifest`, the machine-readable frontend/backend surface contract).
- Shipped-surface truth: `uv run python scripts/check-shipped-surface-truth.py` -> rc=0.
- Manifest surfaces exist: `docs/architecture/CONDUCTOR-CLI-PAGE-CONTRACT.md`,
  `packages/hive-conductor/backend/routes/cli.py`,
  `packages/hive-conductor/backend/services/cli_commands.py`,
  `packages/hive-conductor/backend/tests/test_cli_contract.py`,
  `packages/hive-conductor/frontend/src/pages/CLI.tsx`,
  `packages/hive-conductor/frontend/src/lib/api.ts`,
  `packages/hive-conductor/tests/e2e/cli-page.spec.ts`,
  `packages/hive-conductor/frontend/e2e/cli-page.spec.ts`, `scripts/check_enumerations.py`.

Per r5 §4 for the detailed acceptance mapping (CLI page is a limited
operational console; every command runs through the registered `cli_registry`;
unsupported commands fail with 404 `unsupported_command` + audit, never
simulated; I/O sanitized/bounded; reconnect/history audited; e2e covers every
shipped command plus unauthorized/unsupported/timeout/unavailable). Not
re-executed here: the full Playwright e2e stack (needs compose + browsers) and
the 230s coverage run — both are CI jobs, out of this lane's local budget, and
not asserted by r5 either. One pre-existing doc/code asymmetry noted by r5
(contract step 3 vs the `backend_unavailable` 503 branch not calling
`_append_history`) is left unchanged — a behavior change outside a CI-repair
round.

## 5. Verdict

#292's implementation is complete and green on every gate this lane can run, and
the vulture ledger (the lane's only permitted amendment) is **exact** — there
is nothing in-lane to bank or remove. The `exact-debt-ledger` red, and the
same-root-cause `Quality / Reachability` / `test` / coverage-Pillars legs, is
**reproducibly red on develop's own tip `e20e9f52ea94`** (proven above) and is
not reachable from candidate code or candidate ledgers under the two-merge
rule. Resolution requires owner action on develop (land the grant + baseline
row from `auto-881`), which is outside this lane's vulture-only exception.

**Verdict: NEEDS-DEEP-REVIEW** — the lane's repair action is exhausted (vulture
is exact); the remaining gate failure is develop-inherited reachability debt
that the two-merge rule and the develop-side owner fix make unrepairable
in-lane.

No code, ledger, or grant edit belongs in this lane; this round adds only these
notes, committed locally without modifying behavior.
