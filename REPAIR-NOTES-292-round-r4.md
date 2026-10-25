# REPAIR-NOTES-292-round-r4.md

CI-repair verification for issue #292 (`auto-292`), lane L292, at head
`5be36e9bf11a1b33f08b78d329d58b44c86add3a`, base `e20e9f52ea94b393184f210cc9379f9f693f13d0`
(origin/develop, re-fetched this round and unchanged: `git rev-parse origin/develop`
-> `e20e9f52ea94`).

Assigned gate: `exact-debt-ledger` (vulture-ratchet.yml). Prior block: r3's
NEEDS-DEEP-REVIEW escalation of the reachability residual. This round re-derived
every claim fresh at the current head; nothing from r2/r3 was assumed.

## 1. All lane-reachable gates are green at `5be36e9bf` (re-run this round)

- `uv run ruff check .` -> All checks passed! (driver check-1 + re-run)
- `uv run ruff format --check .` -> 3364 files already formatted (driver check-2)
- `uv run pytest packages/hive-conductor/backend/tests/test_cli_contract.py -q` -> 23 passed (driver check-3)
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` -> ok, 3815 node IDs (driver check-4)
- `uv run pytest packages/hive-conductor/backend/tests -q` -> **3792 passed, 23 skipped** (fresh, 200s)
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  (CI's exact arguments) -> **exit 0**: `1326 reviewed identities -> 1326 findings`,
  `unclassified: 0`, `never_allowlist: 0`. The vulture half of the job is GREEN;
  there are no unbanked identities, so the round's permitted
  `quality/vulture-baseline.json` amendment has nothing to act on. The five
  `admission_identity.py::unused variable` rows at
  `quality/vulture-baseline.json:283-287` are develop-banked and still
  scan-true; removing them without eliminating the findings would turn the
  green half red, so the ledger is correctly left untouched.
- `check-shipped-surface-truth.py`, `check_enumerations.py`,
  `check-frontend-api-routes.py`, `check-frontend-typed-client.py`,
  `check-compliance.py`, `check-api-route-contracts.py`,
  `check-cross-package-imports.py`, `check-merge-markers.py` -> all exit 0.

## 2. #292 acceptance criteria re-verified against the tree (not prior claims)

- Contract defined: `docs/architecture/CONDUCTOR-CLI-PAGE-CONTRACT.md` —
  classification "limited operational console", the five-command set, the
  authorization model (AuthMiddleware; read-only introspection; no elevated
  scope added or bypassed), and the relationship to backend CLI sessions.
- Every command executes through a registered backend capability:
  `services/cli_commands.py::cli_registry` is the single authority; the exec
  route, the manifest route (`GET /v1/cli/commands`), and the page's `help`
  all read it (`routes/cli.py`).
- Unsupported commands fail explicitly: `routes/cli.py` answers 404
  `unsupported_command`, audited `severity=warning`; `CLI.tsx::failureLines`
  renders backend statuses only — no fabricated output anywhere (its sole
  hard-coded command literal is the boot command `hctl status`).
- Audited/sanitized/policy-bounded: `log_audit(action="cli_exec", ...)` on
  every path including refusals (unsupported, unknown_session, timeout,
  refused, error); `sanitize_cli_output` strips control chars and caps
  200 lines x 1000 chars; input is name-matched only, bounded to 200 chars.
- Reconnect/refresh preserve real state: server-side session history
  (`_append_history`, bounded 50) restored on boot; e2e pins
  "refresh restores the session's real history from the backend".
- E2E covers every shipped command (manifest-driven) plus unauthorized,
  unsupported, timeout, backend-unavailable, unreachable-transport, and
  failed-recovery states: `tests/e2e/cli-page.spec.ts` (the CI-owned suite)
  and `backend/tests/test_cli_contract.py` (23 tests, incl. the
  machine-readable `test_frontend_command_surface_matches_the_backend_manifest`
  compatibility test that statically holds `CLI.tsx` to the manifest and to
  `/v1/cli/*`-only paths).

## 3. The exact-debt-ledger failure: reachability leg, develop-inherited — proven

`uv run python scripts/check-ratchet-provenance.py` fails on exactly one leg:

```
ratchet: reachability ... 168 unreachable modules -> 169 unreachable of 1418 modules
FAIL: reachability ratchet moved away from trusted state
  - maistro.runs.admission_identity: NEW unreachable module absent from trusted base and not previously authorized
  - maistro.runs.admission_identity: current unreachable module missing from candidate baseline
```

Every other leg (promotion-surface 74->74, dispositions 168->168,
shell-execution 3->3, contract-markers 358->358, enumerations 1->1,
lifecycle 0->0, vulture 1326->1326) is OK.

Evidence that this red is not this branch's and cannot be fixed in it:

1. `git diff --stat e20e9f52ea94..HEAD -- packages/maistro-core` is **empty** —
   the branch changes zero maistro-core files.
2. `git grep admission_identity e20e9f52ea94 -- packages/*/src` is **empty** —
   nothing imports the module at the base either; it is unreachable there too.
3. The module exists at the base (`git cat-file -e` OK): it landed at develop's
   tip itself via the #1936 merge (`e20e9f52ea94` = "Merge pull request #1936
   from Agent-StrongHold/auto-1851"), i.e. develop's own tip is red on its own
   gate (169 unreachable scanned vs 168 banked).
4. **New this round (pickaxe):** `git log -S "maistro.runs.admission_identity"
   e20e9f52ea94 -- quality/reachability-baseline.json` returns **no commits** —
   the row was never banked anywhere in develop's history; the #1851 leaf
   merged with the reachability half unbanked (its own notes,
   `docs/testing/inventory-notes/task-admission-identity-types.md:119,148,224`,
   record the same rc=1 on its branch).
5. `quality/ratchet-authorizations.json` at the base has zero
   `admission_identity` entries, and grants are read **from the merge base**
   (`ratchet_provenance.load_authorizations`), so no branch-side edit can
   authorize the row (the two-merge rule; r2 additionally proved the negative
   experimentally: banking the row locally turns `check-reachability.py` green
   but `check-reachability-provenance.py` still fails).
6. `RATCHET_BASE_REV=origin/develop REQUIRE_AUTH=false MAISTRO_DRY_RUN=1
   uv run pytest tests/test_reachability_baseline_identity.py
   tests/test_check_reachability.py -q` -> **3 failed, 36 passed**, every
   failure naming `maistro.runs.admission_identity`
   (`::error title=New unreachable modules::maistro.runs.admission_identity`) —
   this is precisely the ci.yml `test`-gate failure listed for
   `2b0e92e77651`, same root cause. The "Quality gate (Pillars 1–4, 7, 8)"
   failure is the aggregate job requiring Quality/Reachability to succeed.

In-lane fix options, each rejected on evidence:

- **Wire the module**: contradicts its own contract — `admission_identity.py`
  declares it "an inactive contract leaf ... a later, separately reviewed
  integration lands the runtime consumer ... before these types become
  reachable". No #292 surface legitimately consumes root-admission identity
  types; an import added only to flip the scanner is cosmetic gate-gaming.
- **Merge the integration**: the wiring lives in draft PR #2178
  (`origin/fix/1845-generation-integration-20261017`, commit `07911f7a2`,
  self-described "Draft #1845 integration proposal; NOT MERGE-READY",
  7,373 insertions across tasks/pg_admission/queue/runner). Pulling another
  lane's unreviewed draft into a #292 CLI-page PR is not a sanctioned repair.
- **Bank the row / add a grant here**: fails the authorization half regardless
  (proof in 5 above), and reachability-baseline/grant edits are outside this
  round's permitted exception (vulture-baseline only).
- **Delete the module**: would remove develop's #1851 deliverable and break
  `packages/maistro-core/tests/runs/test_root_admission_identity.py`.

Owner path (unchanged from r2/r3, still not landed): the prepared fix is on
`auto-881` (`fe80d4c55`: baseline row + `quality/reachability-dispositions.json`
LIBRARY group + convergence-matrix census row) and requires the owner to land
the grant on develop first (two-merge rule), or to land the #1845 integration
(PR #2178) which makes the module reachable. `origin/develop` was re-fetched
this round and is still `e20e9f52ea94` — neither has landed.

## 4. Conclusion

The #292 work itself is complete and green on every gate this lane can run;
the merge-queue red (`exact-debt-ledger`, plus the same-root-cause `test`,
`Quality/Reachability`, and aggregate Pillars/coverage jobs) is inherited from
develop's tip and requires the develop-side sequence above. No code, ledger,
or grant edit belongs in this lane; this round adds only these notes.
