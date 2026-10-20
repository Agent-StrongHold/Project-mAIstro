---
inventory-delta:
  packages/hive-conductor/backend/tests: +18
  packages/maistro-server/tests: +2
---

# #1824 installed model configuration reaches the runtime's Binding and gateway credential

Seventeen node IDs in
`packages/hive-conductor/backend/tests/test_effective_gateway_key.py` (new) and
seven in `packages/maistro-server/tests/test_worker_yaml_config_startup.py`
(new) — eighteen since the CI-repair round below — plus two existing server
node IDs rewritten in place
(`test_startup.py::TestRouterApiKeyValidation`, same count): they pin the
environment-only ROUTER_API_KEY refusal, which now requires pinning the YAML
singleton to None, because the worker — correctly — loads the documented
config into it during every lifespan boot.

**Hive +17** pin the one effective-key contract
(`services.secrets.effective_llm_gateway_key`): the precedence matrix
(only-`MAISTRO_LLM_API_KEY`, only-`LITELLM_API_KEY`, both supported proxy
aliases, alias ordering, vault-first on both names, conflict resolution,
empty-string-falls-through, none-is-`None`); `sk-noop` removal (the legacy
roster client refuses complete/stream *before any HTTP* when unconfigured,
with a sanitized message carrying no key material); the embedded runtime
building its roster client and governed endpoint from the effective key (and
holding no key at all when nothing is configured); and the governed egress
endpoint resolving the same credential through the same contract as the roster
client.

**Hive +1 (CI-repair round, diff-coverage)**:
`test_configured_client_dispatches_with_the_effective_credential` covers the
second arc of `_HttpOpenAILLMClient._require_credential`'s credential branch
(`adapters/maistro_core.py`) — the one the merge-queue coverage gate measured
at 50% of 2 branch arcs because every prior test drove the empty-key refusal.
The new test pins the other half of the fail-closed contract: a client built
with the effective key is *not* refused — it dispatches to the gateway it
names, carrying that credential as the bearer token. `stream` delegates to
`complete`, so one passage covers the guard for both entry points.

**Server +2** prove the installed configuration reaches the runtime's scoped
Binding: the declared `model.chat` Binding resolves through the real Container
the worker itself built (existing bootstrap + scope routing; no transport; no
test singleton injection), in-process and in a fresh shipped-entrypoint
process. The loader semantics those two proofs ride on — the worker-side YAML
hook, the fail-closed missing-file contract, and the sanitized refusal of a
malformed/type-invalid file — are owned by develop's
`test_model_config_process_startup.py` (see the reconciliation below), not
duplicated here.

## Develop-merge reconciliation (no node-ID delta)

The branch was synced to develop `2f56be40a` (merge `b3b386da5`). The merge
kept this note's +17/+7 exactly: no node IDs were added, removed or renamed by
the reconciliation, so the front-matter deltas above are unchanged. Three
develop-side test files predated the one-contract contract and were repaired
for stub fidelity / cache hygiene, not for behavior:

- `test_effective_gateway_key.py` — develop's `AdmittedModelCalls` wiring in
  `_construct_runtime` reads `container.run_store`/`provider_adapter_catalog`
  (real Container attributes, always present); the two runtime-construction
  stubs now mirror them. `test_endpoint_resolves_the_effective_key` gained the
  same `get_settings.cache_clear()` hygiene its sibling already documented:
  develop's e2e module seeds the lru-cached Settings with its own gateway key,
  which otherwise outranks the alias this test states.
- `test_provider_pin_registration.py` — the `get_settings` stub now carries
  `maistro_llm_api_key`, mirroring what pydantic-settings produces from the
  env the same fixture sets (the effective-key contract reads that field).
- `test_graph_runner.py` — the `_S` settings stub carries
  `maistro_llm_api_key` (unconfigured), mirroring the real Settings field the
  governed `_endpoint` reads on the canonical DAG path.

