# REPAIR-NOTES-292-round-r5.md

CI-repair round 5 for issue #292 (`auto-292`). Head at start and end of the
code work: `0d847f20a8bf45680d9dab461f1fa30b3705976a`; base `e20e9f52ea94`
(origin/develop, re-fetched this round, unchanged; `git merge-base --is-ancestor
e20e9f52ea94 HEAD` -> true, so there was no sync conflict to resolve).

Assigned gate: `exact-debt-ledger` (`.github/workflows/vulture-ratchet.yml`).
Nothing from r2/r3/r4 was taken on faith: every claim below was re-derived by
executing a command at this head.

## 1. What the assigned job actually runs

`.github/workflows/vulture-ratchet.yml:30` job `exact-debt-ledger` runs three
steps in order: `scripts/check-ratchet-provenance.py`, then
`scripts/check-shipped-surface-truth.py`, then
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'`.

Executed this round:

| Step | Result |
| --- | --- |
| `uv run python scripts/check-ratchet-provenance.py` | **rc=1** — only the `reachability` leg fails (`maistro.runs.admission_identity`) |
| `uv run python scripts/check-shipped-surface-truth.py` | rc=0 — "Shipped-surface truth matrix is complete." |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0 — `1326 reviewed identities -> 1326 findings`, `unclassified: 0`, `never_allowlist: 0` |

So the vulture ledger half — the half this round is permitted to amend — is
already exact. There are **no unbanked vulture identities**, and
`quality/vulture-baseline.json` at develop already banks the five
`admission_identity` rows (`git show e20e9f52ea94:quality/vulture-baseline.json
| grep -c admission_identity` -> 5). Nothing to bank, nothing to remove;
amending it would only make a green half red.

## 2. The red leg, reproduced on develop's own tree (new evidence this round)

Previous rounds argued develop-inheritance from history and diffs. This round
runs the gate on develop's content alone, with no worktree contamination:

```
git archive e20e9f52ea94 | tar -x -C /tmp/dev-base-292
cd /tmp/dev-base-292 && <worktree venv>/python scripts/check-reachability.py
-> 1417 production modules, 169 unreachable from any entry point
   1 module(s) are NEWLY UNREACHABLE:
     maistro.runs.admission_identity  (maistro.runs.admission_identity)
   rc=1
```

develop's committed `quality/reachability-baseline.json` holds 168 rows
(`git show e20e9f52ea94:quality/reachability-baseline.json | grep -c
admission_identity` -> 0). develop's tip therefore fails the reachability
ratchet **against its own content**, before this branch is involved. The
worktree scans 1418 modules (develop 1417 + this branch's
`@flat/hive-conductor/services.cli_commands`) and reports the identical 169
unreachable set — the branch's one added module is reachable, so the branch
contributes no debt of its own.

Supporting facts, all re-checked:

- `git diff --name-only e20e9f52ea94..HEAD -- 'packages/*/src'` -> empty; the
  branch touches no `packages/*/src` Python (only hive-conductor
  `backend/routes/cli.py`, `backend/services/cli_commands.py`, frontend
  `.ts/.tsx`, tests, docs, and two ledgers that are not the reachability one:
  `git diff --stat e20e9f52ea94..HEAD -- quality/` names only
  `frontend-typed-client-baseline.json` and `shipped-surface-truth.json`).
- `git grep -n admission_identity -- '*.py'` (excluding the module and its own
  test) -> no importer anywhere in the tree, at base or at head.
- `git show e20e9f52ea94:quality/ratchet-authorizations.json | grep -c
  admission_identity` -> 0, and authorizations are read from the merge base
  (`ratchet_provenance.load_authorizations(base=trusted_ref.base_sha)`), so a
  candidate cannot authorize the row it would bank (the two-merge rule).
- The same root cause reds the other jobs listed at `2b0e92e77651`:
  `RATCHET_BASE_REV=origin/develop REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run
  pytest tests/test_reachability_baseline_identity.py
  tests/test_check_reachability.py -q` -> **3 failed, 36 passed**, each failure
  naming `maistro.runs.admission_identity`
  (`::error title=New unreachable modules::maistro.runs.admission_identity`).

