# Issue #57 round: develop-sync salvage + fresh validation (head b414e6f75)

Round scope: resolve the BLOCKED prior round's concrete cause (mid-flight `git merge 2014ab888`
left conflicted by a provider rate-limit death), sync origin/develop, then re-validate every
branch-verifiable acceptance criterion on the new head. No production or test edits were needed
beyond the conflict resolution.

## Salvage performed (the assigned blocker)

- Prior job a24f0c6560 died on provider 429 mid-merge, leaving `MERGE_HEAD=2014ab888`
  (origin/develop ancestor) with one conflict:
  `packages/maistro-bootstrap/src/maistro_bootstrap/builders/agent_loop.py`.
- Resolution (commit fbc721ed4): kept the branch's hardened `run_command` dispatch
  (strict argv validation via `_run_command_argv` + `sandbox.run_argv`, shell=False; the
  model-authored `requires_human_approval` gate stays retired) and folded develop's comment
  reword ("Tracked follow-up (#329 / ADR-090726-9a4e)") into the surviving comment so the
  follow-up reference is not lost with the deleted block. Develop's only change to that file
  was that comment reword on code the branch deleted — no behavioral develop intent dropped.
- Follow-up merge of origin/develop tip bcd7acb7f (one commit: #2318 promotion-surface grant)
  → head b414e6f75, clean ('ort' strategy, 1 file).
- Ledger integrity after merges (AGENTS.md row-loss rule): `git diff --numstat fbc721ed4..HEAD
  -- quality/` = only `ratchet-authorizations.json +35` (develop's grant); no rows lost from
  either parent; branch's intentional ledger deltas unchanged vs bcd7acb7f.

## Fresh validation on head b414e6f75 (all executed this round)

- `uv run ruff check .` → All checks passed.
- `uv run ruff format --check .` → 3507 files already formatted.
- `uv run pytest packages/maistro-core/tests -q` → **16734 passed, 1213 skipped, 7 xfailed**
  (includes tools/capabilities/agents/security suites: governed contracts 581-line suite,
  schema boundary, seam fail-closed, sentinel audit, effect-context policy).
- `uv run pytest packages/maistro-bootstrap/tests -q` → 257 passed, 7 skipped
  (includes test_agent_loop_command_contract.py: schema requires argv/no cmd string;
  raw `cmd` rejected; metacharacter tokens rejected; dispatch reaches `run_argv` shell=False,
  sandbox.py:241–261).
- `uv run pytest tests/test_check_direct_effects.py tests/test_check_model_egress.py -q` → 74 passed.
- `uv run pytest packages/hive-conductor/backend/tests/test_governed_tools.py
  test_legacy_dag_node.py test_maistro_core_adapter.py test_agent_model_tools.py -q` → all passed
  (legacy no-identity tool call refused; governed tools admitted through canonical Invocation).
- `uv run mypy packages/maistro-core/src packages/maistro-bootstrap/src` → Success (850 files).
- CI-exact gates (quality.yml:1526 args; reachability quality.yml:1569):
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  → exit 0 (base bcd7acb7f → candidate b414e6f75, 1297 reviewed / 1293 findings);
  `check-reachability.py` → exit 0; `check-suite-inventory.py` → exit 0 (21 suites match);
  `check-convergence-matrix.py` → exit 0 (52 subsystems, 147 unreachable attributed).

## Acceptance re-verification (independent, on code)

- Seam dependency (criterion 1): `GovernedToolExecutor._invoke_admitted` calls
  `effects.invocations.invoke` (tools/contracts.py:341–353); legacy DAG tool nodes use the same
  service (legacy_dag_node.py:441). No second executor introduced.
- Allowlist/schemas fail closed (3,4): agents/base.py:905–913 denies undeclared names with
  scoped audit evidence; `_validate_tool_request` refuses missing schemas and re-validates
  Sentinel-repaired arguments via the shared `validate_tool_arguments`;
  `UnknownToolSchema`/`ToolArgumentError` raised before any backend (contracts.py `_admit_call`).
- Reversibility (6): `ToolContractRegistry` owns `ReversibilityRegistry` (contracts.py:101);
  unknown names get no caller-selected tier; `hive_tool_reversibility` resolves the same host
  registry. SECURITY.md layer-4 row and CONVERGENCE-MATRIX.md match this behavior (prior drift
  finding stays fixed; `check-convergence-matrix` exit 0).
- Expected-effect evidence + mismatch (5,6,7,9): evidence binds capability/provider/materialized
  arguments/`arguments_digest` (validated)/pre-state digest/policy_version (expected_effect.py),
  bound to Invocation identity before durable admission (invocation.py:899–904); first host
  observation is authoritative and cannot be rewritten (invocation.py:953–973); mismatch emits a
  durable `capability.invocation.expected_effect_mismatch` EventEnvelope with stable id and
  raises `PredictionMismatch`; high-impact contract without a prediction contract fails closed
  (contracts.py:73–84). Tests pin these incl. sqlite-reopen recovery
  (test_governed_contracts.py:208, 258).
- TOOL_EFFECT inventory (criterion 10): base (161dedc06 and bcd7acb7f) carries 6 TOOL_EFFECT rows
  (the issue's "seven" predates develop-side retirement of one site). Head dispositions: 0 rows
  with MIGRATE pending; chat_completion `_tool_web_search`/`_tool_browse_url` route through
  `services.governed_tools` (chat_completion.py:1361–1379); legacy_dag_node + tool_executor rows
  reclassified INTENTIONAL_LIBRARY/INFRASTRUCTURE with recorded rationale (provider backends
  beneath canonical Invocations). Direct-effects gate exit 0 confirms census/disposition parity.
- Bypass rejection (criterion 11): `test_a_tool_node_without_canonical_identity_is_refused`
  (test_legacy_dag_node.py) pins the retired direct-effect branch; `_run_tool_node` raises
  without NodeContext identity (legacy_dag_node.py:462–464).

## Residuals (external, not branch-repairable)

- Criterion 12: #847 state=open in dispatch-context (captured 2026-10-25). Branch-side substance
  is present and tested; the GitHub closure event is maintainer-owned sequencing outside this
  lane's prohibitions.
- CI on head b414e6f75: cannot exist without a push (prohibited); captured check-runs for older
  heads were pending/stale. Remote CI stays UNVERIFIED by lane design.
- 7-v-6 TOOL_EFFECT count is historical provenance (PR #506 inventory vs develop-tip census),
  not missing work; every row present at base is dispositioned.

Verdict: MERGE-READY as writer handoff only — never integration approval. Merging remains gated
on maintainer sequencing of #847 closure and remote CI on the pushed head. No push, PR, issue,
or ledger action performed. No tests added → no suite-inventory delta required.
