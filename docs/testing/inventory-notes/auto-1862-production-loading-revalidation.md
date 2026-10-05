# Issue #1862 — production loading before generic composition-guard collection, revalidated at lane head

Lane L1862 (implement + verify + repair), jobs `1a2aec658d754c9ba3f9344245ce27fa`
and `6ecf8f7921b14dc493f2fe4b5a394413`, worktree `~/Git/wt/auto-1862`, branch
`auto-1862`, base = head before this note = `afb8659ac4829ad8d674fdd7e92ad24e2a4dc2a9`
(develop tip). Every piece of evidence below was executed in this lane against
that exact revision; nothing is inherited from prior-round claims. The
repair round (job `6ecf8f7921b14dc493f2fe4b5a394413`) re-executed every
section at the lane head `56343cd1969bec7ccca40913f2d0dcf85db3e761`
(= `afb8659a` + develop merges `534d475e`/`94781cf6`; the only lane-specific
diff at that head is this note) — see "Repair-round revalidation" below.

## Reconciliation with the landed implementation

#1862 was filed 2026-10-03 against develop `8c8fc8d67`, where both guards
still derived `shipped_kinds()` from process-local `list_kinds()`. PR #1935
(commit `4010e69f6`, 2026-10-04, under parent issue #1082) landed the shared
helper `packages/maistro-core/tests/graph/nodes/_production_registration.py`
and the universe proof `test_production_registration_universe.py` before this
lane ran; `git merge-base --is-ancestor 4010e69f6 HEAD` holds at this head.
This lane therefore performed focused revalidation of every #1862 acceptance
criterion at the merged revision. No code repair was needed; no test count
moved, so this note records no `inventory-delta`.

## Acceptance criteria -> executed evidence

- **Fresh interpreter, only the two guard modules, all eleven creative
  registrations**: `uv run pytest
  packages/maistro-core/tests/graph/nodes/test_node_composition.py
  packages/maistro-core/tests/graph/nodes/test_container_node_composition.py
  -v --tb=short` -> **137 passed**; all eleven `creative.*` identities appear
  in both sweeps' parametrizations. The audited counterfactual executes as a
  regression: `test_a_bare_core_import_misses_what_loading_adds` (passed), and
  the same probe run by hand at this head reports the core-only selection at
  **19 non-test kinds with zero `creative.*`**.
- **Same loading boundary, no per-kind hand-written assertions**: both guard
  files import `_production_registration` (the only loading path either uses);
  the Container identity sweep parametrizes over the reconciled universe
  (`test_the_container_resolver_composes_every_production_kind`, 30 params)
  and `test_the_composition_sweeps_use_this_universe` +
  `test_the_declaring_sweep_is_a_subset_of_the_reconciled_universe` pin both
  sweeps to that one universe.
- **Collection-order independence**: node-composition alone -> 99 passed;
  container alone -> 38 passed; reversed file order -> 137 passed; a broader
  four-file selection including `test_base_contract.py` -> 162 passed; the
  full CI selection (below) -> unchanged universe. Test fixtures stay
  excluded (`test.*` filters plus the AST source scan;
  `test_test_shaped_registrations_never_enter_the_universe` passed).
- **Loader import failure is visible**: with an out-of-tree shim whose
  `sys.meta_path` finder raises `ImportError` on `maistro_design.creative_nodes`
  (the mechanism `importlib.import_module` — the loader's own import path —
  actually uses; a `builtins.__import__` patch does *not* intercept it),
  collection of **each** guard file **errors** ("Interrupted: 1 error during
  collection", exit 2) — no skip, no empty successful sweep. The shim lived
  outside the tree. (Repair-round precision fix: the earlier wording said a
  bare `sitecustomize` shim; the failing hook must sit on `sys.meta_path`.)
- **Negative cases**: bare-resolver refusal, named missing authority,
  synth-dag store regressions, production-wiring omission, and the #1165
  fail-closed Warden/Sentinel seam -> `-k` selection over them gives
  **34 passed** (node-composition) and **1 passed** (container seam pin).
- **CI selection unchanged**: `.github/workflows/ci.yml` `test` job still
  runs `uv run pytest packages/maistro-core/tests -v --tb=short`
  (`REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`); no new job. Executed at this
  head with CI's env: **12399 passed, 890 skipped, 1 xfailed** in 345.97s,
  exit 0.

## Selected production identities at this revision

30 kinds enter the guards, all through loaded reachable production modules:
19 core through the `maistro.graph.nodes` catalog sweep (`agent.delegate_remote`,
`agent.remote_work`, `agent.spawn_harness`, `agent.synth_dag`, `airtable.poll`,
`compliance.block`, `dashboard.append_section`, `human.approve_draft`,
`human.ask_question`, `human.delegate_to_role`, `human.review_and_edit`,
`jira.poll`, `jira.wait_for_subtasks`, `llm.summarize`,
`rsi.quota_pace_trigger`, `transform.alias_keys`,
`transform.extract_field`, `transform.filter_by_type`,
`transform.format_markdown`) and the eleven creative kinds through
`maistro_design.creative_nodes` (`creative.acceptance`,
`creative.artifact_generate`, `creative.artifact_plan`,
`creative.brief_resolve`, `creative.copy_platform`, `creative.cross_critique`,
`creative.message_architecture`, `creative.publish_export`,
`creative.research_evidence`, `creative.targeted_refinement`,
`creative.visual_direction`). Captured from `--collect-only` at this head.
`maistro_design.nodes` (`design.orchestrate`, `design.consistency_eval`)
stays outside the proof under its reviewed `design-node` reachability
disposition, asserted by
`test_the_unreachable_registration_module_stays_out_of_the_proof` (passed).

## Repair-round revalidation (job `6ecf8f7921b14dc493f2fe4b5a394413`, head `56343cd19`)

All acceptance evidence re-executed at the lane head; no code changed
(implementation lives in the merge base, via PR #1935). Executed and observed:

- Two guard modules only, fresh interpreter: **137 passed**; exactly the
  eleven `creative.*` identities in both sweeps' parametrizations.
- The counterfactual, by hand at this head: a bare `maistro.graph.nodes`
  import registers **19 non-test kinds, zero `creative.*`**; importing the
  real production module `maistro_design.creative_nodes` adds exactly the
  eleven (`test_a_bare_core_import_misses_what_loading_adds` also passed
  inside the suite).
- Collection order: node-composition alone **99 passed**, container alone
  **38 passed**, reversed file order **137 passed**, broader four-file
  selection **162 passed** — `--collect-only` production-kind sets identical
  (30 kinds, 11 creative) across all three selections (diff-verified).
- `test_production_registration_universe.py`: **13 passed** (reconciliation
  clean, creative identity pin, sweeps-use-this-universe pin, fail-closed
  outside-src registration, synthetic-tree negative cases).
- Negative cases: `-k "refuses or missing or omitting or neither"` over
  node-composition → **36 passed**; container default-deny seam pin →
  **1 passed**.
- Full CI `test`-job selection (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run
  pytest packages/maistro-core/tests -v --tb=short`): **12401 passed, 888
  skipped, 1 xfailed, exit 0** in 320.30s. Same 13289 total as the earlier
  record (12399+890); two tests moved skip→pass with the develop merges.
- `uv run ruff check .` and `uv run ruff format --check .`: both clean.
  `scripts/check-suite-inventory.py`: ok, 14 suites match (no test added, so
  no `inventory-delta`). `scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: 1338 reviewed identities
  = 1338 findings, exit 0.

### Hosted CI status at this head (the one open gate)

Every required check run executed successfully on `56343cd19` (31 check runs
captured 2026-10-05T07:56Z; last producer, `integration-scope`, completed
07:40:09Z; `Container scan + SBOM + cosign` skipped as out of scope). The
required `gates-ran` commit status is **pending**, published 07:24:52Z while
evidence was still arriving. Reproducing CI's exact evaluator locally on the
complete captured evidence — `python3 scripts/check-gates-ran.py
--check-runs <captured> --require-complete --base-branch develop
--event-name pull_request --changed-files <this note>` — returns **"ok: all
28 required check(s) ran on this head", exit 0**. The publisher run for this
candidate (created 07:40:13Z, immediately after the final producer
completion) has stayed `queued` amid a repo-wide publisher-run storm with
heavy cancellation churn; later publisher runs that completed published for
other candidates (this head's status timestamp never moved). Nothing in the
branch can change this: `gates-ran.yml` deliberately judges from protected
default-branch code so a candidate cannot rewrite its own judge, and pushing
is outside this lane's authority. This is a hosted-infra condition requiring
operator action (drain/re-run the Gates Ran publisher, or the admin-bypass
merge that `branch-protection.json` grants `OrganizationAdmin`/
`RepositoryRole:admin`), not a repairable branch finding.

## Boundary note

The issue's scope sentence names `maistro_design.creative_graph` as an entry
path; the helper imports `maistro_design.creative_nodes` — the registration
module `creative_graph` itself executes (`from .creative_nodes import ...`,
`creative_graph.py:51`) when production imports it — and
`test_the_creative_kinds_enter_through_their_real_production_module` pins
that identity. This is the same real production loading path, not a
hand-maintained kind list.
