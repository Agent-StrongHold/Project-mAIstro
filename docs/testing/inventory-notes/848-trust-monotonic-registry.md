---
inventory-delta:
  packages/maistro-core/tests: +8
  packages/hive-conductor/backend/tests: +3
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
