# REPAIR-NOTES-292-round-r7.md

CI-repair round 7 for issue #292 (`auto-292`), re-run because the previous
in-flight attempt (`222e934566be…`, head `ae1622fd1665`) ended with a malformed
`MAISTRO_RESULT` line (`ValueError: invalid MAISTRO_RESULT JSON … char 43`)
rather than a verdict. Nothing from r2–r6 is taken on faith: every claim below is
re-derived by executing a command at this head `b3865b5bcf2a` against base
`e20e9f52ea94` (origin/develop, re-fetched this round, unchanged).

Assigned gate: `exact-debt-ledger` (`.github/workflows/vulture-ratchet.yml:30`),
which runs three steps in order — `check-ratchet-provenance.py`,
`check-shipped-surface-truth.py`, `check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'`.

No sync conflict: `git fetch origin develop` left `origin/develop` at
`e20e9f52ea94` (`git merge-base HEAD origin/develop` == `e20e9f52ea94`), so the
base is the merge-base and there is nothing to merge.

## 1. exact-debt-ledger, freshly executed at this head

| Step | Command | Result |
| --- | --- | --- |
| 1 (provenance) | `uv run python scripts/check-ratchet-provenance.py` | **rc=1** — only the delegated `reachability` leg fails; every other leg (promotion-path, reachability-dispositions, shell-execution, contract-markers, enumerations, lifecycle, …) is OK. The failing identity is `maistro.runs.admission_identity`. |
| 2 (shipped truth) | `uv run python scripts/check-shipped-surface-truth.py` | rc=0 — "Shipped-surface truth matrix is complete." |
| 3 (vulture) | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0 — `1326 reviewed identities -> 1326 findings`, `unclassified: 0`, `never_allowlist: 0`. |

**The vulture per-identity ledger — the only ledger this CI-repair round may
amend — is already exact.** There are no unbanked vulture identities and
`quality/vulture-baseline.json` is byte-for-byte the base's (the branch's only
`quality/` edits are `frontend-typed-client-baseline.json` and
`shipped-surface-truth.json`; `git diff --numstat origin/develop -- quality/`
names exactly those two). Amending it would break a green half.

## 2. The red leg is develop-inherited (proven on develop's own content)

`check-reachability.py` resolves ROOT from `__file__`, so running it in an
extract of the base commit is a clean develop-vs-develop test:

```
rm -rf /tmp/dev-base-292 && mkdir -p /tmp/dev-base-292
git archive e20e9f52ea94b393184f210cc9379f9f693f13d0 | tar -x -C /tmp/dev-base-292
cd /tmp/dev-base-292 && .venv/bin/python scripts/check-reachability.py
-> 1417 production modules, 169 unreachable from any entry point
   1 module(s) are NEWLY UNREACHABLE:
     maistro.runs.admission_identity  (maistro.runs.admission_identity)
   rc=1
```

develop's committed `quality/reachability-baseline.json` holds **168** rows and
**0** `admission_identity` rows, so develop's own tip fails the reachability
ratchet against its own content before this branch is involved. The same root
cause reproduces the three root-suite failures:

```
uv run pytest tests/test_reachability_baseline_identity.py tests/test_check_reachability.py -q
-> 3 failed, 36 passed
   ::error title=New unreachable modules::maistro.runs.admission_identity
   test_the_committed_baseline_passes_the_gate_it_now_carries
   test_the_baseline_is_exactly_the_unreachable_set
   test_check_reachability.py::test_baseline_matches_the_tree
```

## 3. The lane cannot repair this red (two-merge rule, from the code)

`scripts/check-reachability-provenance.py` computes
`added = current - trusted` and fails on
`unauthorized = [m for m in added if m not in authorized]`, where
`authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)` and
`resolve_baseline` (`scripts/ratchet_provenance.py:305-350`) sets `base_sha` to
the **merge-base** commit (`_merge_base`), not the candidate worktree. The base
carries 0 `admission_identity` grants
(`git show e20e9f52ea94:quality/ratchet-authorizations.json | grep -c
admission_identity` -> 0). So no candidate-side grant is read, and banking the
reachability row locally still leaves `added` non-empty and unauthorized. This
is the two-merge rule documented in `AGENTS.md`: land the grant first, then the
change. `git diff --name-only e20e9f52ea94..HEAD -- 'packages/*/src'` is empty, so
the branch contributes no debt of its own.

