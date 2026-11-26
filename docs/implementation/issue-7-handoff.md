# Issue #7 bounded implementation checkpoint

## Frozen scope

- Assignment: issue #7 only; branch `auto-7`; starting HEAD `d90b7afa41157afe42e63e602ea8cc7afbeceadc`; supplied develop base `7ba29c1cd0e45d0fa3ccc9cef807173e52b3c75d`.
- Evidence snapshot: `/home/dev/maistro/jobs/f3bbba4e05894a4985e8e5000423fee0/dispatch-context.json`. No remote enumeration or GitHub mutations.
- Initial worktree was clean. Existing committed lane work is preserved. No incoming uncommitted patch was necessary.
- This round will inspect and validate the salvaged Entra group-gated JIT provisioning slice (#492 in the milestone exit conditions), its production auth path, adjacent tests and governing ADRs. Candidate edit scope: Conductor backend auth/config/tests, corresponding inventory note, and this handoff. Other milestone capabilities are acceptance review only, not implementation scope for this bounded round.

## Prior-attempt diagnosis / ambiguities

- Supplied failure: provider HTTP 400 / tool calls cut off by max_tokens, with no new artifact. Strategy: smallest independently testable salvaged slice, no milestone-wide rewrite.
- Supplied prior result file is absent (`ENOENT`); not found, skipped.
- Job directory listing contains no `check-*.log` files; driver checks cannot be claimed.
- Issue #7 is a multi-initiative milestone, not a bounded implementation specification. Assumption: improve/prove the existing #492 slice and report all other exit conditions as unverified rather than claim milestone completion.
- Existing history includes rebuild repairs and broad changes relative to supplied develop base. Do not discard or silently certify that inherited diff.

## Progress

- Baseline targeted validation: `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py -x -q` — 22 passed (2.20s); log `/tmp/issue-7-jit-before.log`.
- Reachable production seam: `OAuthLoginService.__init__` builds the JIT provisioner from Settings; `authenticate` calls it only for verified, unlinked Entra identities. Existing policy limits new accounts to role `user` and configured permissions.
- Evidence-backed gap selected: `GraphMembershipResolver.resolve` forwards the login access token to an arbitrary `@odata.nextLink`, and treats non-string/blank next links as completed membership. This can disclose credentials to an unrelated allowlisted origin or admit on malformed partial evidence. Bound repair to validating Graph pagination and rejecting malformed continuations; add both resolver and real-login regression tests. No new auth authority or entitlement semantics.
- Relevant governance reviewed: ADR-080 (same-user memory is not scope widening), ADR-082226-5104 (PostgreSQL authority; Ladybug projections), ADR-068 (existing authorization/elevation substrate), and Proposed ADR-059 (OAuth authN yields the existing Hive session, not IdP-provided authZ). Reconciliation: existing administrator-configured group-to-permission JIT mapping is the issue's explicit extension of ADR-059's deferred optional map; this repair changes neither that mapping nor the accepted authorization model. Memory and execution authorities remain untouched.
- Regression demonstration: `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py -q -k 'untrusted_graph_pagination or invalid_continuations'` — **17 failed, 22 deselected** against unchanged production code. Includes all three real-login cases; log `/tmp/issue-7-pagination-red.log`.
- Repair: validate continuations against the HTTPS Graph origin and `/v1.0/me/transitiveMemberOf` subject endpoint before issuing another request. Reject malformed present continuations instead of considering partial evidence complete. Never echo continuation values into errors/audit.
- After repair: targeted suite **39 passed** (1.52s), including pre-existing paged success and page-limit refusal; log `/tmp/issue-7-jit-after.log`. Focused ruff check passed. Initial format check found the two touched files needed formatting; applied `uv run ruff format` to those files. Wider validation completed below.
- Implementation checkpoint committed locally: `2e257333c0` (`fix(#7): bind Entra JIT pagination to the authenticated subject`).

## Fresh validation (this round, not inherited claims)

All logs below are under `/tmp/issue-7-*`; no driver logs existed in the supplied job directory.

| Command | Result |
| --- | --- |
| `uv sync --locked --extra dev` | exit 0, resolved 468 packages |
| `uv run ruff check .` | exit 0, all checks passed |
| `uv run ruff format --check .` | exit 0, 3486 files formatted |
| `uv run pytest packages/hive-conductor/backend/tests -x -q` | exit 0, **3983 passed, 26 skipped**, 31 warnings, 211.72s |
| `uv run python scripts/check-release-consistency.py` | exit 0, released none / shipping 0.9.0 / target 1.0.0 |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` | exit 0, **4009** node IDs match inventory, no duplicate evidence |
| `uv run python scripts/check-reachability.py` | exit 0, 1460 modules / 152 unreachable |
| `uv run python scripts/check-promotion-surface.py` | exit 0 |
| `uv run python scripts/check-backlog-consistency.py` | exit 0, 167 items parse |
| `uv run python scripts/check-radon-baseline.py` | exit 0, 127 reviewed blocks, no regressions |
| `uv run python scripts/check-contract-markers.py` | exit 0, claims evidenced or recorded; two existing AST escape-sequence warnings |

The backend suite has Pydantic serializer/deprecation warnings and 26 skipped tests; passing this suite is not proof of live infrastructure or real-model execution. No gates, quality ledgers, grants, or policy permissions were edited.

## Develop sync (this round): merge origin/develop 7ba29c1cd0 into auto-7

The supplied develop base `7ba29c1cd0` was **not** an ancestor of the branch: the lane had diverged at merge-base `4de7e906d9`, so the branch lacked everything develop gained since and the base..HEAD diff showed ~190k reversed lines. Per the lane instruction ("if it was a develop sync conflict: fetch origin, merge origin/develop into the branch, resolve every conflict in place"), `git merge origin/develop` was executed. Resolutions, in place:

1. **Textual conflict — `KNOWN-GAPS.md` release-notes paragraph.** Develop superseded the stale "Canvas jobs require an external runner" sentence with "The built-in Canvas worker ships and advances jobs durably; the Design Studio product E2E over it (#773) is still pending"; the lane had appended two M3 sentences (the #82 backlog deferral and the #492 JIT admission-only scope). Merged text keeps develop's newer Canvas statement and the lane's additions.
2. **Semantic conflict — `HiveUser` renamed to `HiveAccount`** on develop (`f168831ec0`, P0.1 principal-debt burn). Only the lane's `services/entra_jit.py` still referenced the old name (import, docstring, return annotation, constructor). Renamed; `username_registry`/`stores.users` were already `HiveAccount`-typed on develop, and `HiveAccount` carries every field the provisioner sets.
3. **Semantic conflict — reachability RETIRE ledger vs the lane's wiring.** Develop (`55c354aa74`, #2309/#2456) RETIREs `hive-unwired-services` and lists `services.entra_entitlements` as "Entra entitlement policy without an identity caller"; the lane's #492 work wires exactly that module (Settings load-time policy validation + `EntraJitProvisioner`), so the merged ledger keeps the lane's row removal. `quality/reachability-dispositions.json` rationale was corrected to drop the now-false clause and record why the module left the group; develop's test pin `tests/test_hive_unwired_retire_2309.py::_GROUPS` drops the module with an explanatory comment. Ledger-integrity rule honored: `git diff --numstat origin/develop -- quality/` shows only the lane's pre-existing `-1` row in each ledger; no develop rows lost.

### Post-merge validation (fresh, this round)

| Command | Result |
| --- | --- |
| `uv sync --locked --extra dev` | exit 0 (lockfile updated by the merge) |
| `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py -q` | exit 0, **39 passed** |
| `uv run pytest packages/hive-conductor/backend/tests -q` (pre-fix state) | 1 failed (`test_hive_unwired_retire_2309`), 4570 passed, 113 skipped — the semantic conflict above |
| `uv run pytest packages/hive-conductor/backend/tests/test_hive_unwired_retire_2309.py -q` (post-fix) | exit 0, **1 passed** |
| `uv run pytest packages/maistro-rsi/tests -q` | exit 0, **1793 passed, 4 skipped** (sensitive-paths uniqueness invariant intact after merge) |
| `uv run python scripts/check-reachability.py` | exit 0, 1508 modules / 81 unreachable — merged baseline matches scan |
| `uv run python scripts/check-reachability-dispositions.py` | exit 0, 27 groups cover all 81 unreachable modules (38 CONNECT / 20 LIBRARY / 23 RETIRE) |
| `uv run python scripts/check-reachability-dispositions-provenance.py` | exit 0, no unauthorized disposition expansion |
| `uv run python scripts/check-reachability-provenance.py` | exit 0, no candidate-approved expansion |
| `uv run python scripts/check-release-consistency.py` | exit 0, released none / shipping 0.9.0 / target 1.0.0 |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor` | exit 0, 4712 node IDs match inventory, 0 duplicate evidence |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-rsi` | exit 0, matches recorded inventory |
| `uv run ruff check` / `ruff format --check` on all files touched by this round | exit 0 (one reformat applied to `entra_jit.py` after the rename lengthened a signature) |

## Milestone acceptance accounting (all 19 frozen exit conditions)

| # | Criterion | Evidence / disposition |
| --- | --- | --- |
| 1 | VERSION / CHANGELOG / package metadata consistent | PASS: fresh `check-release-consistency.py` exit 0. |
| 2 | Existing release workflows verified | UNVERIFIED: no release workflow execution or remote mutation performed. |
| 3 | Clean-machine install/deploy and real-model Graph E2E | UNVERIFIED: backend tests ran locally with test doubles; no clean-machine/live-model proof. |
| 4 | Backup/restore including Conductor credentials/decryption escrow | UNVERIFIED: no live backup/restore or escrow exercise. |
| 5 | RC soak and byte-equivalent final promotion | UNVERIFIED: no RC artifacts or soak environment supplied. |
| 6 | Every KNOWN-GAPS item shipped/deferred | UNVERIFIED: inherited gap notes are not current acceptance proof; release consistency does not certify dispositions. |
| 7 | Durable backlog path cut over or release-deferred | UNVERIFIED: inherited KNOWN-GAPS deferral exists, but current production services were not reconciled in this bounded slice. |
| 8 | Persistent Workspace Agent progresses canonical Goals and survives failover without duplicate authority | UNVERIFIED: no new restart/failover acceptance exercise; canonical execution authorities unchanged. |
| 9 | Goal completion is evidence-backed desired-state truth | UNVERIFIED: not inferred from backend suite passing. |
| 10 | Canonical Workspace/Project/Goal/Agent/reconciliation/Run inspection | UNVERIFIED: backend tests alone do not prove every required projection. |
| 11 | Isolated disposable per-Workspace Ladybug projection | UNVERIFIED: no cross-Workspace/hydration/eviction acceptance run. |
| 12 | Dreaming produces provenance-bearing user facts retrievable only when contextually relevant | UNVERIFIED: no real producer-to-retrieval acceptance run. |
| 13 | Private/domain scoping distinguished from same-user user modeling | UNVERIFIED: governing ADR reviewed; no new production memory-path proof. |
| 14 | Optional composable and fully/partially pinned Home | UNVERIFIED: no browser/API parity acceptance run. |
| 15 | Durable adaptive return/settings contract | UNVERIFIED: backend suite is not full Agent/API/UI settings proof. |
| 16 | Durable Attention/Waiting ordering and evidence-backed escalation | UNVERIFIED: no end-to-end ordering/escalation acceptance run. |
| 17 | Bounded idle discovery uses canonical security/Run/Invocation seams | UNVERIFIED: no unattended discovery acceptance run. |
| 18 | Design Studio uses shared Agent/user-memory/Attention | UNVERIFIED: no production cross-product acceptance trace. |
| 19 | Entra first login creates users only for eligible groups, with configured grants | PASS (deterministic production-path tests): 39 JIT tests plus full backend suite, including verified OIDC route, real settings/builder/resolver, account/link/session assertions, unknown-group/outage/config-ceiling refusals, and 17 new regression cases. Live tenant/deployment Graph scopes remain UNVERIFIED. |

## Handoff / residual risks

- This repair is complete locally, not milestone completion or integration approval. Recommended verdict: NEEDS-DEEP-REVIEW for the milestone-level handoff.
- No live Entra tenant was available; operators must configure delegated Graph membership scopes. Existing JIT semantics are first-login only: already-provisioned users retain grants after group removal, as explicitly declared in KNOWN-GAPS.md.
- Pagination intentionally accepts only the same HTTPS Graph origin, default port, and `me/transitiveMemberOf` endpoint; if Microsoft changes its continuation endpoint shape, fail closed until the contract is deliberately updated.
- The broad inherited branch diff relative to the supplied develop base has been reconciled: origin/develop `7ba29c1cd0` is now merged into the branch with conflicts resolved in place (see the develop-sync section). Remaining milestone capabilities are still acceptance review only, not implementation scope for this bounded round.
- Progress: `{checked: 19, done: 2, skipped: 17, errors: 0, next: "decompose remaining milestone acceptance; obtain operator release/live-service evidence"}`. Done counts deterministic acceptance only; the live-tenant caveat above still applies.
- Develop-sync round adds: `{checked: 3, done: 3, skipped: 0, errors: 0}` conflict resolutions (KNOWN-GAPS paragraph, HiveAccount rename, RETIRE-ledger/test pin); branch now contains origin/develop `7ba29c1cd0` with all conflicts resolved in place and gates re-run post-merge. Milestone-level acceptance accounting is unchanged: still 2 deterministic passes, 17 unverified.
