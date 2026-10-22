---
inventory-delta:
  packages/maistro-core/tests: +33
---

# Codex App Server as a governed HarnessRunner provider (issue #822 / auto-822)

Thirty-three node IDs in `test_codex_app_server_harness.py` (new) cover the
`codex_app_server` provider end to end — the provider seam itself, the governed
`HarnessSessionManager` effect path, and the canonical graph-node executor —
against the issue's acceptance list (successful turn, streaming, tool request,
denied effect, provider crash, cancellation, session cleanup).

**+6** `TestProviderSurface`: identity/preference (`PREFERRED_CODEX_PROVIDER`),
healthcheck, foreign-thread correlation, envelope + `provider_metadata`
(maistro session id authoritative, codex thread id as metadata), model flag +
system-message exclusion, unknown-session `KeyError`.

**+11** `TestTruthfulProjection`: failed session create fails closed with no
half-registered session (sandbox released); failed turn and unparseable /
non-object results raise `CodexTurnError` instead of fabricating success;
stop releases thread mapping + sandbox; stop is idempotent and survives a
failing foreign stop command; post-stop turns raise `KeyError` (typed
cancellation projection). The repair round adds five closed-leg guards:
non-object create output, object create output with no `session_id`,
unparseable (non-JSON) create output, and a create `exec` that raises — each
must still release the sandbox and surface the typed error, never keep a
half-registered session.

**+4** `TestStreamProjection`: NDJSON App Server events project to canonical
observation (`codex.<kind>`, effect requests as gateable `tool_call`), field
correlation on every event; unparseable lines surface as `error` events with a
`failed` terminal status; non-zero stream exit projects `failed`; blank
NDJSON lines are skipped and a non-object line is surfaced as `error` — never a
silent success.

**+2** `TestMicroVMWiring`: factory boots the microVM at the pointed-at
workspace with exactly the scoped credential env (no broad service tokens
cross the VM boundary); runner end-to-end turn inside the VM.

**+8** `TestGovernedIntegration`: full lifecycle through governed Invocation;
denied effect dropped by the ActionGate before surfacing; Warden blocks
inbound before Codex sees it; provider crash raises through Invocation (failed
attempt, no fabricated envelope); unhealthy provider degrades to typed
`Unavailable` (SAFE_NOOP); cancellation projects as unknown-session
`Unavailable`; recorded Invocations carry maistro's canonical
run/NodeRun/Attempt identity (foreign thread id stays metadata); harness
output cannot mint new sessions/runs (Codex is not a peer scheduler).

**+2** `TestGraphNodeIntegration`: a canonical graph node runs a codex turn via
`HarnessNodeExecutor` → `HarnessOutput` with the session stopped afterwards;
turn failure propagates the typed error and still releases the session.

Local run: `uv run pytest packages/maistro-core/tests/capabilities/test_codex_app_server_harness.py -q`
→ 33 passed; `uv run ruff check .` and `uv run ruff format --check .` clean;
`uv run mypy packages/maistro-core/src` clean. The provider's public
`foreign_session_id` accessor is read by `send`/`stream` (not only by tests),
so the vulture per-identity ratchet (`packages/*/src --min-confidence 60
--exclude '*/third_party/*'`) reports no new debt for this change.

## Repair round (auto-822)

Two merge-queue blockers on top of the original 27-node suite, both reproduced
and fixed locally rather than re-reported:

- **Diff coverage (publish-set floor + diff coverage).** The original suite
  measured `codex_app_server.py` at 76.7% of 30 changed branch arcs (floor
  80%). Five closed-leg branches were untested: non-object create output, object
  create output without `session_id`, unparseable create output, a raising
  create `exec`, and the blank/non-object stream-line legs. Added the five
  named tests above; `scripts/check-diff-coverage.py --base
  fad17a87c34193a91c568eb8b0a910e8e6384ccd --branch-fail-under 80` now passes
  (27/30 → 28/30 branch arcs; the three remaining partials are the defensive
  `thread_id is None` / `thread_id is not None` guards that the public API
  cannot reach).
- **Supply chain (pip-audit).** `aiohttp==3.14.3` (transitive, via `cosmic-ray`)
  reports `CVE-2026-111064`, `CVE-2026-111063`, `GHSA-2g87-pp6c-29x5`; fixed
  versions exist, so the gate's allowlist cannot absorb them. Bumped the
  lockfile: `uv lock --upgrade-package aiohttp` → `aiohttp 3.14.5`,
  `yarl 1.25.1`. `scripts/pip_audit_gate.py` now passes (the only remaining
  advisory, `ecdsa==0.19.2 PYSEC-2026-1325`, is already in `ALLOWED`). Note:
  this advisory is also red on the develop base commit, so it is pre-existing
  debt, not introduced by this branch; the bump is still the correct fix and
  lands here because the gate is in this lane's blocking set.