## 4. #292 acceptance criteria (re-verified against the tree, not prior claims)

- **Supported command set + authorization model + session relationship
  defined** -> `docs/architecture/CONDUCTOR-CLI-PAGE-CONTRACT.md` classifies the
  page a *limited operational console*; the registry authority is
  `packages/hive-conductor/backend/services/cli_commands.py:147 cli_registry`;
  `routes/cli.py` documents `AuthMiddleware` (401) and the CLI-session store.
- **Every exposed command executes through a registered backend capability**
  -> `routes/cli.py:90` manifest and `routes/cli.py:139` exec both read
  `cli_registry`; `CLI.tsx` renders only `data.lines`/restored history.
- **Unsupported commands fail explicitly, never simulated** ->
  `routes/cli.py:141-159` answers 404 `unsupported_command` audited
  `severity=warning`; `CLI.tsx:19-49` renders only backend-answered statuses.
- **I/O audited, sanitized, policy-bounded** -> `log_audit(action="cli_exec")`
  on ok/unsupported/unknown_session/timeout/refused/error
  (`routes/cli.py:141-236`); `sanitize_cli_output` strips control chars and caps
  200 lines × 1000 chars (`cli_commands.py:68-77`).
- **Reconnect/refresh preserve real state** -> `_append_history` bounded 50
  (`routes/cli.py:112`), restored in `CLI.tsx:99-126`.
- **E2E covers every shipped command + unauthorized/unsupported/timeout/
  backend-unavailable** -> `packages/hive-conductor/tests/e2e/cli-page.spec.ts`
  (manifest-driven per-command pass, unsupported 404, 401, 504, 503, transport
  failure, recovery, refresh); collected by the CI e2e service
  (`packages/hive-conductor/docker-compose.test.yml:80,98` ->
  `npx playwright test --config=tests/e2e/playwright.config.ts`). Spec
  execution itself UNVERIFIED in-lane (needs compose stack + browsers).
- **Machine-readable compatibility test** ->
  `backend/tests/test_cli_contract.py::test_frontend_command_surface_matches_the_backend_manifest`
  statically reads `CLI.tsx` and fails on unregistered command literals or
  `/v1` paths outside `/v1/cli`.
- **No hard-coded-output-only command** -> all five registry handlers delegate
  to a live capability; `help` renders from the registry itself.

Executed at this head: `uv run ruff check .` -> All checks passed!;
`uv run ruff format --check .` -> 3364 files already formatted;
`uv run pytest packages/hive-conductor/backend/tests/test_cli_contract.py -q`
-> **23 passed in 3.25s**; `uv run python scripts/check-suite-inventory.py
--suite packages/hive-conductor/backend/tests` -> ok (3815 identities, 0
duplicates); `check-shipped-surface-truth.py` -> rc=0.

One pre-existing doc/code asymmetry (recorded in r5, left unchanged): the
contract's execution-path step 3 says timeout/refusal/crash each land in the
durable trail, while the 503 `backend_unavailable` branch (`routes/cli.py:213-224`)
audits but does not call `_append_history`. Amending it is a behavior change
outside a CI-repair round and would need its own test.

## 5. Verdict

#292's implementation is complete and green on every gate this lane can run, and
the vulture per-identity ledger (the lane's only permitted amendment) is exact —
nothing to bank or remove. The `exact-debt-ledger` red, and the same-root-cause
root-suite failures, are **reproducibly red on develop's own tip `e20e9f52ea94`**
and are unreachable from candidate code or candidate ledgers under the two-merge
rule. Resolution requires owner action on develop (land the grant + baseline row
from `auto-881` at `fe80d4c55`), which is outside this lane's vulture-only
exception.

**Verdict: NEEDS-DEEP-REVIEW.**

No code, ledger, or grant edit belongs in this lane; this round adds only these
notes, committed locally without modifying behavior.
