# #2418 verifier revalidation at develop sync `8f2fc00e5c9d`

Third verifier round on the branch, now at the merge of `origin/develop`
`4d148dd3cc3a` (dependency/image-bump train #2413/#2430/#2431/#2433). The
delta since the previous revalidation at `280e286ff4` touches no
admitted-authority surface: Dockerfiles, image pins, workflow
starvation-budget wiring, and develop's own `tests/test_root_image_interpreter_lines.py`
(with its `2430-root-image-interpreter-lines.md` delta note). No count moved,
so no `inventory-delta` is recorded.

Independently executed at `8f2fc00e5c9d6807de763f80f0550f09c220cdbb`
(base `4d148dd3cc3a`):

- Driver deterministic checks (job `62796115927943deb62838404358eec7`,
  check-0..6): `uv sync --locked --extra dev`; `ruff check .`; `ruff format
  --check .` (3604 files); focused suites 189 core + 53 hive; per-suite
  inventory gates ok (hive 4297, core 18752).
- Focused suites re-run: admission + delegation + factory 101 passed;
  identity/tool_choice/quota/egress 88 passed; hive adapter +
  effective-gateway-key + materialized authority 53 passed.
- `test_configured_hive_agents_use_admitted_execution_and_usage` by name:
  `[boot]` and `[materialized]` both pass; the test asserts the full
  Run/NodeRun/Attempt(+lease) → Invocation (`agent-llm:{name}:0:1`,
  actor/Workspace/project/Binding) → usage-log join on a real SQLite store,
  plus post-revocation zero-dispatch refusal.
- `test_materialized_model_authority.py` collects exactly 20 cases, all pass;
  the `admitted_model.py` coverage closers pass by name (replay preserves
  `_stream_chunks` tool_calls + finish_reason, text-only fallback,
  `required_workspace_id` mismatch refuses before egress, early `aclose`
  cancels the in-flight pump).
- Ratchets with CI-exact arguments: vulture 1229 → 1229 (`packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`, `RATCHET_BASE_REV=origin/develop`);
  wiring-reads 11 → 11; suite inventory full run ok (21 suites, 35849 unique
  node IDs); cross-package imports ok (3591 files / 11 packages).
- Lint/type: `ruff check .` and `ruff format --check .` clean; `uv run mypy`
  over CI's exact ten-package list: 1126 files, no issues.
- Cheap CI gates: compliance registry, monorepo layout, merge-marker scan —
  all ok. Branch diff vs base touches no `quality/` ledger or
  `baseline.json`; `quality/` vs `origin/develop` shows only develop's own
  `image-inventory.json` image-pin rows (2).
- `DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF` re-export imports cross-package as
  `litellm-gateway`.
- Closure-keyword scan over branch-unique commit messages: no
  fixes/closes/resolves markers; PR body Progresses/Refs #1084 without
  closing it.

Still unverifiable locally (hosted, left unchecked in the PR body): full CI
on this PR — all 66 check runs were still `queued` at capture; the
Docker/e2e/MinIO/Postgres legs are not runnable in this review environment.
