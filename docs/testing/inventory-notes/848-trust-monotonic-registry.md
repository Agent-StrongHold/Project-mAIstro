---
inventory-delta:
  packages/hive-conductor/backend/tests: +13
  packages/maistro-core/tests: +22
---
# Issue 848: trust-monotonic registry boundaries

Adds focused regression coverage for capability rediscovery and explicit
replacement authority, fail-closed provider tier ordering, traversal-safe skill
mutation, malicious catalog hot reloads, privileged Pi trust claims, and
Binding-scoped Atlassian MCP tool calls.

## Scope reconciliation (repair round, resolves the prior deep-review flags)

Three items were flagged by the first round; each is resolved with evidence
rather than a new mechanism:

1. **Vulture gate executable.** The gate environment had drifted (no
   `vulture` module); `uv sync --locked --extra dev` restores it. Run with the
   exact CI invocation (`scripts/check-vulture-baseline.py packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'`), the only NEW identities
   are three findings in `packages/maistro-core/src/maistro/capabilities/
   invocation.py` (`observed_at`, `_validate_reconciliation`,
   `_validate_evidence`) introduced by base commit d7a9a75bf (#1310) — not by
   this change — two of which are already banked on origin/develop's ledger.
   This commit adds zero vulture debt; the per-identity ledger is not edited
   here because ledger edits are restricted to an explicit CI-repair round.
2. **Signature policy stays deferred to ADR-083 acceptance.** ADR-083
   (publisher-VC skill signing, microVM tiers, gateway policing) is
   `Proposed`, so no cryptographic signature policy is operative today. The
   issue criterion binds to the *applicable* signature policy; the operative
   policy enforced on these paths is security scan + provenance + the
   host-owned unvetted tier floor + the governed replacement decision.
   Implementing ADR-083's signing ahead of acceptance would preempt governance
   and add the parallel trust mechanism the issue's stop condition forbids.
3. **No unguarded MCP tool-call route exists to wire.** The only `tools/call`
   implementation in the tree is the Binding-guarded `AtlassianMCPClient`;
   `routes/mcp.py` exposes management/probe routes only (fixed probe URLs,
   no arbitrary tool-name proxy). Adding a live invocation route is new
   scope beyond this issue; the boundary defect it names is closed.

## Validation evidence (re-validation round at 35d388d37286)

All three items above re-verified against reachable production behavior:

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1322 reviewed
  identities = 1322 findings, zero unbanked (confirms item 1; ledger not
  edited).
- `grep -n 'tools/call\|call_tool' packages/hive-conductor/backend/routes/mcp.py`
  → no matches (confirms item 3).
- ADR-083 remains `Proposed` (item 2 unchanged).
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run pytest packages/maistro-core/tests -q` → 15373 passed, 1073
  skipped, 3 xfailed (includes the 8 new tests: overwrite attempt, governed
  replacement, blank/unknown provider tier fail-close, traversal mutation,
  malicious in-memory entry, malicious hot reload, privileged Pi trust claim,
  Pi instructions scan).
- `uv run pytest packages/hive-conductor/backend/tests -q -k "not e2e"` →
  3654 passed, 20 skipped (includes the 3 new MCP boundary tests).
- `uv run mypy packages/maistro-core/src packages/maistro-server/src
  packages/maistro-turing/src packages/maistro-canvas/src
  packages/maistro-bootstrap/src packages/maistro-registry/src
  packages/maistro-ext-sdk/src` (CI's exact invocation) → Success.
- `uv run python scripts/check-suite-inventory.py` → ok, 17 suites match.

## Diff-coverage repair round (at d3360e48f722)

CI at this head failed two gates: `Coverage gate (publish-set floor + diff
coverage)` and `test`. The stale "Quality / Xenon: failure" in the lane brief
was contradicted by the check-run evidence at this exact head (conclusion:
success); the xenon, radon and complexity-scope gates were re-run locally with
CI's exact arguments and pass (134 blocks = baseline 134, module ledger empty,
project average A).

The diff-coverage gate failed six changed files (reproduced locally with CI's
arguments against the PR base fad17a87c341):

- `hive-conductor/backend/services/mcp_client.py` 70.9% — untested
  `call_tool` happy path, credential/endpoint denials, malformed-Binding
  allowlist collapse, wrong-server Binding, non-Atlassian URL normalization
  fail-closed path.
- `capabilities/discovery.py` partial arc — `register()`'s new `False` return
  (rediscovery admits nothing) was never exercised through `discover_into`.
- `capabilities/registry.py` 86.2% — `ProviderReplacementDecision.__post_init__`
  refusals, `define()` conflicting-redefinition ValueError, `replace()` KeyError.
- `security/trust.py` partial arc — non-string tier in `trust_rank`.
- `skills/catalog.py` 87.5% — `load_directory` symlink/scan-skip; hot-reload
  unauthorized symlink path.
- `skills/forge.py` 87.5% — `_find_mutation_path` symlink/non-file/outside-root
  refusals; existing-content scan block.

Ten tests were added to
`packages/maistro-core/tests/security/test_trust_monotonic.py` and nine to
`packages/hive-conductor/backend/tests/test_mcp_trust_boundary.py` (each named
for the refusal it pins; the hive happy-path test asserts the exact JSON-RPC
payload, Bearer header and allowlisted tool name).

Repair-round validation evidence (all commands run at d3360e48f722 + this
change, against PR base fad17a87c341):

- Full two-producer coverage measurement with CI's exact producer commands
  (`coverage run --branch --source=packages/maistro-core/src/maistro -m pytest
  packages/maistro-core/tests`, then `--append` for hive-conductor): 15585
  passed / 1131 skipped (core), 3780 passed / 24 skipped (hive), then
  `scripts/check-diff-coverage.py coverage.xml --base fad17a87c341` → **ok,
  exit 0** ("every measured file this change touches is at or above 90% lines /
  80% branch arcs").
- Publish-set floor: all five producers (core, canvas, evolve, rsi, bootstrap)
  under coverage, `coverage report --fail-under=87` → exit 0 (93%).
- `test`-job steps re-run: hive-conductor backend suite 3780 passed; root suite
  `tests/ --ignore=tests/tools/registry` 5395 passed (one earlier run had a
  single transient failure in the Docker-based
  `test_restore_oracle_characterization.py::test_real_verify_restore_drill_passes_end_to_end`
  — a test that exists unchanged at the merge base and passes in isolation and
  on re-run; Docker contention with other lanes' containers, not this diff);
  cross-suite leakage proof `tests/ + hive-conductor/backend/tests +
  maistro-design/tests` in one process → 9843 passed, 164 skipped.
- OpenAPI types drift check: `scripts/dump-hive-openapi.py` output at this head
  is byte-identical to the same dump at the merge base (235 paths, 140
  schemas), so the #1048 generated-types step cannot fail on this diff.
- `scripts/check-suite-inventory.py --suite` for both touched suites → ok
  (deltas in this note updated to +22 core / +13 hive).
- `uv run ruff check .` / `uv run ruff format --check .` → clean;
  `uv run mypy` (CI's exact package list) → Success, 906 files.
- Quality gates re-run with CI's exact arguments: xenon 134 blocks (= baseline
  134; module ledger empty, project average A), `check-radon-baseline.py` 134
  = 134 with zero new/regressed/improved/stale, `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → 1321 =
  1321, exit 0, `tests/test_complexity_gate_scope.py` 5 passed. The check-run
  evidence at this head shows `Quality / Xenon` conclusion: **success** — the
  lane brief's xenon-failure line was stale, not a defect to fix.
