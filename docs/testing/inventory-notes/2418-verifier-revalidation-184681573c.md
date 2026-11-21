# #2418 verifier revalidation at develop sync `184681573c`

Fourth verifier round on the branch, at the merge of `origin/develop`
`567d584260` (M1 closeout #346 research/rsi-runner image boot smokes, PR
#2400) on top of the previous revalidation at `8f2fc00e5c9d`. The delta
since `8f2fc00e5c9d` touches no admitted-authority surface: Dockerfiles,
CI workflow, `pyproject.toml`/`uv.lock`, image boot-smoke scripts and their
root-suite tests, `quality/image-inventory.json` image-pin rows
(develop's own #2400), and the prior round's note. No maistro-core or
hive-conductor test count moved, so no `inventory-delta` is recorded
(per-suite gates below match the recorded baseline exactly).

Independently executed first-hand at `184681573c9d1074372dc97c991d3e3486efbd58`
(base `567d584260cec7894c246a9e9b4e69e6c7b5c434`):

- Driver deterministic checks for this job ran green on this exact head
  (check-0..6): `uv sync --locked --extra dev`; `ruff check .`; `ruff format
  --check .` (3605 files); focused core suites 189 passed; hive adapter +
  effective-gateway-key + materialized authority 53 passed; per-suite
  inventory ok (hive 4297, core 18752, zero duplicated evidence).
- Re-run by this round: `test_governed_llm_admission.py` 24 passed
  (including the four `admitted_model.py` coverage closers by name: replay
  preserves recorded tool_calls + finish_reason, text-only fallback when no
  `_stream_chunks`, `required_workspace_id` mismatch refuses before egress,
  early `aclose` cancels the in-flight pump); `test_governed_delegation.py`
  5 passed (model-before-delegate distinct effect keys + replay);
  `test_configured_hive_agents_use_admitted_execution_and_usage` +
  `test_materialized_model_authority.py` 22 passed.
- Ratchets: `scripts/check-wiring-reads.py` ok (11 unread, ledger matches);
  `scripts/check-cross-package-imports.py` ok (3592 files / 11 packages);
  `scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  re-run ok first-hand (hive suite green in driver log check-5).
- `ruff check .` clean; `DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF` imports
  cross-package from `model_chat` as `litellm-gateway`.
- Closure keywords: branch-unique commit messages scanned — no
  fixes/closes/resolves markers; PR body Progresses/Refs #1084 without
  closing it ("Does **not** close the parent").

Still unverifiable locally: full CI on this PR — all 66 check runs at the
last captured head were still `queued`/pending at capture; the
Docker/e2e/MinIO/Postgres legs are not runnable in this review environment.
