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
