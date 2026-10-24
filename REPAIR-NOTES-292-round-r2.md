# REPAIR-NOTES-292-round-r2.md

CI-repair round for issue #292 (`auto-292`), lane L292, base
`e20e9f52ea94b393184f210cc9379f9f693f13d0` (origin/develop).

Round scope: the merge-queue `test` failure, the preserved develop-sync merge
conflict, and the vulture per-identity ledger gate.

## 1. Develop sync — resolved and committed (`02fea0fab`)

The preserved conflict was a criss-cross merge against origin/develop. Two paths
were conflicted; both were resolved in place, in favour of this branch's side
(theirs), after diffing the two stages:

| Path | Resolution | Why |
|------|------------|-----|
| `packages/hive-conductor/tests/e2e/README.md` | theirs (branch side) | The stage-2/stage-3 diff showed the branch side is develop's side plus exactly one row (`cli-page.spec.ts`); develop adds no conflicting row. |
| `quality/frontend-typed-client-baseline.json` | theirs (branch side) | The scanner's `collect_violations()` on the merged tree returns exactly the branch's 189 entries (136 `hand_typed` + 53 `raw_fetch`). develop's three `raw_fetch::packages/hive-conductor/frontend/src/pages/CLI.tsx:10/11/12` rows are gone because `CLI.tsx` now calls `src/lib/api.ts`, so the candidate ledger is a subset of the trusted one: no new debt, no stale rows. |

## 2. The assigned `test` failure — the OpenAPI types step