The `tests/` suite drift this merge reports (`expected 5260, collected 5261`)
is inherited, not introduced by #1824: no #1824 surface touches `tests/`, and
this note's own deltas target `packages/hive-conductor/backend/tests` and
`packages/maistro-server/tests` only. The drift has two carried components,
now recorded: the #1881 oracle files (`1881-restore-oracle-snapshot-consistency.md`,
+19, merged from `2f56be40a`) and PR #1993's sentinel registry-parity node
(`auto-1824-carried-1993-sentinel-registry-parity.md`, +1) whose delta was
lost when develop's tip (`c2a22e55d`) rewrote the history the branch merged —
develop tip collects 5241 for `tests/`, this branch 5261. (The original text
of this paragraph claimed `tests/` was byte-identical to develop; that was
true against `2f56be40a` and false after develop's rewrite — corrected here.)

## Isolation repair: the `governed_env` settings window closes its cache

Correction to the reconciliation claim above: one of those develop-side
repairs *did* leave a behavioral cross-file effect — an order-dependent test
isolation regression, not a production behavior change. The
`governed_env` fixture in `test_legacy_dag_governed_quota.py` (branch-added
suite) set `MAISTRO_LLM_BASE_URL`/`MAISTRO_LLM_API_KEY` without closing the
`config.get_settings()` lru-cache window. When a preceding file left the
cache empty (e.g. `test_runtime_wires_container_authorities`, whose
`finally: cache_clear()` is itself the documented seam), the governed DAG run
inside the window rebuilt the process-wide Settings singleton from the
transient env — and the singleton kept `litellm_api_base='http://gateway.test'`
after monkeypatch reverted the variables. The next readers then saw a
"configured" gateway: `dag_node_runtime` composed a governed runtime for the
canonical DAG spine tests in `test_graph_runner.py`, whose
`canonical_graph_spine` context deliberately carries no policy evaluator, so
the node's model call crossed the governed egress and was refused with
"capability invocation policy unavailable" — two spine tests failed
(`test_execute_dag_builds_config_and_returns_shape`,
`test_execute_dag_entry_node_fallback_to_first_node`) whenever
`test_governed_model_consumers.py` + `test_legacy_dag_governed_quota.py` ran
before them, while each file alone passed and the full-suite order masked the
pair.

Repair (test-only, in `test_legacy_dag_governed_quota.py`): `governed_env`
now brackets the transient env window with `config.get_settings.cache_clear()`
on both sides — the same seam `test_runtime_wires_container_authorities` and
`test_effective_gateway_key.py` already document. No node IDs added, removed
or renamed; the front-matter deltas are unchanged. Verified: the exact
previously-failing quartet order
(`test_governed_model_consumers.py test_legacy_dag_governed_quota.py
test_provider_pin_registration.py test_graph_runner.py`) passes 51/51, and the
reverse orders (quota-first, graph-runner-first) pass unchanged.

Residual (pre-existing on develop, out of this branch's surfaces):
`test_dag_model_tools.py` sets the same gateway env in a yield fixture without
patching or clearing the settings cache — the identical latent hazard, dormant
today because the cache is populated when it runs.

## Exact-debt-ledger repair (this CI-repair round)

Two ledgers recorded the pre-#1824 deadness of code this issue makes live;
both were pruned per each file's own protocol, not weakened:

- `quality/vulture-baseline.json`: removed the one stale row
  `maistro.config.loader::unused function 'load_yaml_config'` (618 → 617
  findings). `maistro_server/main.py`'s worker startup now calls the function
  (the #1824 boundary-3 change), so vulture no longer reports it unused.
- `quality/reachability-baseline.json` + `reachability-dispositions.json`:
  removed `maistro.config.loader` from the unreachable set (169 → 168) and its
  `config-loader` CONNECT disposition group. The worker startup import gives
  the module a production entry point; the baseline's own `_comment` requires
  pruning entries that become reachable, and the dispositions checker rejects
  a group naming a module outside the baseline. Consequence carried through:
  the `Shared contracts and config` row of
  `docs/architecture/CONVERGENCE-MATRIX.md` moves `few` → `none` (0 of 85
  modules unreachable), per the checker's census.

Verified: `check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` → OK (169 → 168 shrink is the allowed direction);
`check-reachability.py`, `check-reachability-provenance.py`,
`check-reachability-dispositions.py`, `check-reachability-dispositions-provenance.py`,
`check-ac-state.py`, `check-promotion-surface.py`, `check-convergence-matrix.py`,
`check-test-duplicates.py`, `check-suite-inventory.py` all exit 0; the four
reachability-baseline identity tests pass (they failed at the round's starting
head `0485b254d` and pass on develop tip — the drift was the branch's own
 revived module).

## Develop-sync conflict resolution (merge of `e708451b3887` / `fad17a87`)

The develop sync left one unresolved conflict in
`packages/maistro-server/src/maistro_server/main.py`: the branch (#1824) had
added `_load_documented_yaml_config` and develop (#1880) had added
`_load_operator_yaml`, both as the first YAML consumer in `_runtime_lifespan`.
The two are the same behavior with contradictory failure semantics, so the
merge keeps one.

Resolution: develop's `_load_operator_yaml` wins. Its docstring states the
reason the branch's version is not kept — the branch re-raised
`RuntimeError(...) from exc`, and the chained cause is a parser/pydantic
error whose message embeds raw file content (`_load_raw_yaml`'s
"Invalid YAML in ...", a type-invalid value echoing the operator's input).
That publishes secret material to stderr in the traceback, which violates the
issue's "sanitized diagnostics" requirement; develop's `from None` cuts the
chain and logs only the path and the exception type. The branch's duplicate
function and its local `load_yaml_config` import are removed; the module-level
import develop's function uses stays.

Test consequence: the branch's
`test_worker_yaml_config_startup.py` had seven node IDs. Five pinned the
loader semantics (missing-file, malformed refusal, type-invalid refusal,
sanitized-message, fresh malformed refusal) and asserted the branch's message
and kept `__cause__`; those are develop's coverage and are dropped rather than
re-pointed, so the loader keeps one test home. The two that prove the issue's
actual title — the YAML-declared Binding resolving through the real Container,
in-process and in a fresh worker process — survive unchanged (they never
referenced the loader function or its message). Net server delta: **+7 → +2**,
recorded in the front matter above; `1880-worker-yaml-load.md` keeps its +6
for develop's own file, so the suite's expected collected count is unchanged
in total. No quality-ledger rows move: `maistro.config.loader` stays live
through the surviving module-level import.
