# Repair notes — #976 round: develop sync + gate re-bank verification

Round input: worktree preserved an in-progress `git merge` of `e12e11288`
(M2-A, #2283) with one unresolved conflict, and `origin/develop` had advanced
to `09d56b6a0` (EPIC M5-B, #2263) — three commits past the merge target.

## What was done

1. **Conflict resolution** (`packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py`):
   the branch's #976 extension-attribution work and develop's #2318 gateway
   resilience work restructured the same tail of `execute_model_chat`. Union
   resolution:
   - both imports (`logging` from #976, `time` from #2318) and both
     module-global blocks (`logger`/`_adapter_identity_suffix`/`_adapter_log_fields`
     and `_GATEWAY_RATE_LIMITS`/`_CONTEXT_PROBE`/`_GATEWAY_RATE_LIMIT_SCOPE`);
   - develop's refactor kept: the POST moved to `_post_chat_completion`, adapter
     response mapping moved to `_adapter_response_body` (429 recording, error
     taxonomy, non-object body guard);
   - #976's one-per-call extension-attribution log line re-homed into
     `execute_model_chat`'s adapter branch, immediately before
     `_adapter_response_body` — same semantics as before (fields rendered into
     the message via `log_fields_suffix` and attached via `extra`, logged before
     any error raise).
2. **Second merge**: `origin/develop` (`09d56b6a0`) merged cleanly; no
   conflicts. `llm_gateway.py` untouched by the three new commits.
3. **Format**: one blank-line fix from `ruff format` on the merged file.

## Gate evidence at final head (292b2554b + note commit)

- `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate b1c89cdbc` → EXIT 0
  (design coverage measured 39.641, exactly the #166-authorized floor; ratchet
  OK; acceptance mandate: 6 criteria claimed since base, 0 unproven; chain
  mandate OK). The previously stale banked claim (44.2377) was already
  re-banked to the measured 39.641 in 267174e7d; this round proves it holds
  after both develop merges.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → EXIT 0 (1263 reviewed identities).
- `uv run ruff check .` → pass; `uv run ruff format --check .` → pass.
- `uv run mypy --strict packages/maistro-core/src` → Success (832 files; needs
  `uv sync --locked --all-extras`, matching the CI job's setup).
- `uv run python scripts/check-suite-inventory.py` → ok, 21 suites match.
- AC evidence: 82 `ac`-marked tests pass across extensions/provider-adapter/
  gateway scopes, covering SPEC-102426-976a AC-1..AC-6 (24/8/6/6/4/6 markers);
  full extensions + adapters + binding scope: 1460 passed, 5 skipped.
- Gateway union tests: 221 passed (branches, resilience-connect, provider
  adapters, model-chat egress, governed execution identity, admitted calls).

No tests were added or removed in this round (merge-only + conflict union), so
no suite-inventory delta note is required; `check-suite-inventory.py` confirms
the recorded inventory matches.
