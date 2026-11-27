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

## Round 4 acceptance accounting (historical; superseded by Round 5 below)

The PASS labels in this historical table are **not current acceptance claims**.
Round 5 distinguishes exercised primitives from reachable complete product behavior.

| # | Criterion | Evidence / disposition |
| --- | --- | --- |
| 1 | VERSION / CHANGELOG / package metadata consistent | PASS: fresh `check-release-consistency.py` exit 0. |
| 2 | Existing release workflows verified | UNVERIFIED: no release workflow execution or remote mutation performed. |
| 3 | Clean-machine install/deploy and real-model Graph E2E | UNVERIFIED: backend tests ran locally with test doubles; no clean-machine/live-model proof. |
| 4 | Backup/restore including Conductor credentials/decryption escrow | PASS (deterministic): `test_backup_restore_drill.py` proves the restore drill end-to-end — manifest verification, credential-escrow decrypt proof with the pinned root secret, and refusals for wrong pinned secret, absent escrow (hard failure), unrelated identity, swapped Fernet key, corrupt credential store, corrupt backup component, missing state DB (#88, closed). 148 passed in the attention/home/landing/restore batch. Live multi-host drill remains operator work. |
| 5 | RC soak and byte-equivalent final promotion | UNVERIFIED: no RC artifacts or soak environment supplied. |
| 6 | Every KNOWN-GAPS item shipped/deferred | PASS (structural + corrected defect): every entry carries an explicit shipped/deferred statement and Tracking line; the one disposition contradicted by reachable production code (#82 — claimed "`git grep BacklogItem` over `packages/` returns nothing" while BacklogItem/claim/lease/campaign modules ship on the merged develop base) was found and rewritten this round (see Round 3). Other entries' facts were inherited, not re-proven against live behavior. |
| 7 | Durable backlog path cut over or release-deferred | PASS (reconciled this round): the durable path **ships** — `maistro.workspaces.backlog` BacklogItem + atomic fenced claim/lease over a SQLite store wired in `maistro/container.py` (`wire_backlog_store`), HTTP at `/{workspace_id}/backlog`; campaign operator policy durable via `SqliteCampaignStore` (`/{workspace_id}/campaigns`); Hive board `/v1/backlog` over `services.backlog`; agent surface `maistro.backlog.agent_surface` behind the `maistro` CLI. Declared limits: no PostgreSQL BacklogItem backend (in-process fallback with warning on PG Projects), and no production consumer turns campaign selection/claims into canonical Runs. KNOWN-GAPS disposition corrected from false "release-deferred/nothing exists" to shipped-with-limits. |
| 8 | Persistent Workspace Agent progresses canonical Goals and survives failover without duplicate authority | PASS (deterministic): `maistro.goals.reconciliation` + container wiring — goals suite 163 passed, including `test_same_goal_lineage_across_failover`, single-holder fencing (`test_second_holder_gets_no_claim_and_cannot_admit`, `test_takeover_makes_the_old_token_stale`, `test_reconciler_skips_when_another_holder_owns_the_goal`), restart dedup (`test_decision_key_replayed_after_restart_admits_once`, crash-repair pair, `test_recover_enumerates_from_durable_facts_only`), and authority containment (`test_store_never_creates_runs_itself`, `test_control_records_carry_no_execution_lifecycle`); `test_goal_container_wiring.py` proves the control plane is wired into the container with fenced idempotent admission; `test_workspace_agent_identity.py` proves one stable per-Workspace Agent surviving a SQLite restart. |
| 9 | Goal completion is evidence-backed desired-state truth | PASS (deterministic, structural): `test_a_run_outcome_never_moves_goal_state` drives a bound Run to COMPLETED and asserts the Goal stays ACTIVE with no transition records, then exercises the one authorized writer; `test_goal_inspection.py::test_completed_runs_do_not_render_the_goal_completed` and `::test_canonical_goal_state_and_bound_revision_are_not_derived_from_a_run` prove the projection side. |
| 10 | Canonical Workspace/Project/Goal/Agent/reconciliation/Run inspection | PASS (deterministic): `test_goal_inspection.py` (goal history from sequential Runs, NodeRun/Attempt exposure, workspace-scoped read-only routes, OpenAPI contract, no pseudo-Goals, foreign-workspace invisibility) + `test_canonical_run_inspection.py` — 42 passed. |
| 11 | Isolated disposable per-Workspace Ladybug projection | PASS (deterministic): working-graph suite 94 passed — `test_isolation.py` (one graph per Workspace, `test_discarding_one_workspace_leaves_the_other_intact`, foreign-Workspace record refusal, misscoped-hydration poison refusal), hydration/provenance lineage, rebuild/degradation. |
| 12 | Dreaming produces provenance-bearing user facts retrievable only when contextually relevant | SPLIT — retrieval/promotion halves PASS (deterministic): user-model suite 60 passed incl. `test_workspace_a_evidence_surfaces_in_workspace_b_only_when_relevant`, `test_user_correction_changes_later_retrieval_and_keeps_provenance`, promotion provenance/correction/contradiction tests. Producer half UNVERIFIED/deferred: no production caller of `promote_evidence` (Dreaming cadence #1046 unbuilt) — KNOWN-GAPS disposition corrected this round. |
| 13 | Private/domain scoping distinguished from same-user user modeling | PASS (deterministic): `test_workspace_private_fact_that_was_never_promoted_stays_invisible`, `test_colliding_users_cannot_observe_each_others_facts`, `test_persona_shapes_ranking_but_never_authorization`, `test_colliding_identifiers_stay_workspace_private` (ADR-080 semantics asserted in code). |
| 14 | Optional composable and fully/partially pinned Home | PASS (deterministic): `test_home_layout_service.py` + `test_home_routes.py` — partial/100% pinning (`_pinned_record` = two pinned + one Agent-writable unpinned region), unpinned default never persisted by reads, pinned layouts durable across store reopen, compose references kinds not resources. |
| 15 | Durable adaptive return/settings contract | PASS (deterministic): `test_workspace_landing_preference.py`, `test_workspace_restore_policy.py`, `test_settings_durability.py`, `test_preference_calibration.py` — 104 passed in the settings batch (learned/explicit landing preference, restore policy, durable settings, calibration). |
| 16 | Durable Attention/Waiting ordering and evidence-backed escalation | PASS (deterministic): `test_attention_projection.py` — `test_priority_ladder_orders_severity_before_proactive` asserts the exact #1049 ladder (severity > time_sensitive > blocking > queued > follow_up > proactive), near-deadline outranking, overdue refusals, age-alone escalation refusal, machine-wait exclusion, member scoping, dismissal preference durability. |
| 17 | Bounded idle discovery uses canonical security/Run/Invocation seams | UNVERIFIED: #1051 is open and actively implemented in separate repair lanes (attempts recorded against a different head); the Attention `proactive` class exists as the surfacing target, but the discovery/scout/curation pipeline does not ship on this branch. |
| 18 | Design Studio uses shared Agent/user-memory/Attention | PASS (deterministic, execution-level): `packages/maistro-design` suite 724 passed — `creative_graph.py` plans/instantiates/runs one canonical Graph per CreativeBrief through `run_durable_graph`, binding Goal identity/revision and Agent delegation provenance into the canonical Run (no product-private execution or Goal authority); `test_design_scope.py` refuses creation without canonical execution or an authenticated principal. Agent-runtime memory/Attention consumption stays with the deferred producer (row 12/17 limits). |
| 19 | Entra first login creates users only for eligible groups, with configured grants | PASS (deterministic production-path tests): 39 JIT tests plus full backend suite, including verified OIDC route, real settings/builder/resolver, account/link/session assertions, unknown-group/outage/config-ceiling refusals, and 17 new regression cases. Live tenant/deployment Graph scopes remain UNVERIFIED. |

## Historical handoff / residual risks (superseded by Round 5)

- This repair is complete locally, not milestone completion or integration approval. Recommended verdict: NEEDS-DEEP-REVIEW for the milestone-level handoff.
- No live Entra tenant was available; operators must configure delegated Graph membership scopes. Existing JIT semantics are first-login only: already-provisioned users retain grants after group removal, as explicitly declared in KNOWN-GAPS.md.
- Pagination intentionally accepts only the same HTTPS Graph origin, default port, and `me/transitiveMemberOf` endpoint; if Microsoft changes its continuation endpoint shape, fail closed until the contract is deliberately updated.
- The broad inherited branch diff relative to the supplied develop base has been reconciled: origin/develop `7ba29c1cd0` is now merged into the branch with conflicts resolved in place (see the develop-sync section). Remaining milestone capabilities are still acceptance review only, not implementation scope for this bounded round.
- Progress: `{checked: 19, done: 2, skipped: 17, errors: 0, next: "decompose remaining milestone acceptance; obtain operator release/live-service evidence"}`. Done counts deterministic acceptance only; the live-tenant caveat above still applies.
- Develop-sync round adds: `{checked: 3, done: 3, skipped: 0, errors: 0}` conflict resolutions (KNOWN-GAPS paragraph, HiveAccount rename, RETIRE-ledger/test pin); branch now contains origin/develop `7ba29c1cd0` with all conflicts resolved in place and gates re-run post-merge. Milestone-level acceptance accounting is unchanged: still 2 deterministic passes, 17 unverified.

## Round 3 (job `a323711da6314257b70485c99e07b5d1`): fresh validation + #82 disposition repair

The driver supplied no `check-*.log` files (`checks: []` in the manifest), so every check below was executed fresh against HEAD `1757607b5e`; earlier claims were treated as unproven and re-run. One acceptance-relevant defect was found and repaired.

Fresh validation results (all exit 0 unless noted):

| Command | Result |
| --- | --- |
| `uv run ruff check .` | all checks passed |
| `uv run ruff format --check .` | 3677 files already formatted |
| `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py packages/hive-conductor/backend/tests/test_hive_unwired_retire_2309.py -q` | 40 passed |
| `uv run pytest packages/hive-conductor/backend/tests -q` | **4571 passed, 113 skipped** (243s) |
| `uv run pytest packages/maistro-rsi/tests -q` | 1793 passed, 4 skipped |
| `uv run python scripts/check-reachability.py` | 1508 modules / 81 unreachable |
| `uv run python scripts/check-reachability-dispositions.py` | 27 groups cover all 81 |
| `uv run python scripts/check-reachability-dispositions-provenance.py` / `check-reachability-provenance.py` | no unauthorized expansion |
| `uv run python scripts/check-release-consistency.py` | released none / shipping 0.9.0 / target 1.0.0 |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` | suites match recorded inventory |
| `uv run python scripts/check-backlog-consistency.py` | 167 items parse |
| `uv run python scripts/check-promotion-surface.py` / `check-radon-baseline.py` | ok / 124 reviewed blocks |

Red-run evidence for the #492 pagination repair was re-confirmed from the recorded logs (`/tmp/issue-7-pagination-red.log`: 17 failed, 22 deselected; `/tmp/issue-7-jit-after.log`: 39 passed); the regression tests assert structure, not just outcomes (`len(membership_requests) == 1` proves the login bearer token is never forwarded to a foreign `@odata.nextLink`).

**Defect found and repaired — KNOWN-GAPS #82 disposition was false against reachable production code.** The entry claimed `git grep BacklogItem` over `packages/` returns nothing and that no claim transaction or campaign notion exists anywhere in shipped services. The merged develop base `7ba29c1cd0` itself contains the #98/#100/#103 slices: `maistro/workspaces/backlog/` (BacklogItem model, store contract, atomic fenced claim/renew/release/active_claim, SQLite durable store + in-memory reference + `wire_backlog_store` called from `maistro/container.py:2808`), `maistro/workspaces/campaigns/` (durable `SqliteCampaignStore` + loud in-memory fallback, wired at `container.py:2564`), HTTP surfaces `maistro_server/api/backlog.py` + `backlog_history.py` + `campaigns.py` mounted through `api/workspaces.py` → `main.py:968`, Hive's canonical board `routes/backlog.py` (`/v1/backlog`, mounted `main.py:412`) over `services/backlog.py`, and the agent surface `maistro.backlog.agent_surface` consumed by `maistro/cli/_backlog.py`. Repaired: KNOWN-GAPS #82 entry rewritten to the shipped-with-limits truth (no PostgreSQL BacklogItem backend yet — in-process fallback with logged warning on PG Projects; no production consumer turns `select_next`/claims into canonical Runs) and the Release-Notes Text sentence corrected to match. No production code, tests, or ledgers were edited; the repair is docs-only, so no inventory delta.

Updated acceptance rows: 6 and 7 now PASS (see table above); deterministic passes stand at 4 of 19, 15 unverified (live-tenant/release-pipeline classes unchanged).

## Round 4 (job `21ca26e316ec485bab21f0e819243a75`): resolve the deep-review request — acceptance rows mapped to reachable production behavior

The prior round left 15 rows UNVERIFIED and requested deep review. This round re-derived every row against reachable production behavior: located the shipped modules behind each closed sub-issue (#88, #776, #777, #1047–#1050), ran their targeted suites fresh, and recorded file-level evidence. No production code was edited; one more false KNOWN-GAPS disposition was found and corrected (docs-only).

Fresh targeted validation (all exit 0, this round, HEAD `1507434b5`):

| Suite | Result |
| --- | --- |
| `packages/maistro-core/tests/goals` | 163 passed, 24 skipped (PG-gated) |
| `packages/maistro-core/tests/memory/user_model` + `packages/maistro-server/tests/api/test_user_model_api.py` | 60 passed, 11 skipped (PG-gated) |
| `packages/maistro-core/tests/memory/working_graph` + `working` | 94 passed |
| hive `test_attention_projection` + home + landing/restore + `test_backup_restore_drill` | 148 passed |
| hive `test_goal_inspection` + `test_canonical_run_inspection` | 42 passed |
| hive design scope/startup + settings durability + preference calibration | 104 passed |
| hive `test_workspace_agent_identity` + persona routes | 25 passed |
| `packages/maistro-design/tests` | 724 passed, 1 skipped |
| `uv run ruff check .` / `ruff format --check .` | clean / 3677 files formatted |
| `uv run python scripts/check-release-consistency.py` | released none / shipping 0.9.0 / target 1.0.0 |

**Defect found and repaired — KNOWN-GAPS #1047 disposition was false against reachable production code** (same class as the Round-3 #82 correction). The entry claimed "None of it has a production call path — nothing in the conductor process or maistro-server constructs a `UserModelStore`". In fact maistro-server constructs `PostgresUserModelStore` + `UserModelService` at startup (`main.py::_configure_user_model`, invoked from lifespan) and mounts the owner-scoped `/user-model` routes twice (`main.py:977` under `/v1`, `:993`), with 503-offline fallback and passing API tests. The entry is rewritten to the truthful shipped-with-limits state: owner control plane + relevance-gated same-user retrieval ship; the autonomous Dreaming→`promote_evidence` producer and the Agent-runtime recall consumer remain deferred to #1046. The stale heading ("specified but not reachable") and the false sentence are gone; the Release-Notes paragraph never mentioned the user model, so no other text needed correction.

Historical Round 4 accounting claimed 14 of 19 rows, including a partially proven row. That tally is withdrawn: it conflated library/fixture proofs with operational product acceptance. Round 5 below is the current assessment.

## Round 5 — current handoff (job `b3e579978d2845ce87b7ea75ffc76993`)

Starting HEAD `4e931b1a6c429f597e08199bda22759dd5be16c5`, branch `auto-7`,
worktree initially clean. The supplied dispatch snapshot was read locally;
no remote enumeration, GitHub mutation, merge, or discarded work. No driver
`check-*.log` files existed in the job directory. This round's actual logs
are `worker-*.log` in that directory. Previous commits remain intact.

### Evidence-backed changes

1. **Disabled-JIT test was not testing refusal.** Its body only constructed
   `OAuthLoginService` and asserted `_jit is None`. It now uses the real OAuth
   callback, signed nonce-bound Entra token and valid eligible-group config
   with activation absent. It asserts 401, no membership request, no account,
   no identity link and no session. A validation-only external pytest plugin
   injected an activation bypass inside `authenticate` (leaving the builder's
   `_jit is None` assertion intact): the strengthened test failed at
   **303 != 401**. Without that mutant the JIT suite is **39 passed**. No
   production code was mutated on disk. Inventory note
   `issue-7-disabled-login.md` records zero node-count delta.
2. **Release-note text contradicted the documented/shipped queue.** The
   `KNOWN-GAPS.md` copy-ready block said every restart loses queued/active
   tasks; its first entry and production `maistro_server/main.py:665–679`
   document durable admission and `queue.recover(run_store)` when configured.
   Corrected to conditional durability, per-process dispatch, and explicit
   no-database loss. The core task suite exercises recovery; the live PG
   process-restart test was **skipped**, not counted as proof.
3. **Acceptance overclaims corrected here.** In particular, a tested fencing
   primitive is not an operational Workspace Agent, an embedded dictionary
   graph is not a Ladybug adapter, and canonical Design execution alone is
   not shared memory/Attention consumption. These are concrete code-path
   gaps, not scanner guesses. No attempt was made to patch them by adding
   a competing scheduler, Goal store, authorization path or memory authority.

### Fresh validation

All commands below exited 0 unless explicitly described as a negative control.

| Command | Executed outcome |
| --- | --- |
| `uv sync --locked --extra dev` | success |
| `uv run ruff check .` / `uv run ruff format --check .` | success (also rerun after final changes) |
| `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py packages/hive-conductor/backend/tests/test_entra_entitlements.py packages/hive-conductor/backend/tests/test_hive_unwired_retire_2309.py -x -q` | 53 passed before test strengthening |
| `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py -x -q` | 39 passed after strengthening |
| `PYTHONPATH=<job-dir> uv run pytest -p disabled_jit_mutant packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py -q -k jit_disabled` | expected exit 1: 1 failed, 38 deselected, assertion 303 != 401 |
| `uv run pytest packages/hive-conductor/backend/tests -x -q` | **4571 passed, 113 skipped**, 35 warnings |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/memory/user_model packages/maistro-core/tests/memory/working_graph packages/maistro-core/tests/memory/working -x -q` | **311 passed, 35 skipped** (PG-gated tests not proven) |
| `uv run pytest packages/maistro-server/tests/api/test_user_model_api.py -x -q` | 6 passed |
| `uv run pytest packages/maistro-design/tests -x -q` | 724 passed, 1 skipped |
| `uv run pytest packages/maistro-core/tests/tasks -x -q` | 801 passed, 22 skipped |
| `uv run pytest packages/maistro-server/tests/test_task_restart_recovery.py -x -q` | **1 skipped** (no PG DSN); live restart proof UNVERIFIED |
| `uv run pytest packages/hive-conductor/backend/tests/test_backup_restore_drill.py -x -q -rs` | 14 passed, real age/Fernet decrypt proofs |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` | 4684 collected, matches inventory, no duplicate evidence |
| `uv run python scripts/check-release-consistency.py` | released none / shipping 0.9.0 / target 1.0.0 |
| `uv run python scripts/check-contract-markers.py` | success |
| `uv run python scripts/check-backlog-consistency.py` | success |
| `uv run python scripts/check-reachability.py` / `check-reachability-dispositions.py` | success |
| `uv run python scripts/check-reachability-provenance.py` / `check-reachability-dispositions-provenance.py` | success; no ledger edits |

### Current acceptance accounting — all 19 frozen issue #7 exit conditions

**PASS (deterministic)** is limited to the stated behavior. **PARTIAL** is
not a completed exit condition. No live service, UI deployment or release
exercise is inferred from a mocked provider, injected policy or skipped test.

| # | Criterion | Current evidence and remaining acceptance |
| --- | --- | --- |
| 1 | VERSION / CHANGELOG / package metadata consistent | PASS (deterministic): fresh release-consistency gate. This does not claim a released 1.0.0. |
| 2 | Existing release workflows verified | UNVERIFIED: no workflow execution records supplied or run; workflow existence is not execution proof. |
| 3 | Clean-machine install/deploy + real-model Graph E2E | UNVERIFIED: local locked dependency sync and mocked-provider tests are not clean-machine/live-model evidence. |
| 4 | Backup/restore including Conductor credentials and escrow | PARTIAL: 14 tests source the real verification script over generated SQLite, age and Fernet artifacts; pinned decrypt and tamper refusals pass. Full database/volume capture, restore and deployed operation were not exercised. |
| 5 | RC soak and byte-equivalent final promotion | UNVERIFIED: no RC artifacts, soak record or promotion byte comparison supplied. |
| 6 | Every KNOWN-GAPS item explicitly shipped/deferred | PASS for disposition accounting: read every entry; limited/deferred/closed states are explicit, including backlog and user-model limits. Repaired the contradictory queue release text. This is not certification of every inherited factual statement or acceptance of every deferral. |
| 7 | Durable backlog/claim/campaign path cut over or release-deferred | PARTIAL: the SQLite control plane and HTTP/CLI seams exist; KNOWN-GAPS declares missing PostgreSQL BacklogItem storage and autonomous claim-to-Run consumer. A PostgreSQL deployment falls back to process-local BacklogItems, so generic durable cutover is not proven. Release-owner acceptance of these limits is UNVERIFIED. |
| 8 | Operational persistent Workspace Agent discovers/progresses/waits/delegates/replans owned Goals and survives restart/failover | NOT MET by current production composition: `container.py:1399–1424` returns 0 without an injected policy, has no physical admitter, and the production caller scan found no configured policy or caller of this tick. `goals/reconciliation/wiring.py:105–148` explicitly uses in-memory state for PostgreSQL (cannot fence replicas or survive restart). `test_goal_container_wiring.py` proves the no-policy and PG-fallback behavior; injected-policy/SQLite tests prove primitives only. Do not activate this by inventing a second execution authority. |
| 9 | Goal completion evidence-backed, never inferred from latest Run | PARTIAL: goals and inspection suites prove Run completion does not automatically complete a Goal. A reachable operational reconciler establishing evidence-backed desired-state completion is not demonstrated (row 8); that half remains UNVERIFIED. |
| 10 | Canonical Workspace/Project/Goal/Agent/reconciliation/Run inspection | PASS for deterministic backend inspection: full backend suite includes `test_goal_inspection.py` and `test_canonical_run_inspection.py` with scope refusals and NodeRun/Attempt views. Live UI inspection was not rerun. |
| 11 | Minimum disposable isolated per-Workspace Ladybug working graph | PARTIAL: container chat context uses `working_memory_context_message` (`container.py:822`), and isolation/hydration/eviction tests pass. But manager `_embedded_factory` selects `create_backend("embedded", ...)`; `working_graph/backend.py:109–124` is dictionaries, explicitly a reference stand-in. No production Ladybug registration was found. Accepted ADR-082226-5104 chooses Ladybug, so an equivalent-role test cannot certify literal backend adoption. |
| 12 | Dreaming produces provenance-bearing user facts; same-user Agent recall only when relevant | PARTIAL: promotion/retrieval primitives and owner HTTP APIs pass. Production constructs the PostgreSQL service (`maistro_server/main.py:89–117`); no production caller of `promote_evidence` or Agent-runtime `recall_for_task` was found. Test-local Workspace Agent harnesses are not the production consumer. Full producer-to-Agent behavior is UNVERIFIED. |
| 13 | Workspace-private scope distinct from same-user personalization | PASS (deterministic boundary): user-model tests refuse colliding other-user/private facts and Persona-based authorization widening. This does not fill row 12's missing runtime wiring. |
| 14 | Optional Home composition; partial/100% pinning | PASS for deterministic backend contract: full backend suite exercises home layout/routes, pinned revisions, scoped references and unpinned composition. Browser rendering was not rerun; no Home dependency was introduced into execution. |
| 15 | Adaptive restoration through durable explicit/learned settings contract | PASS for deterministic backend contract: full backend suite includes landing preference, restore policy, settings durability and preference calibration. Deployed browser restoration remains UNVERIFIED. |
| 16 | Durable Attention/Waiting, prescribed ordering and evidence-backed escalation | PASS for deterministic backend projection: full backend suite covers `test_attention_projection.py`; `services/attention.py` derives from canonical durable sources and persists only defer/dismiss preferences. Exact priority ladder and refusal of age-only escalation pass; no second Attention authority is introduced. |
| 17 | Bounded proactive discovery under canonical Run/Invocation/security seams | UNVERIFIED: no shipped discovery/scout/curation producer demonstrated on this HEAD. The existing `proactive` Attention classification is a destination, not a discovery pipeline. Other-lane attempts are not evidence for this branch. |
| 18 | Design Studio consumes shared persistent Agent/user-memory/Attention | NOT PROVEN: Design tests prove canonical execution, authenticated scope and provenance, not consumption of the missing Agent recall or discovery paths. Production `maistro-design/src` scan found no UserModel/Attention/recall consumer. Canonical execution is necessary but insufficient; row 18's earlier PASS is withdrawn. |
| 19 | Entra group-gated first-login provisioning with only configured grants | PASS (deterministic first-login behavior): real callback + builder/resolver tests, negative controls, 39 JIT tests and complete backend suite. Live tenant Graph scopes UNVERIFIED. This is NOT #492 completion: subsequent-login group-removal reconciliation, durable SSO/local grant provenance and atomic user/link/entitlement transaction are not proven; `OAuthLoginService.authenticate` skips JIT for linked users and provisioner creates user then link separately. |

### Disposition / next owner

**NEEDS-REPAIR for milestone acceptance, not integration approval.** The
bounded first-login repair has passing focused and package validation; the
milestone does not satisfy its operational Agent, Dreaming, literal Ladybug,
proactive-discovery and shared Design consumption requirements, and still
needs operator release evidence. The previous deep-review ambiguity is now
an actionable gap list, not a request to assume missing work has shipped.

No production authority, quality ledger, grant or policy was changed. Read
accepted ADR-068, ADR-080 and ADR-082226-5104 plus Proposed ADR-059; preserved
their authorization/memory/execution boundaries. Remaining implementation
must compose the existing canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`
seams, not replace them. This round adds no competing store or scheduler.

Progress: `{checked: 19, done: 8, skipped: 0, errors: 0, next: "repair operational composition gaps; obtain live release evidence"}`.
Here `done` counts only the eight explicitly bounded deterministic/disposition
PASS rows (1, 6, 10, 13–16, 19), not complete milestone acceptance.

## Round 6 — independent repair-round re-verification (job `ed973a308d1d438480534c04b1a785aa`)

Starting HEAD `90dbb33db0` (identical to the manifest head), worktree clean, no
uncommitted salvage. The prior verify job (`ae850e8d…`) died on a provider 404
*after* its deterministic checks; those logs (in that job directory) all
returned 0 and were inspected, not trusted: every result below was re-executed
fresh in this round. No code, tests, ledgers, gates or policy were edited; this
section is the only change.

### Fresh validation (all exit 0)

| Command | Executed outcome |
| --- | --- |
| `uv run ruff check .` / `ruff format --check .` | all checks passed / 3678 files already formatted |
| `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py packages/hive-conductor/backend/tests/test_entra_entitlements.py packages/hive-conductor/backend/tests/test_hive_unwired_retire_2309.py -q` | **53 passed** |
| `uv run pytest packages/hive-conductor/backend/tests -q` | **4571 passed, 113 skipped** (248.9s) |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/memory/user_model packages/maistro-core/tests/memory/working_graph packages/maistro-core/tests/memory/working -q` | **311 passed, 35 skipped** (PG-gated) |
| `uv run pytest packages/maistro-design/tests -q` | **724 passed, 1 skipped** |
| `uv run pytest packages/maistro-server/tests/api/test_user_model_api.py -q` | **6 passed** |
| `uv run python scripts/check-release-consistency.py` | ok: released none, shipping 0.9.0, working toward 1.0.0 |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` | ok, matches recorded inventory, 0 duplicate evidence |
| `uv run python scripts/check-reachability.py` / `-dispositions.py` / `-provenance.py` / `-dispositions-provenance.py` | ok: 81 unreachable of 1508 modules, 27 groups (38 CONNECT / 20 LIBRARY / 23 RETIRE), no candidate-approved expansion |
| `uv run python scripts/check-contract-markers.py` | ok: every contract claim evidenced or recorded |
| `uv run python scripts/check-backlog-consistency.py` | ok: 167 items parse |

### Negative production-composition claims re-proven (they are true)

- Row 8: `maistro/container.py:1409` — `reconcile_goals` returns 0 when
  `goal_reconciliation_policy is None`; repo-wide grep found no production
  caller of the tick and no production assignment of the policy (tests and the
  reconciliation module only). `goals/reconciliation/wiring.py:119–131` answers
  a PostgreSQL pool with `InMemoryGoalStore()` plus a loud warning.
- Row 11: `working_graph/manager.py:39` selects `create_backend("embedded", …)`;
  no production Ladybug backend registration exists.
- Row 12: `promote_evidence` has no caller outside its defining module;
  `recall_for_task` is reachable only through the owner-scoped HTTP route, not
  any Agent-runtime path.
- Row 18: `packages/maistro-design/src` contains no UserModel, Attention or
  recall consumer.
- Row 19: `services/oauth_login.py:344–350` invokes the JIT provisioner for
  unlinked Entra identities; `services/entra_jit.py:65–92,157–162` validates
  every `@odata.nextLink` against the HTTPS Graph origin and the
  `/v1.0/me/transitiveMemberOf` subject endpoint. The strengthened
  disabled-JIT test (`test_entra_jit_provisioning.py:497`) asserts 401, no
  Graph membership request, and no account/link/session/audit side effects.
- Ledger integrity: `git diff --numstat <base> -- quality/` shows exactly the
  documented lane rows (`reachability-baseline.json` −1,
  `reachability-dispositions.json` +1/−1); all four reachability provenance
  gates pass against them.

### Verdict carried forward

The Round 5 accounting stands unchanged: 8 bounded deterministic/disposition
PASS rows; rows 2, 3, 5, 17 UNVERIFIED (require operator release-pipeline,
clean-machine/live-model, RC-soak and discovery-pipeline evidence not
obtainable in this environment); rows 4, 7, 9, 11, 12 PARTIAL; rows 8 and 18
not met by current production composition. **NEEDS-REPAIR for milestone
acceptance** remains the correct disposition; no code repair belongs in this
verification-only round.

Progress: `{checked: 19, done: 0, skipped: 0, errors: 0, next: "implement rows 8/12/17/18 production composition on canonical seams; obtain operator release evidence"}`.

## Round 7 — CI-gate repair (job `2ae0ec2d0d5e475abd5a3004df873544`)

Starting HEAD `df001b9478` (exact match), worktree clean, no uncommitted salvage;
the two immediately prior jobs died on provider 404s before any work. The driver
supplied no `check-*.log` files, so every result below is fresh. What this round
adds: the dispatch snapshot carries the PR #2529 check-runs for head `90dbb33db0`
— **4 failures** (`Coverage gate (publish-set floor + diff coverage)`, `Quality
gate (Pillars 1–4, 7, 8)`, `Quality / Workspace retirement`, `test`) with no log
output captured. They were reproduced locally with CI's exact arguments instead
of being assumed base-level.

### Root cause found and repaired: the #492 slice gained a consumer of a retiring surface

`RATCHET_BASE_REV=origin/develop uv run python scripts/check-workspace-retirement.py`
failed verbatim: `stores.py::users: NEW importer
packages/hive-conductor/backend/services/entra_jit.py -- a retiring surface may
not gain consumers`. `quality/workspace-retirement.json` is a shrink-only
ledger: `stores.py::users` is a RETIRE row (delete-by M3, replaced by the P0.1
identity store) whose importer list may not grow, so no ledger edit was
possible or made. The repair is composition-only, on existing seams:

1. `services/username_registry.py` — new public `UsernameRegistry.get_user`
   (the public form of `_durable_user`, including its durable-backend
   fallback) plus the module-level delegate; the registry is already a
   recorded importer of the users store.
2. `services/entra_jit.py` — the lost-link-race recovery resolves the
   canonical account through `username_registry.get_user(...)` and the module
   no longer binds `stores`.

Gate after the repair: `78 tolerated importers -> 78`, `OK: 89 retirement
ledger entries match the tree`. This also clears the one reproduced cause of
the `Quality gate (Pillars 1–4, 7, 8)` aggregate (its `quality-retirement`
need).

### Regression tests (inventory note `issue-7-jit-retiring-store.md`, backend suite +2)

- Structural pin: `services.entra_jit` must not bind the retiring `stores`
  module. Demonstrated red against the pre-repair module (`assert not True` on
  `hasattr(m, "stores")`), green after the repair; the CI ratchet it mirrors
  runs only in quality.yml, this suite runs in every backend producer.
- Durable-race case: the recovery returns the canonical account from a real
  `PersistedStore` backend when the account exists only durably. Its docstring
  records the honest limit found while red-proving: allocation itself
  hydrates the users table into memory (`UsernameRegistry._all_users`), so
  this case is capability coverage of the repaired seam, not a discriminator;
  the structural pin above is the guard.

### Fresh validation (all exit 0 unless noted)

| Command | Executed outcome |
| --- | --- |
| `uv run pytest packages/hive-conductor/backend/tests -q` | **4573 passed, 113 skipped** (4571 + the 2 new tests) |
| `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py -q` | 41 passed |
| `uv run pytest packages/hive-conductor/backend/tests/test_username_registry.py packages/hive-conductor/backend/tests/test_registration_policy.py -q` | 81 passed |
| `uv run pytest packages/maistro-turing/tests packages/maistro-turing/backend/tests -q` | 363 passed |
| `uv run pytest packages/maistro-ext-harness/tests packages/maistro-ext-sdk/tests -q` | 420 passed |
| `uv run pytest packages/maistro-rsi/tests -q` | 1793 passed, 4 skipped |
| `uv run pytest tests/ --ignore=tests/tools/registry -q` (REQUIRE_AUTH=false, MAISTRO_DRY_RUN=1, RATCHET_BASE_REV=origin/develop) | **6206 passed, 141 skipped** — the one `test`-job component no prior round had run |
| `uv run ruff check .` / `ruff format --check .` | all checks passed / 3678 files formatted |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` | ok, matches inventory + the recorded +2 delta |
| `uv run python scripts/check-release-consistency.py` | ok: released none / shipping 0.9.0 / target 1.0.0 |
| `uv run python scripts/check-contract-markers.py` / `check-backlog-consistency.py` | ok / ok |
| `uv run python scripts/check-reachability.py` + `-dispositions` + `-provenance` + `-dispositions-provenance` | ok: 81 unreachable of 1508, 27 groups, no expansion |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1219 reviewed -> 1219 findings |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check_enumerations.py` / `check-principal-identity.py` / `check-route-permissions.py` | ok (1 baselined enumeration gap, 0 new; 0 principal violations; 42 declared routes) |
| Coverage-gate replication: `coverage run --branch --source=packages/hive-conductor/backend -m pytest packages/hive-conductor/backend/tests` then `--append --source=packages/maistro-rsi/src/maistro_rsi -m pytest packages/maistro-rsi/tests`, `coverage xml`, `check-diff-coverage.py coverage.xml --base 7926d9ab4dda` | ok: 5 changed files measured (2 test files exempt), **every measured file at or above 90% lines / 80% branch arcs** |

### CI-failure disposition and verdict carried forward

- `Quality / Workspace retirement` and (through its aggregate) `Quality gate`:
  lane-caused, root-caused, and **repaired above**.
- `test`: every suite that job runs passes locally at this head — server and
  design at `90dbb33db0` (Round 6), turing/ext/rsi/backend/root fresh this
  round. No lane-caused failure remains; the red on `90dbb33db0` is consistent
  with the documented runner/worker-death class (the same shape the
  `test_scheduler_projection_authority` worker names for PR #2512), not
  branch content.
- `Coverage gate`: the per-file line+branch diff gate — the part the lane's
  diff feeds — passes locally for every changed file with the gate's own
  script and thresholds. The publish-set 87% aggregate floor needs the full
  multi-producer job (~45 min in CI) and was not replicated; no evidence
  points at the lane diff for it (+~500 statements land in hive-conductor,
  which is deliberately outside the publish set).
- Milestone acceptance accounting (Round 5/6, 19 rows) is unchanged by this
  round and its load-bearing negative composition claims were re-proven
  independently here: `container.py:1409` returns 0 with no policy and no
  production caller/assignment exists (row 8); `wiring.py` answers a PG pool
  with `InMemoryGoalStore` (row 8); `manager.py:39` selects the embedded
  dictionary backend and `backend.py` records `ladybugdb` as unpublished (row
  11); `promote_evidence` has no production caller and `recall_for_task` only
  the owner HTTP route (row 12); `packages/maistro-design/src` has no
  UserModel/Attention consumer (row 18).

**NEEDS-REPAIR for milestone acceptance remains the correct disposition.**
This round repaired the branch's own CI gate; it did not implement rows
8/12/17/18 production composition and did not obtain operator release,
clean-machine, RC-soak or live-tenant evidence, so rows 2/3/5/17 UNVERIFIED,
4/7/9/11/12 PARTIAL, 8/18 NOT MET stand. No quality ledger, grant, gate or
policy was edited; the only ledger-adjacent file is the new inventory note.

Progress: `{checked: 4, done: 2, skipped: 0, errors: 0, next: "implement rows 8/12/17/18 production composition on canonical seams; obtain operator release evidence"}`.
Here `checked` counts the four CI failures, `done` the two repaired
(retirement + its Quality-gate aggregate); the other two carry the disposition
above.

## Round 8 — independent verifier re-verification at the develop-merged head (job `809cf362a1aa48018243da895ba8e6de`)

Starting HEAD `b9a42614c3` (exact match), worktree clean; the only change over
Round 7 is the merge of develop `3be6b6650c` (Design-loop-start WIP, installed-
workspace proof harness, gate-c/mutation workflow changes — no `quality/`, no
JIT/auth files touched by the merge). Driver-supplied `check-*.log` files were
inspected, then every load-bearing result below was re-executed fresh in this
round. No code, test, ledger, grant, gate or policy file was edited; this
section is the only change.

### Executed at this head (verifier's own runs, not inherited claims)

| Command | Result |
| --- | --- |
| `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py packages/hive-conductor/backend/tests/test_hive_unwired_retire_2309.py -q` | **42 passed** (matches driver log) |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-workspace-retirement.py` | exit 0: 78 -> 78 tolerated importers, OK on 89 entries (the Round-7 repair holds at the merged head) |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` | exit 0: 4689 collected node IDs match the recorded inventory, 0 duplicate evidence (the merge's `test_design_loop_start_contract.py` is included) |
| `uv run python scripts/check-release-consistency.py` | exit 0: released none / shipping 0.9.0 / target 1.0.0 |
| closure-keyword scan: `git log <base>..HEAD --format=%s%n%b` pattern `(fixes\|closes\|resolves\|fix\|resolve) #N` | **0 matches**; PR #2529 body says "Refs #7" only — no premature issue closure |
| `git diff --numstat origin/develop -- quality/` + content diff | exactly the documented lane deltas (`reachability-baseline.json` −1, `reachability-dispositions.json` +1/−1 with the entra_entitlements rationale); no develop rows lost by the merge |

### Negative composition claims re-proven at the merged head (all true)

- Row 8: `maistro/container.py:1409` returns 0 without a policy; the only
  non-test `goal_reconciliation_policy` references are the field default
  (`:519`) and the guard itself — no production assignment or tick caller;
  `goals/reconciliation/wiring.py:134,139` answers a PostgreSQL pool with
  `InMemoryGoalStore()`.
- Row 11: `working_graph/manager.py:38-39,63` selects `create_backend("embedded", …)`;
  `working_graph/backend.py` records `ladybugdb` as unpublished (literal Ladybug
  backend not adoptable).
- Row 12: `promote_evidence` has no caller outside `user_model/promotion.py` /
  `__init__` re-export; `recall_for_task` is reachable only through the
  owner-scoped `maistro_server/api/user_model.py` route.
- Row 18: `packages/maistro-design/src` has no UserModel/Attention/recall code
  consumer (only prose mentions in DESIGN.md catalogs).
- Row 2/5: `.github/workflows/release.yml:23-24` still self-declares "NOT YET
  EXERCISED … never run"; all 36 local tags are `backup/*` / `orphan-bak/*` /
  pre-rebase lane tags — no release tags, so RC soak / byte-equivalent promotion
  has no executed evidence.

### Positive Row-19 inspection at the merged head

- `services/oauth_login.py:344-352`: `authenticate` invokes the JIT provisioner
  only for a verified, unlinked Entra identity; refusal falls through to the
  uniform denial with the decision audited.
- `services/entra_jit.py:64-65,82-100,156-161`: continuations validated to the
  HTTPS `graph.microsoft.com` origin, default port, exact
  `/v1.0/me/transitiveMemberOf` subject path, no userinfo/fragment, and the
  untrusted URL is never echoed; malformed present continuations refuse rather
  than admit on partial evidence; `_GRAPH_MAX_PAGES = 10` bounds paging.
- `services/entra_jit.py` no longer binds the retiring `stores` module
  (grep: no match); the structural pin
  (`test_entra_jit_provisioning.py:890` `assert not hasattr(entra_jit_module, "stores")`)
  and the strengthened disabled-JIT test (`:497-524`: real callback, 401, no
  Graph membership request, no account/link/session/audit side effects) are
  present and pass in the 42 above.
- KNOWN-GAPS.md: all 15 entries carry an explicit shipped/deferred/limited
  statement and a `Tracking:` line where limits remain (row 6 disposition
  accounting re-confirmed by reading every entry).

### Verdict carried forward

Round 5/6/7 accounting is unchanged by the develop merge and independently
re-confirmed here. Milestone acceptance: **NEEDS-REPAIR** — rows 8 and 18 are
not met by current production composition; rows 2, 3, 5, 17 are UNVERIFIED
(operator release-pipeline, clean-machine/live-model, RC-soak and
discovery-pipeline evidence not obtainable in this environment); rows 4, 7, 9,
11, 12 are PARTIAL; row 19 is deterministic-PASS with the live-tenant and
reconciliation limits already declared. The lane's own repairs (pagination
binding, disabled-JIT proof, retirement re-route) are sound and hold at this
head; what remains is program-scale composition work, not a defect in this
branch's diff.

Progress: `{checked: 19, done: 0, skipped: 0, errors: 0, next: "implement rows 8/12/17/18 production composition on canonical seams; obtain operator release evidence"}`.

## Round 9 — independent verifier re-verification at the round-8 head (current round)

Starting HEAD `9510ff2e1923` (exact match), worktree clean; the only change over
Round 8 is that round's docs-only note. Driver-supplied `check-*.log` files were
inspected (uv sync OK; `ruff check` "All checks passed!"; `ruff format --check`
"3682 files already formatted"; the 42-test pytest pass; suite inventory
`ok ... 4689` node IDs, 0 duplicate evidence), then every load-bearing result
below was re-executed fresh in this round at this head. No code, test, ledger,
grant, gate or policy file was edited; this section is the only change.

### Executed at this head (verifier's own runs, not inherited claims)

| Command | Result |
| --- | --- |
| `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py packages/hive-conductor/backend/tests/test_hive_unwired_retire_2309.py -q` | **42 passed** (matches driver log) |
| `uv run pytest packages/maistro-rsi/tests -q` | **1793 passed, 4 skipped** (the branch's `sensitive_paths.py` addition is covered green) |
| `uv run python scripts/check-workspace-retirement.py` (CI's exact invocation, `quality.yml:1148`) | exit 0: 78 -> 78 tolerated importers, 89 ledger entries OK (Round-7 repair holds) |
| `uv run python scripts/check-release-consistency.py` | exit 0: released none / shipping 0.9.0 / working toward 1.0.0 (row 1) |
| closure-keyword scan: `git log 3be6b6650c..HEAD --format=%s%n%b` grep `(fixes?\|closes?\|resolves?) #N` | **0 matches**; PR #2529 body is "Refs #7" only — no premature issue closure |
| `git diff origin/develop -- quality/` | exactly the documented lane deltas: `reachability-baseline.json` −1 row (`services.entra_entitlements` now reachable), `reachability-dispositions.json` rationale + module-list updated with the #492 wiring; no other rows touched |

### Negative composition claims re-proven at this head (all true)

- Row 8: `container.py:1409` `if self.goal_reconciliation_policy is None: return 0`;
  the only references to the policy are the field default (`:519`), the guard,
  tests, and the vulture whitelist — no production assignment or tick caller;
  `goals/reconciliation/wiring.py:134-139` answers a PostgreSQL pool with
  `InMemoryGoalStore()`.
- Row 11: `working_graph/manager.py:38-39` `_embedded_factory` selects
  `create_backend("embedded", …)`; `working_graph/backend.py:5,114` records the
  `ladybugdb` distribution as unpublished.
- Row 12: `promote_evidence` callers are tests plus the `__init__` re-export
  only; `recall_for_task` is reachable through the owner-scoped
  `maistro_server/api/user_model.py` route and core `service.py` alone.
- Row 18: `grep -r "UserModel\|recall_for_task\|Attention" packages/maistro-design/src --include=*.py`
  → zero matches.
- Rows 2/5: `.github/workflows/release.yml:23-24` still self-declares
  "NOT YET EXERCISED … has never run"; all 36 local tags are `backup/*` /
  orphan / pre-rebase lane tags — no release tags.

### Positive Row-19 inspection at this head

- `services/oauth_login.py:344-352`: `authenticate` invokes the JIT provisioner
  only for a verified, unlinked Entra identity; refusal falls through to the
  uniform denial with the decision audited.
- Structural pin `test_entra_jit_provisioning.py:890`
  (`assert not hasattr(entra_jit_module, "stores")`) and the strengthened
  disabled-JIT refusal test (`:497-524`) are present and pass in the 42 above.
- KNOWN-GAPS.md: 15 gap entries, each carrying an explicit shipped/deferred/
  limited disposition, 12 `Tracking:` lines (row 6 re-confirmed by scan).

### Verdict carried forward

Round 5-8 accounting is unchanged at this head and was independently
re-executed here. Milestone acceptance: **NEEDS-REPAIR** — rows 8 and 18 are
not met by current production composition; rows 2, 3, 5, 17 are UNVERIFIED;
rows 4, 7, 9, 11, 12 are PARTIAL; rows 1, 6, 13 are deterministic-PASS and
rows 10, 14, 15, 16 PASS in the collected backend inventory with live-UI
inspection unverified; row 19 is deterministic-PASS with declared live-tenant
limits. The lane's repairs hold at this head; the remaining gap is
program-scale composition plus operator release evidence, not a defect in this
branch's diff.

Progress: `{checked: 19, done: 0, skipped: 0, errors: 0, next: "implement rows 8/12/17/18 production composition on canonical seams; obtain operator release evidence"}`.

## Round 10 — independent verifier re-verification at the round-9 head (job `6c50727e`, repair stage)

Starting HEAD `2bedd230cfad` (exact match), worktree clean; the only change over
Round 9 is that round's docs-only note. The prior driver run's `check-*.log`
files (job `cd29c2ab`, same head) were inspected — uv sync OK, `ruff check`
"All checks passed!", `ruff format --check` "3682 files already formatted",
42-test pytest pass, suite inventory `ok ... 4689` — then every load-bearing
result below was re-executed fresh in this round at this head. No code, test,
ledger, grant, gate or policy file was edited; this section is the only change.
No test was added, so no suite-inventory delta arises (`check-suite-inventory`
confirms the recorded 4689 still matches).

### Executed at this head (verifier's own runs, not inherited claims)

| Command | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed! |
| `uv run ruff format --check .` | 3682 files already formatted |
| `uv run pytest packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py packages/hive-conductor/backend/tests/test_hive_unwired_retire_2309.py -q` | **42 passed** (matches driver log) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact invocation, `quality.yml:1630-1634`) | exit 0: 1219 reviewed identities -> 1219 findings, unclassified 0 — no unbanked identities, no ledger amendment needed |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-workspace-retirement.py` (CI's invocation, `quality.yml:1148`) | exit 0: 78 -> 78 tolerated importers, OK on 89 entries |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` | exit 0: 4689 collected node IDs match the recorded inventory, 0 duplicate evidence |
| `uv run python scripts/check-release-consistency.py` | exit 0: released none / shipping 0.9.0 / working toward 1.0.0 (row 1) |
| closure-keyword scan: `git log 3be6b6650c..HEAD --format=%s%n%b` grep `(fixes?\|closes?\|resolves?) #N` | **0 matches** — no premature issue closure |
| `git diff --numstat origin/develop -- quality/` | exactly the documented lane deltas: `reachability-baseline.json` −1 row (`services.entra_entitlements` now reachable via the #492 JIT wiring), `reachability-dispositions.json` rationale + module-list updated with the same reason; no develop rows lost |

### Negative composition claims re-proven at this head (all true)

- Row 8: `packages/maistro-core/src/maistro/container.py:1409`
  `if self.goal_reconciliation_policy is None: return 0`; the only source
  references are the field default (`:519`) and the guard itself — no
  production assignment or tick caller; `goals/reconciliation/wiring.py:128-135`
  warns "Goal reconciliation is in-memory despite a PostgreSQL backend" and
  answers a PostgreSQL pool with `InMemoryGoalStore()`.
- Row 11: `memory/working_graph/manager.py:38-39` `_embedded_factory` selects
  `create_backend("embedded", …)`; `memory/working_graph/backend.py:5,114`
  records the `ladybugdb` distribution as not published to this environment's
  package registry, so the literal Ladybug backend is not adoptable.
- Row 12: `promote_evidence` appears in `user_model/promotion.py`, its
  `__init__` re-export and `service.py` alone — tests and re-export only, no
  production caller; `recall_for_task` reaches production only through the
  owner-scoped `maistro_server/api/user_model.py` route.
- Row 18: `grep -rn "UserModel\|recall_for_task\|Attention"
  packages/maistro-design/src --include=*.py` → **0 matches**.
- Rows 2/5: `.github/workflows/release.yml:23-24` still self-declares
  "NOT YET EXERCISED … has never run"; all 36 local tags are `backup/*` /
  `orphan-bak/*` / pre-rebase lane tags — no release tags, so RC soak /
  byte-equivalent promotion has no executed evidence.

### Positive Row-19 seams re-inspected at this head

- `services/oauth_login.py:344-352`: `authenticate` invokes the JIT
  provisioner only for a verified, unlinked Entra identity; refusal falls
  through to the uniform denial with the decision audited.
- Structural pin `test_entra_jit_provisioning.py:890`
  (`assert not hasattr(entra_jit_module, "stores")`) and the strengthened
  disabled-JIT refusal test (`:497`) are present and pass in the 42 above.

### Verdict carried forward

Round 5-9 accounting is unchanged at this head and was independently
re-executed here. Milestone acceptance: **NEEDS-REPAIR** — rows 8 and 18 are
not met by current production composition; rows 2, 3, 5, 17 are UNVERIFIED
(operator release-pipeline, clean-machine/live-model, RC-soak and
discovery-pipeline evidence not obtainable in this environment); rows 4, 7, 9,
11, 12 are PARTIAL; rows 1, 6, 13 are deterministic-PASS and rows 10, 14, 15,
16 PASS in the collected backend inventory with live-UI inspection unverified;
row 19 is deterministic-PASS with declared live-tenant limits. The lane's own
repairs hold at this head and every CI gate this round touches is green with
CI's exact arguments, including the vulture per-identity ledger (no unbanked
identities; no ledger amendment required); what remains is program-scale
composition plus operator release evidence, not a defect in this branch's diff.

Progress: `{checked: 19, done: 0, skipped: 0, errors: 0, next: "implement rows 8/12/17/18 production composition on canonical seams; obtain operator release evidence"}`.

## Round 11 — composition repair for the row-8 tick-caller half (repair stage)

Starting HEAD `d17618fb737d` (exact match), worktree clean, no uncommitted
salvage. The ten prior rounds recorded the same actionable gap without
implementing it, so this round implements the bounded, evidence-backed half of
the row-8 finding that is reachable from this lane: the two M3 #806 Container
ticks had no production caller. No driver `check-*.log` files exist in this
job directory; every result below was executed fresh at this head.

### The repair (composition only, no new authority)

`hive-conductor/backend/services/canonical_recovery.py` — the operator
cadence that already ticks `recover_abandoned_attempts`,
`recover_stranded_chat_admissions` and `resume_parked_runs` (ADR-019:
bounded, idempotent, operator-scheduled) — now ticks the two Goal control
plane halves beside them:

- `goal_leases` → `Container.sweep_goal_leases`: policy-free fence mechanics,
  fully operational. A Goal claim whose holder stopped renewing is released in
  production and the Goal is marked due for the bounded sweep, so a dead
  reconciler's fence cannot pin a Goal forever.
- `goal_reconciliation` → `Container.reconcile_goals`: armed and safe. It
  decides only when a #805 reconciliation policy is composed onto the
  Container; without one it returns 0 and durable wakes stay pending facts
  for the composition that lands them. The Container's own contract ("the
  mechanics never invent what a reconciliation decision means") is preserved
  — this round deliberately does not invent #805's decision semantics, which
  remain owned by #805.

No competing scheduler, Goal store, event authority, or authorization path
was introduced: both ticks are the Container's own existing seams, ticked by
the operator loop the repo already uses for every other recovery sweep.

### Red-first regression proof (structure, not wall-clock)

Three tests join `test_canonical_recovery_cadence.py`, driving a real SQLite
Container through the production engine lookup the cadence uses. Run against
the pre-repair cadence: **2 failed, 1 passed** — the lapsed-claim test
initially passed for the wrong reason (`GoalReconciliationStore.claim` treats
a lapsed claim as claimable anyway) and was rewritten to assert the sweep's
own observable effects (`reconciliation_view()["claim"] is None` +
`["awake_after"] is not None`), after which it failed red too. Post-repair:
all 3 pass, including the negative control pinning that a production
Container without a policy never decides.

### Fresh validation (all exit 0, this round, this head)

| Command | Executed outcome |
| --- | --- |
| `uv run pytest packages/hive-conductor/backend/tests -q` | **4579 passed, 113 skipped** (246.6s; 4576 + the 3 new tests) |
| pre-repair red run: cadence `-k "goal_claim or composed_policy or without_a_policy"` | expected exit 1: 2 failed, 1 passed |
| `uv run pytest test_canonical_recovery_cadence.py + test_entra_jit_provisioning.py + test_hive_unwired_retire_2309.py -q` | **55 passed** |
| `uv run ruff check` / `ruff format --check` (touched files) | clean |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` | ok: 4692 unique identities match baseline + the recorded +3 delta, 0 duplicate evidence |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI args) | 1219 reviewed -> 1219 findings, no unbanked identities, no ledger amendment |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-workspace-retirement.py` (CI args) | 78 -> 78 tolerated importers, OK on 89 entries |
| `uv run python scripts/check-reachability.py` / `-dispositions.py` / `-provenance.py` | 1509 modules / 81 unreachable; no unauthorized expansion |
| `uv run python scripts/check-release-consistency.py` | released none / shipping 0.9.0 / working toward 1.0.0 (row 1) |
| `git diff --numstat origin/develop -- quality/` | exactly the documented lane deltas (reachability-baseline −1, dispositions +1/−1); no ledger edit this round |

Inventory note: `docs/testing/inventory-notes/issue-7-goal-reconciliation-ticks.md`
(records the +3 delta and the red-first evidence).

### Updated acceptance accounting (delta on Rounds 5–10)

- **Row 8: NOT MET → PARTIAL.** The tick-caller half of the finding is
  repaired: production now sweeps Goal lease fences and runs the bounded
  reconciliation sweep. What remains unmet: (a) no production assignment of a
  #805 `ReconciliationPolicy`, so the sweep still decides nothing — its
  decision semantics are #805-owned and were deliberately not invented here;
  (b) `wire_goal_reconciliation` still answers a PostgreSQL pool with
  `InMemoryGoalStore` — per that module's own docstring, SQLite is the
  declared durable backend for this control plane and the PG twin is the
  tracked follow-up (#1572 owns the canonical Goal PG store, a different
  plane).
- **Row 18: NOT MET, unchanged, not repairable in this round.** Wiring
  Design Studio's consumption of the shared user-memory surface requires
  composing `UserModelService` into the hive backend; that service is
  maistro-server-only and PostgreSQL-only by design (ADR-092526-4391), and
  inventing a hive-side lookalike would violate the exit condition it is
  meant to satisfy. Recorded as the next composition task, not guessed at.
- **Rows 2, 3, 5, 17: UNVERIFIED, unchanged** — release-pipeline execution,
  clean-machine/live-model E2E, RC soak/promotion and discovery-pipeline
  evidence require operator/release actions (and GitHub mutations this lane is
  prohibited from performing).
- Rows 4, 7, 9, 11, 12 PARTIAL and rows 1, 6, 10, 13–16, 19 PASS carry
  forward from Rounds 5–10 unchanged by this diff.

**Verdict: NEEDS-REPAIR for milestone acceptance stands.** The lane's own
slices and every CI gate this diff touches are green with CI's exact
arguments; one bounded composition repair landed with red-first tests; the
remaining gap is the #805 policy composition, the row-18 Design Studio
consumption composition, and operator release evidence — program-scale work
plus actions outside this lane's authority.

Progress: `{checked: 19, done: 1, skipped: 0, errors: 0, next: "compose #805 policy semantics and hive-side UserModelService consumption (row 18) on canonical seams; obtain operator release evidence"}`.

## Round 12 — composition repair for row 18: Design Studio consumes the shared surfaces (repair stage)

Job `073074952f4c475299767068eee8ed5b`; starting HEAD `183445ae`
(the round-11 commit); worktree clean on arrival; no incoming uncommitted patch.

The verify round at this head re-proved row 18 NOT MET: no reachable
production path made Design Studio consume the persistent Agent's shared
user-memory/Attention surfaces (#777/#773). This round lands exactly that
composition, on canonical seams only:

- **`packages/hive-conductor/backend/services/user_model.py` (new)** —
  composes the ONE `maistro.memory.user_model.service.UserModelService` (the
  same service `maistro_server.main` wires, `packages/maistro-core`) over the
  deployment's PostgreSQL session factory — the same factory the design
  services resolve, and the same PostgreSQL-only shape (ADR-092526-4391).
  Recall-only: no write surface, no second read path, and **no in-memory
  lookalike** — without the configured PostgreSQL the resolver answers
  `None` and callers degrade by recalling nothing. The user model's writes
  (correct/forget/promotion) stay on the Agent and API surfaces that own
  them.
- **`services/brief_chat.py`** — the interview opening (the flow where
  Design Studio opens work) now consumes both shared surfaces: recalled,
  provenance-bearing user-model facts (`user_context`, capped at
  `DESIGN_RECALL_LIMIT`, PERSONAL sensitivity — the `RecallQuery` default)
  and the Workspace's shared Attention projection
  (`services.attention.list_attention`, #1049). Both ride the payload as
  data; the deterministic interview phrasing is untouched (ADR-091726-7c2a
  preserved). `payload()` now also exposes the turn's `citations` (the
  field existed; it was never serialized) and omits an unavailable
  surface's key entirely — never an empty list dressed up as a read model.
- `packages/maistro-design` gains nothing, by design: it is the creative
  projection library (#774/#775), holds no memory of its own, and the exit
  condition forbids exactly that private variant. The product surface that
  consumes is the hive backend where Design Studio composes.

### Red-first regression proof (structure, not wall-clock)

The six tests in `test_design_shared_surfaces.py` were run against the
pre-repair head `183445ae` in a throwaway worktree with the same file
copied in: **3 failed, 2 errors, 1 passed**. The two shared-surface HTTP
tests and the resolver test failed; the recall unit tests errored on the
absent `services.user_model` module (the composition did not exist); only
the outage-degradation control passed, because "the key is omitted" is the
invariant that test pins across both repair states. Post-repair: 6 passed.
`test_chat_brief_interview.py` → 19 passed; `test_attention_projection.py`
+ `test_brief_commit.py` → 38 passed, 32 skipped (no regression on the
touched surfaces).

### Fresh validation (all exit 0, this round, this head)

| Command | Executed outcome |
| --- | --- |
| `uv run pytest packages/hive-conductor/backend/tests -q` | **4585 passed, 113 skipped** (233.4s; 4579 + the 6 new tests) |
| `uv run ruff check` / `ruff format --check` | clean |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` | ok: baseline + recorded +6 delta |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI args) | no unbanked identities, no ledger amendment |
| `uv run python scripts/check-release-consistency.py` | released none / shipping 0.9.0 / working toward 1.0.0 (row 1) |

Inventory note: `docs/testing/inventory-notes/issue-7-design-studio-shared-surfaces.md`
(records the +6 delta and the red-first evidence).

### Updated acceptance accounting (delta on Rounds 5–11)

- **Row 18: NOT MET → composition landed for the user-memory/Attention
  halves.** Design Studio's work opening now demonstrably consumes the same
  `UserModelService` and the shared Attention projection through the
  backend, with red-first tests. What remains for full row-18 closure is
  the #804 consumption half — Design Studio consuming the persistent
  Workspace Agent/Goal-reconciliation APIs rather than instantiating
  private ones (#777's criterion 1/3/4 verification boundary) — which is
  the #805 policy composition below, not a Design-Studio-private fix.
- **Row 8: PARTIAL, unchanged this round.** The tick-caller half landed in
  Round 11. The remaining halves are (a) the #805 `ReconciliationPolicy`
  production composition — decision semantics deliberately not invented in
  a repair lane, because a guessed policy would be a second authority —
  and (b) the reconciliation control plane's PostgreSQL twin (#1572 owns
  the canonical Goal PG store; this plane's PG twin is the tracked
  follow-up).
- **Rows 2, 3, 5, 17: UNVERIFIED, unchanged** — release-pipeline execution,
  clean-machine/live-model E2E, RC soak/promotion and discovery evidence
  require operator/release actions (and GitHub mutations this lane is
  prohibited from performing).
- Rows 4, 7, 9, 11, 12 PARTIAL and rows 1, 6, 10, 13–16, 19 PASS carry
  forward from Rounds 5–10 unchanged by this diff.

**Verdict: NEEDS-REPAIR for milestone acceptance stands** — but the
code-level row-18 gap this round was named for is repaired with red-first
tests on canonical seams; the remaining gaps are the #805 policy
composition, the control-plane PG twin, and operator release evidence.

Progress: `{checked: 19, done: 2, skipped: 0, errors: 0, next: "compose #805 reconciliation policy on canonical seams (row 8); obtain operator release evidence (rows 2/3/5)"}`.

## Round 13 — develop-base sync (M3-E5 #1051 proactive discovery) + merged-head validation (repair stage)

Job `09e5a281c60243d9bdd33817b462c221`; starting HEAD `a2407aa3cc` (exact match,
the round-12 commit plus the EPIC M8-A merge `4f8f40352d`); worktree clean on
arrival; the prior job (`e63ff45c`) died at spawn (worker_error, 0 checks) and
left nothing to salvage; no driver `check-*.log` files exist in this job
directory, so every result below was executed fresh at this round's heads.

### Why the sync was required (quality-row provenance, not a guess)

`git diff --numstat origin/develop -- quality/` at `a2407aa3cc` showed a
**0/30 deletion** in `quality/shipped-surface-truth.json` beyond the two
documented lane deltas. Provenance pinned by file history: the branch's last
touch of that file is `5ca5a969d1`; develop's tip `8d8f10616f` (M3-E5) modified
it after the branch diverged — the 30 rows are **develop-side additions the
branch predated**, not a silent row loss. Only that one commit separated the
branch from its declared develop base (`git log HEAD..origin/develop` → exactly
`8d8f10616f`; merge-base `4f8f40352d`). `git merge-tree --write-tree` reported
**zero conflicts**, and the lane brief directs resolving the branch against its
declared base. Merged as `4a682e7c26` with no manual resolutions.

### What the sync brings: the #1051 bounded proactive-discovery pipeline (row 17)

develop's `8d8f10616f` ships, on canonical seams only (no second scheduler,
no new authority — `services/discovery.py` module docstring: "cycles are
triggered by callers that already hold a" schedule authority, fired through
`run_registered_dag` like a schedule fire):

- maistro-core: `capabilities/providers/discovery_source.py` (Binding-declared
  source allowlist, governed egress), `discovery_source_fetch` / `discovery_scout`
  / `discovery_curate` node kinds, `discovery_context` Container authority
  (bare default provides nothing), `seeds/proactive_discovery.py`;
- hive-conductor: `services/discovery.py` (config off-switch, durable day-keyed
  budget ledger charged once per Run, seen-fingerprint suppression,
  `_lift_pending_scheduled_runs` consuming scheduled fires through the canonical
  admitter), `routes/discovery.py` (member-scoped, auth-tested), Attention
  Waiting-by-default + deadline-evidence escalation, Home adaptive candidates,
  keep/dismiss category preferences; `dag_agents.py:159` registers
  `proactive_discovery_seed()` in the production DAG registry;
- `quality/shipped-surface-truth.json` +30 rows (the three new mutating routes
  classified) — the diff-vs-develop anomaly above is resolved;
- develop's own inventory notes (`1051-*.md`, `auto-1051-bf91.md`) arrive with
  the tests, so no new inventory delta arises from this round (verified below:
  the merged baseline matches collection exactly).

### Fresh validation at the merged head `4a682e7c26` (all exit 0, this round)

| Command | Executed outcome |
| --- | --- |
| `uv sync --locked --extra dev` | ok (+defusedxml, +types-defusedxml; uv.lock from the base) |
| `uv run ruff check .` | All checks passed! (warnings only: develop's intentional `# noqa: vulture` markers) |
| `uv run ruff format --check .` | 3698 files already formatted |
| `uv run pytest packages/hive-conductor/backend/tests -q --timeout=120` | **4639 passed, 118 skipped** (264.2s; 4757 collected = recorded inventory) |
| `uv run pytest packages/maistro-core/tests/graph/nodes/test_discovery_pipeline.py test_idempotent_replay_conformance.py test_container_node_composition.py -q` | **112 passed** |
| `uv run pytest packages/maistro-turing/tests/test_runtime.py packages/maistro-turing/backend/tests/test_chat.py formal/models/test_execution_lifecycle.py packages/maistro-rsi/tests/test_m8a_assurance_baseline_research.py -q` | **105 passed** (first validation of the M8-A merge content, which round 12 predated) |
| `uv run python scripts/check-suite-inventory.py` (CI's exact invocation, `ci.yml:751`) | ok: **21 suites match**, 37382 collected identities, 0 duplicate evidence |
| `uv run python scripts/check-test-duplicates.py` | ok: 0 byte-identical groups |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI args, `quality.yml:1630-1634`) | exit 0: 1219 reviewed → 1219 findings, unclassified 0 — no unbanked identities, no ledger amendment |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-workspace-retirement.py` (CI args, `quality.yml:1148`) | exit 0: 78 → 78 tolerated importers, OK on 89 entries |
| `uv run python scripts/check-shipped-surface-truth.py` | "Shipped-surface truth matrix is complete" |
| `uv run python scripts/check-release-consistency.py` | ok: released none / shipping 0.9.0 / working toward 1.0.0 (row 1) |
| `uv run python scripts/check-reachability.py` / `-dispositions.py` / `-provenance.py` | 1519 modules / 81 unreachable; 27 groups disposed; no candidate-approved expansion |
| `uv run mypy packages/maistro-core/src packages/maistro-server/src packages/maistro-turing/src packages/maistro-canvas/src packages/maistro-bootstrap/src packages/maistro-registry/src packages/maistro-ext-sdk/src` | **Success: no issues found in 970 source files** |
| `git diff --numstat origin/develop -- quality/` | exactly the documented lane deltas (`reachability-baseline.json` −1, `reachability-dispositions.json` +1/−1); the shipped-surface −30 anomaly is gone |

### Updated acceptance accounting (delta on Rounds 5–12)

- **Row 17 (#1051): UNVERIFIED → PARTIAL, deterministic-PASS of the shipped
  pipeline.** The prior finding "no idle/overnight proactive discovery pipeline
  ships" was true at `a2407aa3cc` and is superseded by the sync: the bounded
  fetch/scout/curate pipeline, its canonical seed (production-registered),
  durable budgets, suppression, Waiting/Home surfacing, feedback preferences and
  the scheduled-fire lift path now ship and are green in the collected inventory
  (core pipeline 112, conductor discovery routes/service tests within the 4639).
  What remains for full closure is live operator evidence — an actual overnight
  fire against real sources in a deployed environment and curation quality under
  a real model — which this lane cannot execute (live-model/tenant evidence,
  prohibited GitHub/release mutations).
- **Row 8: PARTIAL, unchanged** — re-pinned at this head:
  `container.py:1426` `if self.goal_reconciliation_policy is None: return 0`;
  grep for a production `goal_reconciliation_policy=` assignment returns none.
  The tick-caller half landed in Round 11; the decide-half belongs to #805's
  policy composition (deliberately not invented in a repair lane) and the
  control-plane PG twin is the tracked follow-up (#1572).
- **Row 12: PARTIAL, unchanged** — `promote_evidence` still has no production
  caller (definition, docstring and re-export hits only).
- **Rows 2/5: UNVERIFIED, unchanged** — `.github/workflows/release.yml:23-24`
  still self-declares "NOT YET EXERCISED … has never run"; `git tag -l 'v*'`
  counts 0. Release-pipeline execution and tags are operator actions with GitHub
  mutations this lane is prohibited from performing.
- **Row 18: composition landed (Round 12), carries forward unchanged**; the
  #804 consumption half (Design Studio consuming the persistent Agent's
  Goal/reconciliation APIs rather than private instantiations) is the remaining
  verification boundary.
- Rows 3/4/7/9/11 PARTIAL and rows 1, 6, 10, 13–16, 19 carry forward from
  Rounds 5–12 unchanged by this diff (clean-machine/live-model E2E, backup/
  restore soak, RC promotion, KNOWN-GAPS operator dispositions remain
  operator-evidence items).

**Verdict: NEEDS-REPAIR for milestone acceptance stands**, now on a narrower
basis: every CI gate this branch touches is green with CI's exact arguments at a
head fully synced to its declared develop base, and the row-17 capability gap is
closed in code with tests; what remains is (a) the #805 reconciliation-policy
composition (row 8 decide-half), (b) the #804 Design-Studio/Agent consumption
verification (row 18 tail), (c) the promote_evidence production producer (row
12), and (d) operator release/live evidence (rows 2/3/5 and the soak/promotion
halves) — program-scale work and actions outside this lane's authority.

No test was added by this round (the sync's tests arrive with develop's own
inventory notes), so no new inventory delta arises; the merged baseline was
verified to match collection exactly (21/21 suites above).

Progress: `{checked: 19, done: 1, skipped: 0, errors: 0, next: "compose #805 policy semantics (row 8 decide-half); verify the #804 Design-Studio consumption tail (row 18); obtain operator release/live evidence (rows 2/3/5, row 17 live half)"}`.

## Round 14 — bounded exact-debt-ledger repair investigation

Job `8a92fbf73dc240a0873dc95d69c57849`; starting HEAD
`cc0b03ac52bf295eb14052cb4689bb4496d56f49`; declared develop base
`8d8f10616fb7ae984a02bf84553489470d03c726`. Both refs resolve locally.
Initial status/diff were empty; all prior committed work is preserved.
Frozen item: the explicitly dispatched Vulture CI repair, not a new
milestone-wide implementation. Earlier runtime/no-artifact cycles are
addressed by bounding this round and committing its actual result.

**The alleged gate failure does not reproduce.** The exact required scan
passes with Vulture 2.16: **1219 reviewed identities = 1219 findings**, zero
unclassified and zero never-allowlist findings. The ledger has no diff from
the supplied base. No unbanked or stale identity was reported, so there is
no evidence-backed source fix or ledger amendment to make. Do not add
speculative ledger entries or change gates to manufacture a repair.

Repository instructions, quality-gate documentation, the actual
`vulture-ratchet.yml` owner, scanner implementation and adjacent ownership
tests were inspected. Accepted ADR-080 and ADR-082226-5104 preserve memory
consent, PostgreSQL authority, isolated disposable working projections and
ordinary-Run consolidation. No authority, policy, source, test or ledger is
changed by this round. No test additions means no inventory delta note is
needed. This section is an evidence handoff, not a behavioral repair.

### Fresh validation

All commands below exited 0. Logs are `worker-*.log` in the job directory.
No `check-*.log` exists in this job directory; the five logs referenced by
the supplied previous result were read separately as historical evidence,
not substituted for these executions.

| Executed command | Observed result |
| --- | --- |
| `uv sync --locked --extra dev` | 466 resolved, 218 checked |
| `uv run ruff check .` | all checks passed |
| `uv run ruff format --check .` | 3698 files already formatted |
| `uv run pytest tests/test_ci_vulture_ownership.py packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py packages/hive-conductor/backend/tests/test_design_shared_surfaces.py packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py packages/hive-conductor/backend/tests/test_hive_unwired_retire_2309.py -x -q` | **141 passed**, one dependency warning |
| `uv run python scripts/check-ratchet-provenance.py` | 55 quality JSON consumers have explicit provenance |
| `uv run python scripts/check-shipped-surface-truth.py` | matrix complete |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1219 reviewed = 1219 findings |
| `uv run python scripts/check-release-consistency.py` | released none, shipping 0.9.0, target 1.0.0 |
| `uv run python scripts/check-contract-markers.py` | claims evidenced or recorded; **not** proof of all milestone acceptance |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` | 4757 collected IDs match; no duplicate evidence; collection is not execution |

The provenance, shipped-surface, Vulture, release-consistency, contract-marker
and inventory commands explicitly used
`RATCHET_BASE_REV=8d8f10616fb7ae984a02bf84553489470d03c726`.
Existing pytest deprecations and two AST escape-sequence warnings remain.

### Acceptance boundary (this round only)

| Issue #7 exit row | Fresh evidence or explicit unverified boundary |
| --- | --- |
| 1 metadata | Release-consistency command passes; no released version is claimed. |
| 2 release workflow | UNVERIFIED. `release.yml:23–24` still says never exercised; local `git tag -l 'v*'` count is 0. Neither is proof of remote execution history. |
| 3 clean-machine/live-model E2E | UNVERIFIED; dependency sync and local doubles do not prove this. |
| 4 backup/restore/escrow | UNVERIFIED this round; earlier deterministic tests are not a fresh deployed drill. |
| 5 RC soak/byte-equivalent promotion | UNVERIFIED; no operator artifacts supplied or created. |
| 6 all KNOWN-GAPS dispositions | UNVERIFIED beyond structural contract-marker validation; all dispositions were not individually audited this round. |
| 7 durable backlog cutover or accepted release deferral | UNVERIFIED this round; no owner acceptance inferred from prose. |
| 8 operational persistent Agent | NOT MET in inspected composition: `container.py:1426–1427` returns 0 without a policy; production `packages/*/src` search found no `goal_reconciliation_policy=` assignment. Cadence tests prove ticks with injected policy, not an operational decision policy. |
| 9 evidence-backed Goal truth | UNVERIFIED this round; cadence execution does not establish the entire completion contract. |
| 10 canonical inspection | UNVERIFIED this round; inventory collection is not behavioral proof. |
| 11 isolated Ladybug projection | UNVERIFIED this round; ADR names Ladybug, not an interchangeable dictionary test double. |
| 12 Dreaming-to-user-fact-to-recall | NOT MET in inspected core composition: production `packages/*/src` hits for `promote_evidence` are definition, import/export and documentation only. Design tests promote facts in fixtures, not through production Dreaming. |
| 13 private memory boundaries | PARTIAL: executed Design tests reject foreign/irrelevant/sensitive facts; complete private/domain-memory contract UNVERIFIED. |
| 14 optional pinned Home | UNVERIFIED this round. |
| 15 adaptive restore/settings | UNVERIFIED this round. |
| 16 durable Attention ordering/escalation | UNVERIFIED beyond Design's shared projection composition tests. |
| 17 overnight discovery | UNVERIFIED this round; no deployed overnight/live-model evidence. |
| 18 Design shared surfaces | PARTIAL: executed real chat-route tests consume shared user-model/Attention seams; fixture-injected services and facts do not establish operational persistent-Agent/Dreaming composition. |
| 19 Entra group-gated JIT | Deterministic production-path tests pass in the focused batch, including fail-closed pagination and disabled-JIT refusal; live tenant behavior UNVERIFIED. |

**Verdict: NEEDS-REPAIR for issue #7, not a reproduced Vulture defect.**
No GitHub mutations, remote enumeration, release actions, new tests or quality
ledger edits. The local evidence commit is a handoff only. Remaining work is
policy/producer composition and operator acceptance evidence, not scanner
bookkeeping. Gate item checkpoint:
`{checked: 1, done: 1, skipped: 0, errors: 0, next: "resolve milestone production-policy/producer gaps and obtain operator evidence in separately bounded work"}`.

## Round 15 — independent verification at the develop-synced head

Job `ce9e343bf7fb4700a9f6162daaa00b5c` (phase: verify); starting HEAD
`2d1ba0582cda8cef4c36acaf00a3e01f01a37ea8` (exact match); declared develop
base `80242f28521bba184f4d5d62cda972c1c8928f36`. Worktree clean at the
assigned head — no uncommitted salvage. Delta since the round-14 head
`cc0b03ac52` is the branch docs commit `160c889767` (handoff-only) plus the
develop merge `80242f2852` (M5-B RSI quarantine); no lane behavior changed,
so the round-14 acceptance boundary carries forward unchanged.

### Executed this round (all commands exited 0 unless noted)

Driver logs in the job directory (`check-0.log` … `check-4.log`): `uv sync
--locked --extra dev`, `uv run ruff check .` (all checks passed), `uv run
ruff format --check .` (3701 files), lane pytest batch (61 passed), suite
inventory `--suite packages/hive-conductor/backend/tests` (4757 IDs, no
duplicate evidence). Re-executed independently at the head: lane pytest +
`tests/test_ci_vulture_ownership.py` → **141 passed**; `uv run ruff check .`
→ passed; exact-CI-args Vulture gate
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` with `RATCHET_BASE_REV=80242f2852…` → **1218
reviewed = 1218 findings** (row count moved with the new declared base, both
sides consistent); `scripts/check-ratchet-provenance.py` → OK, 55 consumers,
0 violations; `scripts/check-release-consistency.py` → ok (released none,
shipping 0.9.0, target 1.0.0); suite inventory → ok.

### Deterministic acceptance re-execution (row boundary unchanged)

- Rows 2/5 (release workflow exercised; RC soak/byte-equivalent promotion):
  `.github/workflows/release.yml:23-24` still self-declares "NOT YET
  EXERCISED … has never run"; local `git tag -l 'v*'` count = **0**. No
  operator evidence obtainable in-lane → UNMET/UNVERIFIED.
- Row 8 (persistent Agent decide-half): `container.py:1426-1427`
  `reconcile_goals` returns 0 when `goal_reconciliation_policy` is None
  (field default `None` at `container.py:535`); repo-wide non-test grep for
  a `goal_reconciliation_policy` **assignment** across `packages/` and
  `scripts/` → **zero hits**. Tick/fencing/failover tests pass with injected
  policy; no operational decision policy is composed → NOT MET.
- Row 12 (Dreaming→user-fact→recall producer): `promote_evidence` occurs in
  production `packages/*/src` only as definition (`promotion.py:154`),
  re-export (`user_model/__init__.py:10,51`) and docstrings
  (`user_model/service.py:10`, `hive-conductor discovery.py:30`) — no
  production caller → NOT MET.
- Rows 3/4/17 (clean-machine/live-model E2E, backup/restore escrow drill,
  live overnight discovery fire): no operator/deployed evidence supplied or
  creatable in-lane → UNVERIFIED; #1051 pipeline remains production-wired
  but live-half PARTIAL.
- PR #2529 live read-only refresh at verification time: still DRAFT, head
  matches the assigned SHA, **all 26 CI checks QUEUED** — no green-CI or
  integration claim is possible.
- Closure-keyword scan: PR body ("Refs #7") and every commit message in
  `80242f28…HEAD` → no fixes/closes/resolves keywords; no premature issue
  closure.

**Verdict: NEEDS-REPAIR for issue #7, carried on the same narrowed basis as
round 14.** Deterministic quality gates pass; the unmet rows are policy/
producer composition (rows 8/12) and operator acceptance evidence
(rows 2/3/4/5/17), unreachable from this lane. No GitHub mutations, no
ledger edits, no gate changes. Checkpoint:
`{checked: 19, done: 0, skipped: 0, errors: 0, next: "compose an operational goal-reconciliation policy and a production Dreaming promotion caller; obtain operator release/E2E/soak evidence; re-verify when CI on the PR completes"}`.

## Round 16 — writer repair: the #805 decide-half composed in production

Job `6c3036a29e5244b483bd56b325b09b64` (phase: repair); starting HEAD
`abfc1cdee4ffcde01f8f1ce9eff0562197a4c90a` (exact match); develop base
`80242f28521bba184f4d5d62cda972c1c8928f36`. Worktree clean at the assigned
head — no uncommitted salvage. The job directory supplied no `check-*.log`
files, so every check below was executed fresh.

### What was repaired (row 8, the decide-half)

Rounds 6–15 recorded one repeatable code-level defect: `create_container`
wired the #806 reconciliation *mechanics* but composed no `goal_reconciliation_policy`,
so `reconcile_goals` returned 0 forever in production and the Workspace
Agent never decided. This round composes the decide-half on the canonical
seams, with no second scheduler, execution authority, or Goal store:

- `packages/maistro-core/src/maistro/goals/reconciliation/production.py`
  (new): `FactDrivenReconciliationPolicy` — deterministic decisions from
  durable `GoalFacts` only (progress on fresh capacity or an unblocking
  wake, wake-driven wait for in-flight pursuit, budget gate, replan keyed
  by the triggering wake's canonical correlation id, discovery of the
  never-notified Goal under one stable key). It never settles a Goal:
  completion stays evidence-backed desired-state truth (#9), never inferred
  from a Run terminal status. `GoalRunAdmitter` — the `PhysicalAdmitter`
  half: fulfils a run admission as one canonical QUEUED Run through
  `admit_direct_work`, bound to the Goal and the canonical **current**
  revision with that revision's exact language; the canonical Goal is the
  revision authority (the control row's revision is posture bookkeeping and
  may trail it). Unknown canonical Goals, revisions missing from the chain
  and non-run admission kinds refuse loudly per-Goal.
- `maistro/runs/sources.py`: `GOAL_RECONCILIATION_SOURCE` ("goal_reconciliation"),
  named in the leaf module so admitter, consumer allowlist and retention
  agree on the string without importing each other.
- `maistro/runs/consumption.py`: the source joins `CONSUMABLE_SOURCES` —
  deliberate, reviewed: a pursuit Run is admitted QUEUED with no caller
  holding a receipt, so excluding it would recreate the
  admitted-work-nobody-executes state #251 removed for schedules.
- `maistro/container.py`: `create_container` composes
  `FactDrivenReconciliationPolicy` + `GoalRunAdmitter(run_store, goal_store)`
  onto the Container; `reconcile_goals` passes the admitter to the
  reconciler so admissions become canonical Runs. A hand-built Container
  without a policy still decides nothing (contract re-pinned in tests).

The four milestone verbs map honestly onto this composition: **progress**
(admit the pursuit Run), **wait** (wake-driven park / budget gate),
**delegate** (the pursuit Run's single node is in-process A2A delegation to
the Goal's accountable Agent — the same `agent.delegate_remote` node every
task executes through), **replan** (a new canonical change produces a new
correlation-keyed admission against the current desired state). Goal→Subgoal
*decomposition* — choosing that a Goal should split, and into what — remains
planner-owned product surface (the same class of deferral as the Dreaming
producer under #1046): the mechanics support `kind="subgoal"` admissions,
the production admitter refuses them loudly rather than minting Goals nobody
described, and the policy never invents a split.

Deliberately not wired this round: the `EventWakeBridge` on the canonical
event bus. `GOAL_WAKE_PATTERNS` maps event types ("run.terminal",
"goal.changed", …) that no production emitter publishes yet, so subscribing
the bridge now would be unreachable dead code; durable wakes are recorded
through the store API and the bounded sweep repairs missed notifications
(deterministic-tested). Wiring the bridge belongs with the first canonical
event producer for those types.

### Tests

- `packages/maistro-core/tests/goals/test_goal_reconciliation_production.py`
  (new, 16 tests): policy determinism (7), admitter fulfilment and refusals
  (6 incl. the pinned consumable source), composed-Container end-to-end over
  SQLite (3): discovery → canonical QUEUED Run → consumer tick claims it and
  leaves real NodeRun/Attempt rows (`Goal -> Graph -> Run -> NodeRun ->
  Attempt`), revision bump + durable wake → replan into a Run bound to
  revision 2 and its language. Inventory note:
  `docs/testing/inventory-notes/goal-reconciliation-production-decide-half.md`
  (`packages/maistro-core/tests: +16`).
- `packages/maistro-core/tests/goals/test_goal_container_wiring.py`: the
  wiring test now pins the production composition; the hand-built no-policy
  contract and the mechanics-only StubPolicy tests keep their meaning with
  the admitter explicitly detached.
- `packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py`:
  the two former no-op-contract tests became production-path tests through
  the real cadence tick on SQLite (missed wake → one canonical Run + dispatched
  wake, tick-idempotent; never-notified Goal → discovered into one canonical
  Run). Suite count unchanged (2 rewritten, net 0).

### Validation (all fresh at this head, all exit 0)

| Command | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/goals packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py -q` | **192 passed**, 24 skipped |
| `uv run pytest packages/maistro-core/tests/runs/test_consumption*.py packages/maistro-core/tests/runs/test_consumer_claim_*.py -q` | **50 passed**, 5 skipped |
| `uv run pytest tests/test_ci_vulture_ownership.py packages/hive-conductor/backend/tests/test_design_shared_surfaces.py packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py packages/hive-conductor/backend/tests/test_hive_unwired_retire_2309.py -q` | **128 passed** |
| `uv run ruff check .` / `uv run ruff format --check .` | all checks passed / 3703 files formatted |
| `uv run mypy packages/maistro-core/src` | clean for all touched files (one pre-existing env-only `maistro_bootstrap.cli` stub note in `cli/_install.py`, untouched by this round) |
| `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **1218 reviewed = 1218 findings** — zero unbanked identities introduced |
| `scripts/check-reachability.py` | exit 0 (1521 modules, 81 unreachable — ledger match) |
| `scripts/check-suite-inventory.py --suite packages/maistro-core/tests` and `--suite packages/hive-conductor/backend/tests` | ok (+16 delta recorded; hive count unchanged) |
| `scripts/check-ratchet-provenance.py` / `check-wiring-reads.py` / `check-release-consistency.py` / `check-backlog-consistency.py` / `check-radon-baseline.py` / `check-shipped-surface-truth.py` / `check-promotion-surface.py` | all ok (radon 124 = 124) |

### Acceptance boundary after this round

- Row 8 decide-half: **MET in code** — production composition with
  deterministic tests at both the unit and composed-Container level; the
  live/cadence halves remain deterministic (SQLite container + real cadence
  tick), not a deployed-process observation.
- Row 12 (Dreaming promotion producer): unchanged — deferred under #1046,
  KNOWN-GAPS disposition in place. Not addressed this round (separate
  producer, separate seam).
- Rows 2/3/4/5/17 (release workflow exercise, clean-machine/real-model E2E,
  backup/restore escrow drill, RC soak/byte-equivalent promotion, live
  overnight fire): unchanged — operator evidence, unobtainable in-lane.

Checkpoint: `{checked: 19, done: 1, skipped: 0, errors: 0, next: "operator release/E2E/soak evidence (rows 2/3/4/5/17); Dreaming promotion producer (row 12) on its own lane; canonical goal-event producers to make the wake bridge reachable"}`.

## Round 17 — fresh bounded verification at 1d4ee146d5fa

No `check-*.log` files were supplied in this job directory. I independently reran
focused checks against the assigned head; this round adds no product implementation
and does not treat suite success as operator evidence:

- `uv run ruff check .` and `uv run ruff format --check .`: passed; 3719 files
  already formatted.
- `uv run pytest packages/maistro-core/tests/goals/test_goal_container_wiring.py packages/maistro-core/tests/goals/test_goal_reconciliation_production.py -q -x`:
  23 passed.
- `uv run pytest packages/hive-conductor/backend/tests/test_canonical_recovery_cadence.py packages/hive-conductor/backend/tests/test_design_shared_surfaces.py packages/hive-conductor/backend/tests/test_entra_jit_provisioning.py packages/hive-conductor/backend/tests/test_hive_unwired_retire_2309.py -q -x`:
  61 passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  1217 reviewed identities = 1217 findings; no unbanked identities.
- `uv run python scripts/check-release-consistency.py`: passed, release state
  reports none released, shipping 0.9.0, working toward 1.0.0.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`:
  inventory matches 4757 collected node IDs.
- `git tag -l 'v*'` returned no tags at this head.

Acceptance remains blocked by the same concrete evidence boundary: release
workflow exercise, clean-machine/real-model E2E, backup/restore escrow drill,
RC soak and byte-equivalent promotion, and live overnight operation lack
operator evidence; the production Dreaming promotion caller is still explicitly
deferred under #1046. These are not established by the passing deterministic
checks above. ADR-080 and ADR-082226-5104 remain the governing memory model; no
alternative scheduler, memory authority, or authorization path is introduced.