`PR #2223`, CI run `39321005346`, job `test` (id `118294729609`) at head
`f7ca9d9e1` failed at the step "Generated API types match the backend's OpenAPI
document (#1048)": `types.gen.ts` was stale after a refusal-audit docstring
change. The repair commit `bde6aa4af` is verified at the merged HEAD:

```
uv run python scripts/dump-hive-openapi.py          # 237 paths / 141 schemas
npm --prefix packages/hive-conductor/frontend run gen:api   # openapi-typescript 7.13.0
git diff --stat -- packages/hive-conductor/frontend/src/api/types.gen.ts   # empty
```

`packages/hive-conductor/frontend/openapi.json` is gitignored
(`packages/hive-conductor/frontend/.gitignore:31`), so the dump leaves no
tracked residue.

## 3. vulture per-identity ledger — no amendment required

```
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
```

exit 0 — `1326 reviewed identities -> 1326 findings`, `unclassified: 0`,
`never_allowlist: 0`, `baseline: base e20e9f52ea94`, `candidate: 02fea0fab`.
Re-run with `RATCHET_BASE_REV=4588539cc` is also exit 0 with the same counts.
`quality/vulture-baseline.json` is therefore unchanged: this round eliminated no
identity, and the five `AdmissionAssessment` members
(`packages/maistro-core/src/maistro/runs/admission_identity.py:515-520`) were
already banked by develop at `quality/vulture-baseline.json:283-287`.

## 4. Live acceptance evidence (real HTTP, not TestClient)

The hive-conductor ASGI app was booted under uvicorn on a real TCP port
(`127.0.0.1:8199`, `CONDUCTOR_DATA_DIR` in a scratch directory), provisioned
through the public one-shot setup endpoint, and driven with a real session
cookie:

- `GET /v1/cli/commands` (authenticated) -> 200 and the machine-readable
  manifest `hctl status`, `hctl agents`, `hctl health`, `hctl sessions`, `help`.
- `POST /v1/cli/exec` for each of those five -> 200 with real backend output
  (8, 1, 67, 1 and 5 lines respectively).
- `POST /v1/cli/exec` unauthenticated -> 401 `Authentication required`;
  `GET /v1/cli/commands` unauthenticated -> 401.
- `POST /v1/cli/exec {"command": "hctl deploy --prod"}` -> 404
  `{"error": "unsupported_command", ...}` — no client-side simulation.
- `POST /v1/cli/exec {"command": "hctl rm -rf /"}` -> 404 and the session
  history length is unchanged (6 -> 6): a refusal is not a session event.
- `POST /v1/cli/exec {"session_id": "gone-after-reset"}` -> 404
  `{"error": "unknown_session", ...}`.
- Input bound: a 310-character command -> 422 `string_too_long`; `"hctl   status"`
  is normalized to `hctl status`.
- Output sanitization: `sanitize_cli_output` strips ANSI escapes, the bell and
  embedded CR/LF, and caps the result at 200 lines x 1000 characters.
- Audit: `GET /v1/audit` shows one `cli_exec` row per execution
  (`detail: {supported: true, session_id: default, outcome: ok, lines: N}`) and
  one `severity: warning` row per refusal (`supported: false`), each naming the
  acting principal.
- Session state: `GET /v1/cli/sessions` returns the durable server-side history
  with server timestamps, so a refresh or a reconnect replays real state.
- The shipped page (`packages/hive-conductor/frontend/src/pages/CLI.tsx`) calls
  only `/v1/cli/exec` and `/v1/cli/sessions` through `src/lib/api.ts`; it has no
  bare `fetch(`, and its only hard-coded command literal is the boot command
  `hctl status`.

## 5. Residual red — develop-side, owner-held, NOT repairable in this lane

`scripts/check-reachability.py` exits 1 in this tree and on a clean export of
develop itself:

```
1 module(s) are NEWLY UNREACHABLE:
  maestro.runs.admission_identity  (maestro.runs.admission_identity)
```

`packages/maistro-core/src/maistro/runs/admission_identity.py` is byte-identical
to develop and is imported only by its own test; its own docstring declares it
an "inactive contract leaf" whose runtime consumer lands with a later,
separately reviewed integration. The three root-suite failures
(`tests/test_check_reachability.py::test_baseline_matches_the_tree`,
`tests/test_reachability_baseline_identity.py::test_the_committed_baseline_passes_the_gate_it_now_carries`,
`tests/test_reachability_baseline_identity.py::test_the_baseline_is_exactly_the_unreachable_set`)
reproduce on a clean `git archive e20e9f52e` export, and origin/develop's own
push run (`39369230418` CI, `39369230464` Vulture Ratchet, `39369230401`
quality) is red for the same reason.

The fix is a develop-side ledger sequence, not a branch edit: the reachability
grant must land in the base before the candidate row can authorize it (the
two-merge rule), which was proven here — adding the row to
`quality/reachability-baseline.json` makes `scripts/check-reachability.py` exit
0, but `scripts/check-reachability-provenance.py` still fails with
"NEW unreachable module absent from trusted base and not previously authorized",
and adding a grant to `quality/ratchet-authorizations.json` in the same branch
does not help either, because `load_authorizations` reads the grant from the
merge base. The prepared fix is on branch `auto-881` (commit `fe80d4c55`:
baseline row + `quality/reachability-dispositions.json` LIBRARY group +
`docs/architecture/CONVERGENCE-MATRIX.md` census row); it needs the owner to
land the grant on develop first. This lane adds no ledger or grant edit, per
the round's hard prohibition.

## 6. Gates re-run at `02fea0fab`

`uv run ruff check .` (All checks passed), `uv run ruff format --check .`
(3364 files already formatted), `uv run pytest packages/hive-conductor/backend/tests/test_cli_contract.py -q`
(23 passed), the full `packages/hive-conductor/backend/tests` suite
(3792 passed, 23 skipped), `uv run pytest tests/ --ignore=tests/tools/registry -q`
(5393 passed, 138 skipped, 3 failed — the develop-side reachability rows above),
`scripts/check-suite-inventory.py` (21 suites, 32408 node IDs, 0 duplicates),
`scripts/check-frontend-typed-client.py`, `scripts/check-frontend-api-routes.py`,
`scripts/check_enumerations.py`, `scripts/check-workspace-retirement.py`,
`scripts/check-route-permissions.py`, `scripts/check-api-route-contracts.py`,
`scripts/check-public-routes.py`, `scripts/check-shell-execution.py`,
`scripts/check-test-duplicates.py`, `scripts/check-doc-links.py`,
`scripts/check-merge-markers.py`, `scripts/check-compliance.py`,
`scripts/check-promotion-surface.py`, `scripts/check-owned-store-access.py`,
`scripts/check-durable-table-inventory.py` — all exit 0. Frontend
`npm run lint` (0 errors, 93 warnings) and `npm run build` pass.
