---
inventory-delta:
  tests/: +0
---

# Repair round at head 10a5ad498a76 (L1836, issue #1836) — corrupted-worktree salvage, net-zero

The incoming worktree carried **uncommitted corrupted edits** in five test
files under `packages/maistro-core/tests/`: a double-applied text substitution
renaming `approval_request_digest` to a nonexistent
`approval_request_digest_v2` / `approval_request_digest_v2_v2`, with
duplicated import lines. `ruff check` failed with 18 errors (F821 undefined
names, F401/F811 duplicate imports, I001 unsorted imports) and `ruff format
--check` flagged 4 files; this is what the driver's check-0/check-1 logs
recorded.

## Why the rename was abandoned, not completed

- No `approval_request_digest_v2` (or `canonical_approval_payload_bytes`)
  exists anywhere under `packages/*/src` — the rename had no production
  counterpart and no commit in this branch's history introduces one.
- SPEC-101826-1836 (`docs/specs/SPEC-101826-1836-approval-payload-bytes.md`)
  is `status: Proposed` and states explicitly that "No code, test, or schema
  in this repository implements this contract yet". The v2 helpers it
  selects are gated on the ADR owner's acceptance of #1836. Pointing the
  existing suites at a half-implemented v2 helper would have claimed
  implementation for an unaccepted contract — exactly what the gate forbids.

## Salvage disposition

- The corrupted diff was preserved verbatim at
  `/home/dev/Git/wt/incoming-1836-corrupted-rename.patch` (155 lines) before
  any edit.
- The five files were then restored to their committed content by targeted
  in-place edits (no `git restore`/`checkout`); the resulting net tree diff
  against head 10a5ad498a76 is **empty**. No production file, gate, ledger
  (`quality/*.json`), or spec text was touched. This commit adds this note
  only.

## Re-executed validation at the salvaged head (this round, not inherited)

- `uv run ruff check .` → rc 0 ("All checks passed!").
- `uv run ruff format --check .` → rc 0 (3561 files already formatted).
- `uv run pytest packages/maistro-core/tests/capabilities
  packages/maistro-core/tests/graph/nodes
  packages/maistro-core/tests/graph/durable_runs -q` → **2187 passed,
  77 skipped, 4 xfailed** (includes the five salvaged suites:
  test_durable_approval 23 passed, test_durable_approval_validation,
  test_capability_pause_metadata, test_capability_hitl,
  test_agent_spawn_harness).
- Deterministic acceptance command: `uv run python
  scripts/check-adr-status-language.py && git diff --check` → rc 0 / rc 0.
- **Vulture per-identity ledger, CI-exact arguments** (`uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`) → **rc 0**: 1238 reviewed == 1238 findings
  (base f8a2df966a1d, candidate 10a5ad498a76); no ledger amendment owed.
- **Named red gate `security` / Supply chain (pip-audit), CI-exact battery
  re-run**: `uv sync --locked --all-extras`, `uv pip freeze
  --exclude-editable` (219 distributions), `uv run pip-audit --strict
  --format=json -r /tmp/deps.txt` (report complete, audit exit 1),
  `scripts/pip_audit_gate.py` → **rc 0**: only the triaged
  `ecdsa==0.19.2 PYSEC-2026-1325` (reported twice, both allowed);
  direct-dependency usage OK (11 packages, 66 runtime deps, 4 reviewed
  dispositions). Lock versions re-confirmed: dnspython 2.9.2,
  graphql-core 3.3.2, joserfc 1.8.0, opentelemetry-api 1.45.2.
- `scripts/check-image-pins.py`, `check-image-inventory.py`,
  `check-workflow-inventory.py`, `check-security-inventory.py` → all rc 0.
- `scripts/check-suite-inventory.py` → rc 0 (21 suites match the recorded
  inventory; 0 redundant bytes) — consistent with the net-zero test delta.
- **SPEC-101826-1836 golden vectors V-1 … V-18 independently re-executed**
  (recipe implemented out-of-tree per the document text; script kept at
  `/tmp/spec_vectors_1836_round.py`, outside the tree): **43/43 checks
  pass, 0 failures**, stable across two runs — V-1 bytes byte-exact and
  digest `v2:8db816aa…ca82c`; V-2 reorder invariance; all eleven V-3…V-13
  mutation digests match the table, pairwise distinct, all distinct from
  V-1; V-14 bool/int and int/float byte distinctions; V-15 all eight
  rejection rows raise the path-naming `TypeError` (nested non-str key at
  `effect` included) and the v1 hazard columns reproduce (datetime str()
  rendering, set/`object()` silently digested via `default=str` — set
  element order unsorted across processes as documented, `NaN` invalid
  JSON); V-16 v1 key-coercion collision and mixed-key mid-serialization
  `TypeError`; V-17 `ensure_ascii` pin bytes `b'{"name":"caf\\u00e9"}'` with
  v1 digest `9db11f5f…` and the v2 envelope; V-18 legacy row
  `1748e5b5…` byte-exact through the production helper, the inline v1
  recipe, and end-to-end the production `DurableApproval` fallback.
  Resolution order re-verified: explicit field > carried
  `params["request_digest"]` stamp > v1 recompute fallback.

## Decision-gate posture (unchanged, by design)

SPEC-101826-1836 stays `status: Proposed`, `contracts: []`; the ADR owner's
explicit acceptance remains the open gate for #1836, and nothing in this
round claims implementation or acceptance. No tests were added or removed;
the suite inventory is unchanged.

## Residual risks (documented, not new)

- The Container scan + SBOM + cosign job needs CI secrets and rebuilt
  images; not locally reproducible here. Its inputs (Dockerfiles,
  `uv.lock`, `quality/image-pins.json`) are byte-identical to the state the
  prior round re-proved green (trivy/grype rc 0 on engine & hive-conductor,
  lock reconciliation rc 0) at 67833896ec4a, and unchanged since.
- maistro-engine-research / maistro-rsi-runner images were not rebuilt
  locally in any round of this lane; their pins verify upstream.