In-lane "fixes" remain rejected on the same evidence as r2–r4: importing the
inactive leaf from the CLI surface is gate-gaming against that module's own
contract ("a later, separately reviewed integration lands the runtime
consumer"); pulling in draft PR #2178 is another lane's unreviewed work; and
banking the row here still fails the authorization half.

## 3. Other CI legs named in the previous findings, re-checked in-lane

- **Coverage gate (publish-set floor + diff coverage).** The diff-coverage half
  was measured this round with CI's own producer command for this package:
  `uv run coverage run --branch --source=packages/hive-conductor/backend -m
  pytest packages/hive-conductor/backend/tests --timeout=30 -q` -> **3792
  passed, 23 skipped in 229.58s**; plus `--source=scripts` over
  `tests/test_check_enumerations.py tests/test_check_diff_coverage.py` -> 30
  passed. `uv run python scripts/check-diff-coverage.py <xml> --base
  origin/develop` -> **rc=0**: "3 changed file(s) measured ... ok: every
  measured file this change touches is at or above 90% lines / 80% branch
  arcs" (`routes/cli.py`, `services/cli_commands.py`, `scripts/
  check_enumerations.py`). The earlier red line on `scripts/
  check_enumerations.py` appears only when the root `--source=scripts`
  producer is omitted — a local-measurement artifact, not branch debt.
- **security (SAST / Bandit).** CI's exact invocation scoped to the files this
  branch changes: `bandit -r packages/hive-conductor/backend/routes/cli.py
  packages/hive-conductor/backend/services/cli_commands.py -ll
  --confidence-level=medium` -> 0 issues at every severity/confidence.
- **Supply chain (pip-audit).** `git diff --name-only e20e9f52ea94..HEAD -- uv.lock
  pyproject.toml 'packages/*/pyproject.toml'
  packages/hive-conductor/backend/requirements.txt` -> empty; the branch changes
  no dependency or lock file, so it cannot move that gate.

## 4. #292 acceptance criteria (re-verified against the tree, not prior claims)

- Contract defined — `docs/architecture/CONDUCTOR-CLI-PAGE-CONTRACT.md`
  classifies the page as a *limited operational console*, lists the
  five-command set, the authorization model (AuthMiddleware, read-only
  introspection, no elevated scope added or bypassed), and the relationship to
  backend CLI sessions.
- Every exposed command executes through a registered capability —
  `packages/hive-conductor/backend/services/cli_commands.py:45` `cli_registry`
  is the single authority read by the exec route
  (`routes/cli.py:92`, manifest), `GET /v1/cli/commands`, and `help`.
- Unsupported commands fail explicitly, never simulated —
  `routes/cli.py:143-159` answers 404 `unsupported_command` and audits
  `severity="warning"`; `CLI.tsx:25-49` `failureLines` renders only states the
  backend answered with (its sole command literal is `BOOT_COMMAND =
  "hctl status"`).
- I/O audited, sanitized, policy-bounded — `log_audit(action="cli_exec")` on
  ok/unsupported/unknown_session/timeout/refused/error paths
  (`routes/cli.py:143-236`); `sanitize_cli_output` strips control characters and
  caps 200 lines x 1000 chars (`cli_commands.py:62-80`); input is name-matched,
  bounded to 200 chars by the request model.
- Reconnect/refresh preserve real state — server-side history
  (`_append_history`, bounded 50, `routes/cli.py:112`) restored on boot
  (`CLI.tsx:96-126`); pinned by `test_session_history_persists_for_reconnect_
  and_refresh` and the e2e case at `tests/e2e/cli-page.spec.ts:234`.
- E2E covers every shipped command plus unauthorized/unsupported/timeout/
  backend-unavailable — `packages/hive-conductor/tests/e2e/cli-page.spec.ts`
  drives the UI from `GET /v1/cli/commands` (manifest-driven) and is collected
  by the CI e2e service
  (`docker-compose.test.yml:98`: `npx playwright test
  --config=tests/e2e/playwright.config.ts`). Not executed in this lane (needs
  the compose stack + browsers); covered by the CI e2e job.
- Machine-readable frontend/backend compatibility test —
  `backend/tests/test_cli_contract.py:212
  test_frontend_command_surface_matches_the_backend_manifest` reads the shipped
  `CLI.tsx` statically and fails on an unregistered command literal or on any
  `/v1/...` path outside `/v1/cli`.
- No hard-coded-output-only command — the page renders `data.lines` from the
  backend response or the session's durable history; every registry handler
  delegates to a live capability (`cli_commands.py:_status_lines`,
  `_agents_lines`, `_health_lines`, `_sessions_lines`, `_help_lines`).

One documentation/code asymmetry noticed while reading (pre-existing, not
introduced by this round, not an acceptance criterion): the contract doc's
execution-path step 3 says timeout/refusal/crash "each lands in the session's
durable trail", while the 503 `backend_unavailable` branch
(`routes/cli.py:213-224`) audits but does not call `_append_history`. Left
unchanged deliberately — amending it is a behavior change outside a CI-repair
round and would need its own test; recorded here for the owner.

## 5. Conclusion

#292's implementation is complete and green on every gate this lane can run.
The `exact-debt-ledger` red — and the same-root-cause `test`,
`Quality / Reachability`, `Quality gate (Pillars…)`, and coverage-job legs — is
reproducibly red on develop's own tip `e20e9f52ea94` and is not reachable from
candidate code or candidate ledgers under the two-merge rule. The prepared
owner fix still exists on `auto-881` at `fe80d4c55` (reachability baseline row,
reachability disposition, convergence-matrix census) and still has not landed
on develop; it requires the grant to land on develop first.

No code, ledger, or grant edit belongs in this lane; this round adds only these
notes.
