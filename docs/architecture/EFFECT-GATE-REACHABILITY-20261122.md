# Direct-effect reachability review, 2026-11-22

**Status:** scoped code census, not evidence of end-to-end safety and not a new M1 issue.  
**Baseline:** current `develop` files accessed via GitHub. No tests or production traces run.
**Owner:** [#55 one governed effect path](https://github.com/Agent-StrongHold/Project-mAIstro/issues/55), with related [#56 model egress](https://github.com/Agent-StrongHold/Project-mAIstro/issues/56) and [#1195 PM polling](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1195).

## Existing enforcement (do not duplicate)

- [`scripts/check_direct_effects.py`](../../scripts/check_direct_effects.py): curated AST check; refuses new undispositioned calls and stale ledger entries, with stable site keys rather than fragile line numbers. It is **not** a complete interprocedural, whole-program call graph.
- [`quality/direct-effect-call-sites.json`](../../quality/direct-effect-call-sites.json): **49 reviewed AST sites** at this snapshot, with no empty owner or disposition in the returned ledger.
- [`docs/testing/failpoint-matrix-evidence.md`](../testing/failpoint-matrix-evidence.md): existing 22-cell crash model. It demonstrates a generic work callback can double-apply an unguarded effect across crash/retry; governed Invocation's effect identity and reconciliation prevent duplicate dispatch in the **tested** cases.

### Current ledger census

| Category and disposition | Count | Existing owner(s) |
| --- | ---: | --- |
| PM_POLLING_EFFECT, MIGRATE_TO_GOVERNED_INVOCATION | 10 | #1195 |
| MODEL_EFFECT, MIGRATE_TO_GOVERNED_INVOCATION | 26 | #56, #59 and related |
| TOOL_EFFECT, INTENTIONAL_LIBRARY/INFRASTRUCTURE | 4 | #57 and related |
| MODEL_EFFECT, INTENTIONAL_LIBRARY/INFRASTRUCTURE | 7 | Existing model provider infrastructure |
| CANONICAL_INVOCATION, INTENTIONAL_LIBRARY/INFRASTRUCTURE | 2 | Existing effect owner |
| **Total** | **49** | |

**36 sites remain explicitly marked migration debt**, not 36 proven active unsafe effects. Per-code-path reachability must be proved separately, and some entries may already be retired from user-facing routes.

## Bounded candidates outside the curated scanner

These are **search and code-read findings**, not confirmed reachable defects:

| Source / call | Why relevant | Reachability disposition |
| --- | --- | --- |
| [HTTPToolExecutor.call](../../packages/maistro-core/src/maistro/agents/strategies/tool_http.py) | Direct dynamic `POST /tools/{name}` to external tool server; dynamic URL not in the curated model/PM URL recognizers | Class constructed in [agents/wiring.py](../../packages/maistro-core/src/maistro/agents/wiring.py); no non-test `.call` consumer confirmed in source search; treat as **candidate only** |
| [HomeAssistantIntegration.call_service](../../packages/maistro-core/src/maistro/integrations/home_assistant.py) | Dynamic HTTP POST can control locks, fans, switches and scenes | Source search found integration tests and outbound-policy tests, but did not establish a reachable Graph/Tool consumer |
| [event handlers](../../packages/maistro-core/src/maistro/events/handlers.py): webhook_action, ha_action | Direct external POST actions; model-specific conductor_chat_action is tracked | Existing [events/processing.py](../../packages/maistro-core/src/maistro/events/processing.py) has durable `HTTPHandlerCaller` receipt and ambiguity discipline; determine whether legacy handlers remain actual dispatchers |
| [GitHub gh helper](../../packages/maistro-core/src/maistro/tools/git/github.py): `_run_gh` | Can issue mutating `gh pr create` and other CLI operations | Search shows its own tests and an independent git server module; require actual entrypoint-to-call evidence and check the sandbox/effect boundary |

**Unacceptable shortcut:** flag every `httpx` call, read-only `GET`, or `subprocess` use as an M1 security bug. The failure property depends on *reachability, effect type, retryability, idempotency and governance*, not source text alone.

## Next executable proof for #55

1. Enumerate **actual registered Graph nodes, capability providers, API routes, CLI commands and event triggers** and identify which can reach each candidate. Record entrypoint, principal, Workspace, Binding, Invocation and physical effect path.
2. Treat `READ_ONLY`, `IDEMPOTENT`, `COMPENSATABLE`, and `IRREVERSIBLE` separately. Egress/SSRF safety alone does **not** guarantee authorization or crash-window dedupe.
3. For a confirmed mutating/irreversible consumer, test `kill after external effect before canonical commit`, `two workers reclaim stale fence`, `lost receipt/reconnect`, `policy revoked mid-run`, and `cross-workspace caller`. Demand effect-key reconciliation, explicit UNKNOWN or operator intervention, never an unproved second send.
4. Route improvements to existing owners #55/#56/#1195. Expand the **existing** `check_direct_effects.py` classifications using its baseline/grant ratchet, not a parallel scanner or runtime authority.
5. Do not mark #55 complete until the actual relevant **production** effects are governed; do not write 'duplicate effect' as a verified defect unless the live path is reproduced.

## Related interoperability PRs

- [AG-UI projection #2411](https://github.com/Agent-StrongHold/Project-mAIstro/pull/2411), no live client endpoint yet.
- [Agent Skills standards import/export #2502](https://github.com/Agent-StrongHold/Project-mAIstro/pull/2502), inert layout parser, not a tool admission.
- [A2A v1 status-only projection #2505](https://github.com/Agent-StrongHold/Project-mAIstro/pull/2505), no wire endpoint.
- [Main audit #2412](https://github.com/Agent-StrongHold/Project-mAIstro/pull/2412).

**ACP and MCP Apps:** targeted searches for ACP client messages and MCP Apps UI resource/content types did not find a shipped consumer; their integration is **deferred pending consumer demand**, not declared absent from every possible package.
